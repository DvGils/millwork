"""A session: one browser tab's state and tree, and the steps that change them.

Nothing in this file waits. Every method of a session is a step: it runs
from its first line to its last with nothing else in between, so a session
is never caught halfway through a change. Whatever waits on a session's
behalf (a handler, a hook, a request, the session's own life) is in
``millwork.work`` and reaches the state through these steps.

A session never holds a socket. What it has to say goes into its outbox,
and a connection carries it to the tab. It outlives its connection for a
grace period, so a reload or a dropped connection keeps its state.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlencode

from millwork import context, work
from millwork.chat import ChatTurn, Thread, UIMessage
from millwork.connection import REPLACED, Connection, End, Pipe
from millwork.files import FileRef, Reject, SessionFiles, content_to_file
from millwork.forms import resolve_files, validate
from millwork.nodes import Component, Tree, build, diff
from millwork.outbox import Outbox
from millwork.protocol import (
    Answer,
    Command,
    Event,
    Mount,
    Patch,
    Reply,
    Request,
    ServerError,
    SessionInfo,
    pack,
)
from millwork.scope import Scope, Timer
from millwork.tasks import Task
from millwork.turn import Turn
from millwork.ui import Button, Dialog, DropdownMenu, Text
from millwork.ui.chat import Chat
from millwork.ui.files import Download, FileUpload
from millwork.ui.form import Form

if TYPE_CHECKING:
    from millwork.app import App, PageDef

log = logging.getLogger("millwork.session")

RENDER_COALESCE_SECONDS = 0.05
# Messages from the tab still being handled; further ones are dropped until
# the backlog clears, so a flood cannot grow the set of children without bound.
MAX_INFLIGHT = 64
# What a session's page is doing: being opened or left, or there to be used.
SWITCHING, READY = "switching", "ready"


@dataclass
class Want:
    """A page the session is to go to: its first, or a navigation."""

    path: str
    first: bool = False
    done: asyncio.Future[None] | None = None


@dataclass
class Plan:
    """A handler that is to run in a turn, as an event was sorted into."""

    handler: Callable[..., Any]
    args: tuple[Any, ...]
    where: str
    said: str
    """How a failure is logged."""
    event: Event | None = None
    question: tuple[str, bool] | None = None
    form: str | None = None
    visit: int | None = None
    """The visit of a page the handler belongs to. A handler that is not of
    a page (a task's ``on_done``, a toast's button) has none."""
    more: dict[str, Any] = field(default_factory=dict)


class Session[S]:
    def __init__(self, app: App, page: PageDef, params: dict[str, str], path: str) -> None:
        self._loop = asyncio.get_running_loop()
        self.id = secrets.token_urlsafe(16)
        self.resume_token = secrets.token_urlsafe(24)
        self.app = app
        self.page = page
        self.params = params
        self.path = path
        self.user: Any = None
        # The path prefix the app runs under, as the tab's socket arrived under it,
        # for anything the session renders into a browser URL.
        self.base = ""
        # Who opened it, for the per-client cap: the user's id, or the address.
        self.client: str | None = None
        self.created = time.monotonic()
        # When its tab last went away, for the caps: the session longest without
        # a tab makes room first.
        self.detached_at = self.created

        # Its life. A session is open or over, its page is being switched or
        # is ready, and a page whose connect returned is owed a close.
        self.over = False
        self.stage = SWITCHING
        self.owed: PageDef | None = None
        self.visit = 0
        """Counts the pages the session has been on, so that what was meant
        for one page is not done to the next."""
        self.end_reason: str | None = None
        self.end_to: str | None = None
        self._end_asking: asyncio.Future[str | None] | None = None
        self._end_code = REPLACED
        self.scope = Scope(f"session {self.id[:6]}")
        self.turn = Turn()
        self.turn.on_free = self._turn_free
        self.outbox = Outbox()
        self.conn: Connection | None = None
        self._wanted: deque[Want] = deque([Want(path, first=True)])
        self._previous: tuple[PageDef, dict[str, str], str, Tree | None] | None = None
        self._wake: asyncio.Future[None] = self._loop.create_future()
        self.ended: asyncio.Future[None] = self._loop.create_future()
        """Done when the session is over."""
        self.opened: asyncio.Future[BaseException | None] = self._loop.create_future()
        """Done when the first page has connected, or could not: with what
        its connect raised, or None."""
        self.gone: asyncio.Future[None] = self._loop.create_future()
        """Done when nothing of the session is left: its page is closed."""
        self.falls_back = True
        """Whether a page that refuses with NotFound or Forbidden lands on
        the app's page for that. The test harness raises it instead."""
        self.runs_connect = True

        # The sign-in it runs on, and when that runs out in seconds since the
        # epoch. None without one: a public visitor, a proxy's or Dev's user.
        self.sign_in: str | None = None
        self.sign_in_expires: float | None = None
        self._expiry: Timer | None = None
        # The sign-in's key and the user as identified, for asking the app's
        # ``recheck`` about them again, and the timer that asks for a tab that
        # only sits open.
        self._identified: tuple[str, Any] | None = None
        self._recheck: Timer | None = None
        self._grace: Timer | None = None

        self.state: S = app.make_state()
        self.tree: Tree | None = None
        self.files = SessionFiles(self)
        self.tasks: list[Task[Any]] = []
        self._tasks_started = 0
        self._render_due = False
        # Due, and its timer fired while a handler held the turn: it is drawn
        # as the turn comes free.
        self._render_late = False
        self._render_timer: Timer | None = None
        self._print_asked = False
        self._asks: dict[str, _Ask] = {}
        self._toast_actions: dict[str, Callable[..., Any]] = {}
        # Requests in flight by id, each with the connection it came in on.
        self._requests: dict[str, tuple[asyncio.Task[Any] | None, Connection]] = {}
        # The handler request in flight per node and name: a newer one cancels it.
        self._queries: dict[tuple[str, str], asyncio.Task[Any]] = {}
        self._file_slots = asyncio.Semaphore(FILE_SLOTS)
        self._inflight = 0
        self._overflowed = False
        self._busy = False
        self._title_shown: str | None = None
        self.on_failure: Callable[[str, BaseException], None] | None = None
        """Told of every exception the session caught from the app's code, after the
        log line: a page function, a handler, a hook. The test harness raises them."""
        # The failure page's tree, while it is what the tab shows in place of
        # a page whose function raised.
        self._failure: Tree | None = None
        # Development warnings: each is said once per session; counters tell a
        # handler that changed nothing, and a thread that changed state, apart.
        self._warned: set[str] = set()
        self._slow_builds = 0
        self._handler_runs = 0
        self._noop_watch: tuple[str, int] | None = None
        self._threads: dict[str, Thread] = {}

    # What waits: the session's life and the awaited half of its API. They
    # are written in ``millwork.work`` and change nothing but through steps.
    ask = work.ask
    confirm = work.confirm
    end = work.end
    leave = work.leave
    stream = work.stream
    navigate_to = work.navigate_to
    stay_current = work.stay_current
    wait_for_task = work.wait_for_task

    # ------------------------------------------------------------- reading

    @property
    def closed(self) -> bool:
        """Whether the session is over."""
        return self.over

    @property
    def ready(self) -> bool:
        """Whether the session has a page that is there to be used: its
        connect has returned and it is mounted."""
        return not self.over and self.stage == READY

    @property
    def connected(self) -> bool:
        return self.conn is not None

    @property
    def has_tab(self) -> bool:
        return self.conn is not None

    @property
    def inflight(self) -> int:
        """Messages from the tab whose handling has not finished."""
        return self._inflight

    @property
    def _effects(self) -> int:
        """What the session has said and started so far, for telling a handler
        that changed nothing."""
        return self.outbox.posted + self._tasks_started

    def text(self, key: str, **vars: Any) -> str:
        """A framework message in the theme's words, for toasts and errors."""
        return self.app.theme.text(key, **vars)

    def owns_resume(self, token: str | None) -> bool:
        return token is not None and hmac.compare_digest(self.resume_token, token)

    def can(self, path: str) -> bool:
        """Whether this session's user may open the page at ``path``, for a
        link or a button that should only be there for who can follow it. It
        asks the page's own rule, so the answer is the one the page gives."""
        resolved = self.app.locate(path)
        if resolved is None:
            raise LookupError(f"no page at {path}")
        page, params = resolved
        return self.app.may(self.user, page, params).ok

    def leaving_for(self, to: str | None) -> str:
        """Where this session's tab goes when it is sent away: ``to``, or the
        login page for a page that needs a sign-in, or its own public page."""
        if to is not None:
            return to
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        return path if self.page.public else f"/_mw/login?{urlencode({'next': path})}"

    # ------------------------------------------------------------- ending

    def dismiss(
        self,
        message: str | None = None,
        *,
        to: str | None = None,
        asking: asyncio.Future[str | None] | None = None,
        code: int = REPLACED,
    ) -> None:
        """End the session. It is over as this returns: nothing more runs on
        it, nothing more is sent for it but the word that it ended, and its
        place among the app's sessions is free.

        With a ``message`` its tab is told why, and stops instead of
        connecting again. ``to`` sends the tab somewhere. While that is still
        being asked, ``asking`` is the future that will say, and ``to`` is
        where the tab goes if it does not. Without a message the tab is told
        nothing, and one that is still there connects again as new.

        The first to end a session decides what its tab is told. What is
        still owed after this, seeing its work out and closing its page, is
        done by the session's life.
        """
        if self.over:
            return
        self.over = True
        self.end_reason, self.end_to = message, to
        self._end_asking, self._end_code = asking, code
        self.app.sessions.pop(self.id, None)
        self.outbox.seal()
        conn, self.conn = self.conn, None
        if conn is not None:
            conn.close(self._notice())
        for task in list(self.tasks):
            # Told to stop as well as stopped: work in a thread cannot be
            # cancelled, and stops where it next looks at whether it was.
            task.cancel()
        self.scope.cancel()
        for ask in self._asks.values():
            if not ask.future.done():
                ask.future.set_result(None)
        while self._wanted:
            # Nobody gets to the pages that were still wanted.
            want = self._wanted.popleft()
            if want.done is not None and not want.done.done():
                want.done.set_result(None)
        self.ended.set_result(None)
        if not self._wake.done():
            self._wake.set_result(None)

    def _notice(self) -> End | None:
        """What a tab of a session that is over is told, if anything."""
        if self.end_reason is None:
            return None
        return End(self.end_reason, self.end_to, self._end_asking, self._end_code)

    # -------------------------------------------------------- connections

    def attached(self, conn: Connection, last_seq: int) -> None:
        """A tab connected, or came back. It takes the place of the
        connection the session had, which is told so and closes its socket:
        a duplicated tab cannot go on acting on the session."""
        if self.over:
            # The tab of a session that ended is told what its session was.
            conn.close(self._notice())
            return
        old, self.conn = self.conn, conn
        if old is not None:
            old.close(code=REPLACED)
            self._drop_requests(old)
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None
        # A tab with nothing seen gets the page as it stands, unless nothing
        # has been said yet: then it follows from the start, so what the
        # first connect hook says before the page is drawn reaches it.
        if last_seq <= 0:
            last_seq = 0 if self.outbox.seq == 0 else -1
        conn.bind(self, last_seq)

    def detached(self, conn: Connection) -> None:
        """A connection is gone. Only the session's current one counts."""
        if self.conn is not conn:
            return
        self.conn = None
        self.detached_at = time.monotonic()
        self._drop_requests(conn)
        if not self.over:
            self._grace = self.scope.later(self.app.session_grace, self._grace_over)

    def _grace_over(self) -> None:
        self._grace = None
        if self.conn is None:
            self.dismiss()

    def hello(self) -> str:
        """What a connection says first: which session this is."""
        info = SessionInfo(
            id=self.id, resume=self.resume_token, components=self.app.component_versions
        )
        return pack(self.outbox.seq, info)

    def mounted(self) -> str | None:
        """The page as it was last drawn, for a tab that cannot be caught up
        from the outbox. No page function runs for it."""
        tree = self.tree
        if tree is None or self.stage != READY:
            return None
        return pack(
            self.outbox.seq, Mount(root=tree.root, nodes=tree.nodes, title=self._title_shown)
        )

    # ----------------------------------------------------------- sign-in

    def watch_sign_in(self, sign_in: tuple[str, float] | None) -> None:
        """End the session when the sign-in it runs on expires: the sign-in's
        id and its expiry in seconds since the epoch, or None without one.
        Called again when the tab comes back, since the person may have signed
        in anew."""
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        self.sign_in, self.sign_in_expires = sign_in or (None, None)
        if sign_in is not None and not self.over:
            delay = sign_in[1] - time.time()
            if delay <= 0:
                # It ran out while the session was being connected. That is
                # acted on here and now, before anything of the page is sent,
                # and not a moment later when a timer gets round to it.
                self._sign_in_expired()
            else:
                self._expiry = self.scope.later(delay, self._sign_in_expired)

    def _sign_in_expired(self) -> None:
        self._expiry = None
        if not self.over and self.sign_in is not None:
            self.app.end_sign_in(self.sign_in, self.user)

    def watch_user(self, identified: tuple[str, Any] | None) -> None:
        """Keep asking the app's ``recheck`` about this session's user for as
        long as the session lives: ``identified`` is the sign-in's key and
        the user as identified, as the request that opened or resumed the
        session carried them. Asked when the last answer runs out, so a tab
        that only sits open is as current as one that is being used."""
        self._identified = identified
        if self._recheck is not None:
            self._recheck.cancel()
            self._recheck = None
        auth = self.app.auth
        if auth is None or auth.recheck is None or identified is None or self.over:
            return
        # A little past the moment the answer runs out, so the ask finds it stale.
        self._recheck = self.scope.later(auth.ask_again_in(*identified) + 0.01, self._recheck_due)

    def _recheck_due(self) -> None:
        self._recheck = None
        self.scope.start(work.recheck(self), "recheck")

    # ------------------------------------------------------------- pages

    def navigate(self, path: str) -> None:
        """Go to another page on this session: its connect runs, the tab's history
        updates. This returns at once; ``navigate_to`` is the same, awaited."""
        self.want(path)

    def want(self, path: str) -> asyncio.Future[None]:
        """Ask for another page. The future is done when the session is on
        it, or has given up on getting there."""
        done: asyncio.Future[None] = self._loop.create_future()
        if self.over:
            done.set_result(None)
            return done
        if len(self._wanted) >= MAX_INFLIGHT:
            if not self._overflowed:
                self._overflowed = True
                log.warning("session %s: %d messages pending, dropping", self.id, MAX_INFLIGHT)
                self.post(ServerError(message=self.text("too_many_actions"), fatal=False))
            done.set_result(None)
            return done
        self._wanted.append(Want(path, done=done))
        if not self._wake.done():
            self._wake.set_result(None)
        return done

    def idle(self) -> asyncio.Future[None]:
        """For the session's life: done when a page is wanted or the session
        is over."""
        if self._wanted or self.over:
            ready: asyncio.Future[None] = self._loop.create_future()
            ready.set_result(None)
            return ready
        if self._wake.done():
            self._wake = self._loop.create_future()
        return self._wake

    def take_wanted(self) -> Want:
        """The next page to go to. From here until it is settled the page is
        being switched: nothing is drawn and no event of the page left is
        acted on."""
        self.stage = SWITCHING
        return self._wanted.popleft()

    def aim(self, want: Want) -> tuple[PageDef, dict[str, str], str, str] | None:
        """Where a navigation leads: the page, its parameters, the path and
        the fragment. None, with the tab told, when the session's user may
        not go there at all."""
        path, _, fragment = want.path.partition("#")
        page, params = self.app.locate(path) or self.app.fallback("not_found", path)
        if self.app.auth is not None and not page.public and self.user is None:
            self.post(ServerError(message=self.text("sign_in_hint"), fatal=True))
            self.stage = READY
            return None
        return page, params, path, fragment

    def enter(self, page: PageDef, params: dict[str, str], path: str) -> None:
        """Step onto the page a navigation leads to, for its connect to run.
        What the session was on is kept, to go back to if that fails."""
        self._previous = (self.page, self.params, self.path, self.tree)
        self.page, self.params, self.path = page, params, path
        self.tree = None
        self._slow_builds = 0

    def fall_back(self, kind: str, message: str | None) -> None:
        """Land on the app's page for a page that refused, under the path
        that was asked for."""
        self.page, self.params = self.app.fallback(kind, self.path, message)

    def take_owed(self) -> PageDef | None:
        """The page that is owed a close, which it is not after this."""
        page, self.owed = self.owed, None
        return page

    def settle_page(self, want: Want, outcome: str, error: BaseException | None = None) -> None:
        """A page's connect has had its outcome: ``ok``, ``unhooked`` (its
        hook was skipped, so no close is owed), ``failed`` or ``cancelled``.
        The page is ready and mounted, or the session is back on the page
        it came from, or, for a first page that failed, over."""
        if self.over:
            if outcome == "ok":
                # Its connect returned all the same, so it is owed a close.
                self.owed = self.page
            if not self.opened.done():
                self.opened.set_result(error)
            return
        if outcome in ("ok", "unhooked"):
            self.owed = self.page if outcome == "ok" else None
            self.stage = READY
            self.visit += 1
            for ask in list(self._asks.values()):
                if not ask.future.done():
                    ask.future.set_result(None)
            self._asks.clear()
            if not want.first:
                _, _, fragment = want.path.partition("#")
                args: dict[str, Any] = {"path": self.path, "title": self.page.title}
                if fragment:
                    # A fragment names a heading: the tab scrolls to it after the mount.
                    args["hash"] = fragment
                self.command("navigate", **args)
            self._mount()
            if not self.opened.done():
                self.opened.set_result(None)
        elif want.first:
            if not self.opened.done():
                self.opened.set_result(error)
            self.dismiss(self.text("page_failed"), code=4500)
        else:
            # The tab keeps the page it came from, already closed. What the
            # failed connect wrote to the state stays.
            assert self._previous is not None
            self.page, self.params, self.path, self.tree = self._previous
            self.stage = READY
            self.post(ServerError(message=self.text("page_failed"), fatal=False))
        self._previous = None

    # ------------------------------------------------------------- sending

    def post(self, msg: Any) -> bool:
        """Say something to the tab: numbered, kept for replay, and sent by
        whatever connection the session has. Dropped once the session is over."""
        return self.outbox.post(msg)

    def _failed(self, where: str, exc: BaseException) -> None:
        if self.on_failure is not None:
            self.on_failure(where, exc)

    def command(self, name: str, **args: Any) -> None:
        """An instruction to the tab: toast, navigate, clipboard."""
        self.post(Command(name=name, args=args))

    def toast(
        self,
        message: str,
        tone: str = "default",
        title: str | None = None,
        action: tuple[str, Callable[..., Any]] | None = None,
    ) -> None:
        """A toast; ``action=(label, handler)`` adds a button that runs the handler once."""
        args: dict[str, Any] = {"message": message, "tone": tone, "title": title}
        if action is not None:
            label, handler = action
            token = secrets.token_urlsafe(8)
            self._toast_actions[token] = handler
            while len(self._toast_actions) > 20:
                self._toast_actions.pop(next(iter(self._toast_actions)))
            args["action"] = {"id": token, "label": label}
        self.command("toast", **args)

    def clipboard(self, text: str) -> None:
        """Put text on the tab's clipboard."""
        self.command("clipboard", text=text)

    def print(self) -> None:
        """Open the browser's print dialog on the page, which is also how a
        person saves it as a PDF. It opens after the page has been drawn
        again, so what the handler changed first is what gets printed."""
        self._print_asked = True
        self.refresh()

    def logout(self) -> None:
        """Sign out: clear the cookie and send the tab to the login page, or
        where the app's ``on_logout`` says."""
        self.command("logout")

    def reset(self, key: str) -> None:
        """Put the component with this key back to its default: the draft an
        input holds, a form's fields, a tab strip's choice."""
        self.command("reset", key=key)

    def download(self, filename: str, content: Any, mime: str | None = None) -> FileRef:
        """Send a file to the tab without a button: the tab fetches it over the socket."""
        ref = content_to_file(self, content, filename, mime)
        self.command("download", id=ref.id, filename=filename)
        return ref

    # ------------------------------------------------------------- chat

    def chat(self, key: str) -> Thread:
        """The messages of the Chat with this key; created on first use."""
        thread = self._threads.get(key)
        if thread is None:
            thread = self._threads[key] = Thread()
        return thread

    def drop_chat(self, key: str) -> None:
        """Forget the thread under this key, unless a reply is running in it: the
        Chat with that key starts empty next time. An app whose threads live in
        a store keeps only the open one in the session this way."""
        thread = self._threads.get(key)
        if thread is not None and not thread.busy:
            del self._threads[key]

    def _chat_message(self, event: Event, component: Chat) -> None:
        """A user turn: record the message, run the handler as this thread's turn."""
        if component.key is None:
            log.warning("a Chat needs a key to keep its messages")
            return
        thread = self.chat(component.key)
        thread.limit = component.max_messages
        if thread.busy:
            self.toast(self.text("wait_for_reply"), tone="warning")
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        text = str(payload.get("text") or "").strip()
        if len(text) > component.max_chars:
            self.toast(self.text("message_too_long"), tone="warning")
            return
        ids = [d.get("id") for d in payload.get("files") or [] if isinstance(d, dict)]
        files = [
            ref
            for i in ids
            if isinstance(i, str)
            and (ref := self.files.get(i)) is not None
            and ref.node == event.node
        ]
        if component.attachments is not None:
            files = files[: component.attachments.max_files]
        # A command is a message on its own: one that takes no words is sent
        # with none.
        command = payload.get("command")
        if not isinstance(command, str) or not command:
            command = None
        if not text and not files and command is None:
            return
        parts: list[dict[str, Any]] = []
        if text:
            parts.append({"type": "text", "text": text})
        for ref in files:
            parts.append(
                {
                    "type": "file",
                    "mediaType": ref.mime,
                    "url": "",
                    "filename": ref.name,
                    "fileId": ref.id,
                }
            )
        metadata: dict[str, Any] = {"at": time.time()}
        if command is not None:
            metadata["command"] = command
        message = UIMessage(
            id=secrets.token_urlsafe(8), role="user", parts=parts, metadata=metadata
        )
        thread.append(message)
        self._chat_run(event.node, thread, message)

    def _chat_run(self, node_id: str, thread: Thread, message: UIMessage) -> None:
        """Run ``on_message`` for a user message the thread holds: a new one, or one
        sent again after an edit or a regenerate."""
        files = [
            ref
            for p in message.parts
            if p.get("type") == "file"
            and isinstance(p.get("fileId"), str)
            and (ref := self.files.get(p["fileId"])) is not None
        ]
        command = (message.metadata or {}).get("command")
        turn = ChatTurn(
            self, node_id, thread, message, files, command if isinstance(command, str) else None
        )
        handler = self.tree.handler(node_id, "message") if self.tree else None
        self.refresh()
        if handler is None:
            return
        # The turn is not held while a reply streams: tool steps, tasks and
        # inline components render meanwhile; the composer is disabled by `busy`.
        thread.turn_task = self.scope.start(
            work.chat_turn(self, handler, turn), "chat turn", done=lambda _: self._chat_done(thread)
        )
        if thread.turn_task is None:
            self._chat_done(thread)

    def _chat_done(self, thread: Thread) -> None:
        """A reply is over, however it ended: the chat is free again."""
        thread.turn_task = None
        if thread.inflight is not None:
            thread.append(thread.inflight)
            thread.inflight = None
        self.refresh()

    def _chat_stop(self, event: Event, component: Chat) -> Plan | None:
        thread = self.chat(component.key) if component.key else None
        if thread is not None and thread.turn_task is not None:
            thread.turn_task.cancel()
        handler = self.tree.handler(event.node, "stop") if self.tree else None
        return self._plain(handler, None) if handler is not None else None

    def _chat_target(
        self, event: Event, component: Chat, role: str
    ) -> tuple[Thread, int, dict[str, Any]] | None:
        """The thread and the index of the message an action names, when it is
        one of this chat's with the expected role and the thread is free."""
        if component.key is None:
            return None
        thread = self.chat(component.key)
        payload = event.payload if isinstance(event.payload, dict) else {}
        message_id = payload.get("id")
        index = thread.find(message_id) if isinstance(message_id, str) else None
        if index is None or thread.messages[index].role != role:
            return None
        return thread, index, payload

    def _chat_feedback(self, event: Event, component: Chat) -> Plan | None:
        """Thumbs up or down on an assistant message, with a comment; kept in the
        message's metadata so it shows after a reload, and given to ``on_feedback``."""
        target = self._chat_target(event, component, "assistant")
        if target is None:
            return None
        thread, index, payload = target
        value = payload.get("value")
        if value not in ("up", "down", None):
            return None
        comment = str(payload.get("comment") or "").strip()[:2000] or None
        message = thread.messages[index]
        metadata = dict(message.metadata or {})
        if value is None:
            metadata.pop("feedback", None)
        else:
            metadata["feedback"] = {"value": value, "comment": comment}
        message.metadata = metadata or None
        handler = self.tree.handler(event.node, "feedback") if self.tree else None
        if handler is not None:
            return self._plain(handler, message, value, comment)
        self.refresh()
        return None

    def _chat_action(self, event: Event, component: Chat) -> Plan | None:
        target = self._chat_target(event, component, "assistant")
        if target is None:
            return None
        thread, index, payload = target
        action = payload.get("action")
        if not any(a.id == action for a in component.actions):
            return None
        handler = self.tree.handler(event.node, "action") if self.tree else None
        if handler is not None:
            return self._plain(handler, thread.messages[index], action)
        return None

    def _chat_regenerate(self, event: Event, component: Chat) -> None:
        """Answer a user message again: the assistant message named and everything
        after it go, and ``on_message`` runs for the user message before it."""
        target = self._chat_target(event, component, "assistant")
        if target is None or not component.regenerate:
            return
        thread, index, _ = target
        if thread.busy:
            self.toast(self.text("wait_for_reply"), tone="warning")
            return
        user = next(
            (i for i in range(index - 1, -1, -1) if thread.messages[i].role == "user"), None
        )
        if user is None:
            return
        thread.truncate(index)
        self._chat_run(event.node, thread, thread.messages[user])

    def _chat_edit(self, event: Event, component: Chat) -> None:
        """A user message with new text: what followed it goes, and it is answered again."""
        target = self._chat_target(event, component, "user")
        if target is None or not component.edit:
            return
        thread, index, payload = target
        if thread.busy:
            self.toast(self.text("wait_for_reply"), tone="warning")
            return
        text = str(payload.get("text") or "").strip()
        if len(text) > component.max_chars:
            self.toast(self.text("message_too_long"), tone="warning")
            return
        message = thread.messages[index]
        files = [p for p in message.parts if p.get("type") == "file"]
        if not text and not files:
            return
        message.parts = ([{"type": "text", "text": text}] if text else []) + files
        thread.truncate(index + 1)
        self._chat_run(event.node, thread, message)

    def spawn(self, coro: Any, what: str = "work") -> asyncio.Task[Any] | None:
        """Run a coroutine for this session: it is one of the session's own,
        stopped when the session ends, and a failure it lets out is logged.
        On a session that is over it does not run at all, and there is no
        task to return."""
        return self.scope.start(coro, what)

    # ------------------------------------------------------------- tasks

    def task(
        self,
        work: Any,
        *args: Any,
        label: str | None = None,
        key: str | None = None,
        replace: bool = False,
        delay: float | None = None,
        timeout: float | None = None,
        on_done: Callable[..., Any] | None = None,
        quiet: bool = False,
        **kwargs: Any,
    ) -> Task[Any]:
        """Start work the session owns."""
        self._tasks_started += 1
        if key is not None:
            for existing in self.tasks:
                if existing.key == key and not existing.done:
                    if not replace:
                        return existing
                    existing.cancel()
        name = label or getattr(work, "__name__", None) or "task"
        task: Task[Any] = Task(self, name, key, quiet)
        task._on_done = on_done
        if on_done is not None:
            task._observed = True
        if not self.over:
            self.tasks.append(task)
        # On a session that is over the scope starts nothing, and the task
        # ends as cancelled there and then.
        task._begin(work, args, kwargs, timeout, delay)
        if delay and not self.over:
            self.refresh()
        return task

    def later(self, delay: float, work: Any, *args: Any, **kwargs: Any) -> Task[Any]:
        """``task``, started after ``delay`` seconds."""
        return self.task(work, *args, delay=delay, **kwargs)

    def thread(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Task[Any]:
        """``task`` for a sync function: it runs in a worker thread."""
        return self.task(fn, *args, **kwargs)

    def _task_finished(self, task: Task[Any]) -> None:
        """A task reached a terminal status: run ``on_done`` as a handler, then render."""
        on_done = getattr(task, "_on_done", None)
        if on_done is not None and not self.over:
            # One of the session's own, so it ends with the session, and none
            # for a task the end itself cancelled.
            self._start_turn(self._plain(on_done, task), "on_done")
        if len(self.tasks) > 50:
            self.tasks = [t for t in self.tasks if not t.done][-50:] + [
                t for t in self.tasks if t.done
            ][-10:]
        self.refresh()

    # ------------------------------------------------------------- turns

    def _plain(self, handler: Callable[..., Any], *args: Any) -> Plan:
        """A handler that is not an event's own: a task's ``on_done``, a
        chat's ``on_stop``."""
        name = getattr(handler, "__name__", handler)
        return Plan(handler, (self, *args), f"the handler {name}", f"handler {name} failed")

    def _start_turn(self, plan: Plan, name: str) -> None:
        """Run a handler as a child that takes its turn. The scope gives the
        turn back when the child is done, however it ends."""
        self._inflight += 1
        self.scope.start(work.turn(self, plan), name, done=self._turn_done)

    def _turn_done(self, child: asyncio.Task[Any] | None) -> None:
        self._inflight -= 1
        if child is not None:
            self.turn.give_back(child)

    def _handler_begins(self) -> int:
        self._handler_runs += 1
        return self._effects

    def _handler_ended(self, where: str, before: int) -> None:
        self._noop_watch = (where, before)

    # ------------------------------------------------------------- asking

    def open_ask(self, component: Component) -> _Ask:
        """Put a question on the page. Its future gets the answer."""
        request = secrets.token_urlsafe(8)
        ask = _Ask(
            request=request, component=_askable(component), future=self._loop.create_future()
        )
        self._asks[request] = ask
        self.refresh()
        return ask

    def close_ask(self, ask: _Ask) -> None:
        if self._asks.get(ask.request) is ask:
            del self._asks[ask.request]
        self.refresh()

    def _confirm_dialog(
        self,
        title: str,
        description: str | None,
        ok: str | None,
        cancel: str | None,
        destructive: bool,
    ) -> Component:
        buttons = _ConfirmButtons(
            children=[
                Button(
                    cancel or self.text("cancel"),
                    key="cancel",
                    variant="outline",
                    on_click=_noop,
                ),
                Button(
                    ok or self.text("ok"),
                    key="ok",
                    variant="destructive" if destructive else "primary",
                    on_click=_noop,
                ),
            ]
        )
        return Dialog(
            *([Text(description)] if description else []),
            title=title,
            size="sm",
            footer=buttons,
        )

    def _ask_root(self, request: str) -> str:
        return f"{self.tree.root if self.tree else 'root'}/@ask:{request}"

    def _answer_ask(self, event: Event, component: Component | None) -> bool:
        """An event inside an open ask: resolve it, or let it through to its own handler."""
        for request, ask in self._asks.items():
            prefix = self._ask_root(request)
            if event.node != prefix and not event.node.startswith(prefix + "/"):
                continue
            if ask.future.done():
                return True
            if event.name == "submit" and isinstance(component, Form):
                draft = resolve_files(event.payload, self._form_file(event.node))
                instance, issues = validate(component.model, draft, self.text)
                if issues:
                    self.command(
                        "form_issues", node=event.node, issues=[i.model_dump() for i in issues]
                    )
                    return True
                ask.future.set_result(instance)
                return True
            if event.name in ("close", "cancel"):
                ask.future.set_result(None)
                return True
            if event.name == "click" and event.node.endswith("/ok"):
                ask.future.set_result(True)
                return True
            if event.name == "click" and event.node.endswith("/cancel"):
                ask.future.set_result(None)
                return True
            return False
        return False

    # ------------------------------------------------------------- rendering

    def refresh(self) -> None:
        """Render soon. Coalesced: many calls in one tick are one patch."""
        if self.over:
            return
        self._render_due = True
        if self._render_timer is None:
            self._render_timer = self.scope.later(RENDER_COALESCE_SECONDS, self._render_tick)

    def _render_tick(self) -> None:
        self._render_timer = None
        if self.turn.free:
            self.render()
        else:
            # A handler is in the middle of its turn. The page is drawn when
            # it is done, and never from state it has half changed.
            self._render_late = True

    def _turn_free(self) -> None:
        if self._render_late:
            self.render()

    def flush(self) -> None:
        """Render now what is due, if the turn is free. For the test harness,
        which does not wait out the timer."""
        if self._render_timer is not None:
            self._render_timer.cancel()
            self._render_timer = None
        if self._render_due:
            self._render_tick()

    def _mount(self) -> None:
        """Put the page on a tab that has nothing of it: no page yet, or the
        failure page."""
        self._render_due = self._render_late = False
        failed_before = self.tree is not None and self.tree is self._failure
        try:
            tree = self._page_tree()
        except Exception as exc:
            # A page that fails again under its failure page says so in a
            # toast, as a page that fails under itself does.
            self._render_failed(exc, told=failed_before)
            if failed_before:
                return
            # The tab has nothing of this page to keep, so the failure is
            # said where the page would be. A later render that works is
            # mounted in its place.
            failure = self._failure_tree(exc)
            if failure is None:
                self.post(ServerError(message=self.text("render_failed"), fatal=False))
                return
            tree = self._failure = failure
        else:
            self._failure = None
        self.tree = tree
        self._title_shown = self._title(tree)
        self.post(Mount(root=tree.root, nodes=tree.nodes, title=self._title_shown))

    def _title(self, tree: Tree) -> str | None:
        """The tab's title: the root ``Page``'s own when it has one, else the page's."""
        root = tree.nodes[tree.root]
        title = root.props.get("title") if root.type == "Page" else None
        return title if isinstance(title, str) else self.page.title

    def render(self) -> None:
        """Draw the page from the state as it stands and say what changed.
        Only when the page is ready and nobody is in the middle of a turn."""
        self._render_late = False
        if self.over or self.stage != READY or not self._render_due:
            return
        self._render_due = False
        if self.tree is None or self.tree is self._failure:
            self._mount()
            return
        tree = self._build()
        if tree is None:
            return
        ops = diff(self.tree, tree)
        self._check_keyless(self.tree, tree)
        self.tree = tree
        if ops:
            self.post(Patch(ops=ops))
        if self._print_asked:
            # After the patch, which is the page the handler meant to print.
            self._print_asked = False
            self.command("print")
        title = self._title(tree)
        if title != self._title_shown:
            self._title_shown = title
            self.command("title", title=title)
        watch, self._noop_watch = self._noop_watch, None
        quiet = watch is not None and not ops and self._effects == watch[1]
        self._signal_activity()
        if watch is not None and quiet:
            self.warn(
                f"noop:{watch[0]}",
                f"{watch[0]} changed nothing the page shows: no patch, no command, "
                "no task. A forgotten await, state the page does not draw, or a "
                "handler that should not be one?",
            )

    def _check_keyless(self, old: Tree, new: Tree) -> None:
        """A run of keyless same-type siblings whose length changed is a data list
        without keys: every row after the change is redrawn instead of moved."""
        for node_id, kind in new.keyless_runs.items():
            before = old.nodes.get(node_id)
            if before is not None and len(before.children) != len(new.nodes[node_id].children):
                self.warn(
                    f"keyless:{node_id}",
                    f"{node_id} is a list of {kind} rows without keys; give each a key so "
                    "a change moves rows instead of redrawing them",
                )

    def warn(self, key: str, message: str) -> None:
        """A development warning: one log line per session and key, and in debug mode a
        toast as well, so the author sees it where it happened."""
        if key in self._warned:
            return
        self._warned.add(key)
        log.warning("%s: %s", self.page.path, message)
        if self.app.debug:
            self.command("toast", message=message, tone="warning", title="millwork")

    def _signal_activity(self) -> None:
        """Tell the tab when work starts and ends, so it can keep a host that scales
        to zero awake while a task or a reply is running."""
        busy = any(not t.done for t in self.tasks) or any(th.busy for th in self._threads.values())
        if busy != self._busy:
            self._busy = busy
            self.command("activity", busy=busy)

    def _failure_tree(self, error: BaseException) -> Tree | None:
        """The framework's page for a page function that raised, or None when
        that cannot be built either."""
        from millwork.app import _failed_view

        token = context.bind(self)
        try:
            return build(_failed_view(self, error))
        except Exception:
            log.exception("the failure page of %s could not be built", self.page.path)
            return None
        finally:
            context.unbind(token)

    def _render_failed(self, exc: BaseException, told: bool) -> None:
        """The page function raised: logged, and said to the tab as a toast
        when the tab keeps showing what it had."""
        log.exception("page %s failed to render", self.page.path)
        self._failed(f"the page function of {self.page.path}", exc)
        if told:
            self.post(ServerError(message=self.text("render_failed"), fatal=False))

    def _build(self) -> Tree | None:
        """The page's tree, or None when the page function raised: the tab
        keeps the page it has and is told."""
        try:
            return self._page_tree()
        except Exception as exc:
            self._render_failed(exc, told=True)
            return None

    def _page_tree(self) -> Tree:
        # Bound for the render and the build: wire values (a FileRef, a task)
        # read the current session while the tree is walked.
        token = context.bind(self)
        try:
            started = time.perf_counter()
            root = self.page.render(self)
            took = (time.perf_counter() - started) * 1000
            # Two slow builds in a row: a page that does I/O is slow every time,
            # while one wall-clock hiccup (a collection, a busy process) is not.
            self._slow_builds = self._slow_builds + 1 if took > SLOW_PAGE_MS else 0
            if self._slow_builds >= 2:
                self.warn(
                    "slow-page",
                    f"the page function took {took:.0f} ms; it should build the tree and "
                    "nothing else, so move I/O to connect or a task",
                )
            if not isinstance(root, Component):
                raise TypeError(
                    f"page {self.page.path} returned {type(root).__name__}, not a component"
                )
            for request, ask in self._asks.items():
                root.children.append(ask.component.model_copy(update={"key": f"@ask:{request}"}))
            return build(root)
        finally:
            context.unbind(token)

    # ------------------------------------------------------------- events

    def event(self, event: Event) -> None:
        """The tab says something happened on a node. It is looked at by a
        child of the session, which takes its turn if a handler is to run."""
        if self.over:
            return
        if self._inflight >= MAX_INFLIGHT and "/@ask:" not in event.node:
            # An answer to an open question resolves a waiting handler and
            # starts no new work, so it passes the bound: the backlog cannot
            # clear without it.
            if not self._overflowed:
                self._overflowed = True
                log.warning("session %s: %d messages pending, dropping", self.id, MAX_INFLIGHT)
                self.post(ServerError(message=self.text("too_many_actions"), fatal=False))
            return
        self._overflowed = False
        self._inflight += 1
        self.scope.start(
            work.event(self, event), f"event {event.name} on {event.node}", done=self._turn_done
        )

    def answer(self, msg: Answer) -> None:
        """The tab answered an ``ask``. Asks arrive with tasks; until then, log."""
        log.warning("answer for unknown request %s", msg.request)

    def sort(self, event: Event) -> Plan | None:
        """What an event comes to: done here and now when it needs no turn,
        or a handler to run in one.

        Everything the tab sends is untrusted: the node must exist in the
        current tree, a disabled component takes no events, an upload refers
        only to files uploaded for that node, a form submit is validated
        before its handler sees it.
        """
        if self.tree is None or self.over or self.stage != READY:
            return None
        if event.node.startswith("toast:") and event.name == "action":
            handler = self._toast_actions.pop(event.node[6:], None)
            if handler is None:
                log.debug("toast action %s unknown or already used", event.node[6:])
                return None
            return Plan(handler, (self, None), "a toast action", "toast action failed")
        component = self.tree.components.get(event.node)
        if component is None:
            log.debug("event %s for unknown node %s", event.name, event.node)
            return None
        if self._asks and self._answer_ask(event, component):
            return None
        if getattr(component, "disabled", False):
            log.debug("event %s on disabled node %s dropped", event.name, event.node)
            return None
        if (
            isinstance(component, Form)
            and component.read_only
            and event.name in ("submit", "cancel")
        ):
            return None
        payload = event.payload

        if isinstance(component, Chat):
            chat_events: dict[str, Callable[[Event, Chat], Plan | None]] = {
                "message": self._chat_message,
                "stop": self._chat_stop,
                "feedback": self._chat_feedback,
                "action": self._chat_action,
                "regenerate": self._chat_regenerate,
                "edit": self._chat_edit,
            }
            if event.name in chat_events:
                return chat_events[event.name](event, component)

        if event.name == "download" and isinstance(component, Download):
            token = context.bind(self)
            try:
                self.download(component.filename, component.content, component.mime)
            except Exception as exc:
                log.exception("download %s failed", component.filename)
                self._failed(f"the download of {component.filename}", exc)
                self.toast(self.text("download_failed"), tone="destructive")
            finally:
                context.unbind(token)
            return None

        handler = self.tree.handler(event.node, event.name)
        if handler is None:
            log.warning("no handler for %s on %s", event.name, event.node)
            return None

        if event.name == "upload" and isinstance(component, FileUpload):
            # The tab echoes the upload route's answers; the session's own records are
            # the truth, and only files uploaded for this node count.
            ids = [d.get("id") for d in payload or [] if isinstance(d, dict)]
            payload = [
                ref
                for i in ids
                if isinstance(i, str)
                and (ref := self.files.get(i)) is not None
                and ref.node == event.node
            ][: component.max_files if component.multiple else 1]
            if not payload:
                return None

        form: str | None = None
        if event.name == "submit" and isinstance(component, Form):
            form = event.node
            draft = resolve_files(payload, self._form_file(event.node))
            instance, issues = validate(component.model, draft, self.text)
            if issues:
                self.command(
                    "form_issues", node=event.node, issues=[i.model_dump() for i in issues]
                )
                return None
            payload = instance

        return Plan(
            handler,
            (self, payload),
            f"the {event.name} handler on {event.node}",
            f"handler {event.name} on {event.node} failed",
            event=event,
            question=_confirmation(component, event),
            form=form,
            visit=self.visit,
        )

    def _form_file(self, node: str) -> Callable[[str], FileRef | None]:
        """A lookup for the files a form's draft refers to: uploaded for that form, or none."""

        def lookup(file_id: str) -> FileRef | None:
            ref = self.files.get(file_id)
            return ref if ref is not None and ref.node == node else None

        return lookup

    # --------------------------------------------------------- requests

    def request(self, conn: Connection, msg: Request, pipe: Pipe | None) -> None:
        """Begin answering a ``request`` with a ``reply``, for the connection
        it came in on. Registered here, in the step, so that a ``cancel`` or
        the bytes right behind it on the socket find it. What is registered
        here is taken back by the scope when the child is done, however it
        ends, and that includes a child that never ran a line."""
        if self.over:
            conn.forget(msg.request)
            return
        if msg.request in self._requests:
            if pipe is not None:
                conn.forget(msg.request)
            conn.say(Reply(request=msg.request, error="duplicate request"))
            return
        if len(self._requests) >= MAX_REQUESTS:
            conn.forget(msg.request)
            conn.say(Reply(request=msg.request, error="too many requests"))
            return
        key = (msg.node, msg.name) if msg.name not in ("file", "upload") else None
        self._requests[msg.request] = (None, conn)
        child = self.scope.start(
            work.request(self, conn, msg, pipe),
            f"request {msg.name} on {msg.node}",
            done=lambda done: self._request_done(conn, msg.request, key, done),
        )
        if child is None or msg.request not in self._requests:
            return
        self._requests[msg.request] = (child, conn)
        if key is not None:
            # A newer handler request on the same node and name takes the
            # place of the one in flight: a search never answers for what was
            # typed before.
            previous = self._queries.get(key)
            if previous is not None:
                previous.cancel()
            self._queries[key] = child

    def _request_done(
        self,
        conn: Connection,
        request: str,
        key: tuple[str, str] | None,
        child: asyncio.Task[Any] | None,
    ) -> None:
        self._requests.pop(request, None)
        conn.forget(request)
        if key is not None and self._queries.get(key) is child:
            del self._queries[key]
        if child is None or child.cancelled():
            # Cancelled by the tab, a newer request, or the connection going
            # away: the reply, if it still has somewhere to go, says so.
            conn.say(Reply(request=request, error="cancelled"))

    def cancel(self, request: str) -> None:
        entry = self._requests.get(request)
        if entry is not None and entry[0] is not None:
            entry[0].cancel()

    def _drop_requests(self, conn: Connection) -> None:
        """Every request belongs to the connection it came in on: when that
        goes, so do they."""
        for child, theirs in list(self._requests.values()):
            if theirs is conn and child is not None:
                child.cancel()

    def upload_spec(self, node_id: str, field: str | None) -> tuple[list[str] | None, int]:
        """What an upload for this node may be: ``(accept, max_bytes)``. Raises ``Reject``."""
        from millwork.forms import field_spec, file_fields

        component = self.tree.components.get(node_id) if self.tree is not None else None
        accept: list[str] | None
        max_mb: int | None
        if isinstance(component, FileUpload) and not component.disabled:
            accept, max_mb = component.accept, component.max_size_mb
        elif isinstance(component, Chat) and component.attachments and not component.disabled:
            accept, max_mb = component.attachments.accept, component.attachments.max_size_mb
        elif isinstance(component, Form) and not (component.disabled or component.read_only):
            # The pointer of a file field in the draft; a list index is dropped to find
            # it in the spec, which knows list items without an index.
            pointer = re.sub(r"/\d+(?=/|$)", "", field or "")
            spec = file_fields(field_spec(component.model)).get(pointer)
            if spec is None:
                raise Reject("no file field at this pointer")
            accept, max_mb = spec.get("accept"), spec.get("max_size_mb")
        else:
            raise Reject("no upload component for this node")
        return accept, (max_mb * 1024 * 1024 if max_mb else self.app.files.default_max_bytes)


def _confirmation(component: Component, event: Event) -> tuple[str, bool] | None:
    """The question to ask before this event's handler runs, if the component wants one.

    ``Button.confirm`` and ``MenuItem.confirm`` carry the text, and a
    destructive button or item asks it in the dialog's destructive style.
    The style alone asks nothing: whether an action can be undone is the
    app's knowledge, not the framework's.
    """
    if isinstance(component, Button) and event.name == "click" and component.confirm:
        return component.confirm, component.variant == "destructive"
    payload = event.payload
    action = payload[0] if isinstance(payload, list | tuple) and payload else payload
    for item in _menu_items(component, event.name):
        if item.id != action:
            continue
        confirm = getattr(item, "confirm", None)
        if confirm:
            return confirm, bool(getattr(item, "destructive", False))
    return None


def _menu_items(component: Component, event: str) -> list[Any]:
    """The items the event picks from: a table's row actions, a file card's
    actions, a chat message's actions, or a dropdown menu's items."""
    if event == "action":
        return getattr(component, "row_actions", None) or getattr(component, "actions", None) or []
    if event == "select" and isinstance(component, DropdownMenu):
        return component.items
    return []


@dataclass
class _Ask:
    request: str
    component: Component
    future: asyncio.Future[Any]


class _ConfirmButtons(Component):
    """The footer of a confirm dialog: a row the session recognises by its button keys."""

    type: ClassVar[str] = "Row"
    gap: int = 2
    justify: str = "end"


def _noop(*args: Any, **kwargs: Any) -> None:
    return None


def _askable(component: Component) -> Component:
    """A copy whose Dialog opens and closes, and whose Forms submit, into the ask."""
    update: dict[str, Any] = {}
    if isinstance(component, Dialog):
        update["open"] = True
        if component.on_close is None:
            update["on_close"] = _noop
    if isinstance(component, Form) and component.on_submit is None:
        update["on_submit"] = _noop
    for name in ("footer", "action"):
        slot = getattr(component, name, None)
        if isinstance(slot, Component):
            update[name] = _askable(slot)
    children = [_askable(c) if isinstance(c, Component) else c for c in component.children]
    update["children"] = children
    return component.model_copy(update=update)


# A page function slower than this is doing more than building a tree.
SLOW_PAGE_MS = 20
# Requests in flight per session, of any kind, and files streaming out at once.
MAX_REQUESTS = 32
FILE_SLOTS = 4
