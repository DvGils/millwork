"""A session: one browser tab's state, tree, and connection.

The session owns the state object, renders the page from it, diffs against
the last tree it sent, and talks to the tab through whatever ``send``
callable the websocket attached. It outlives the socket for a grace
period so a reload or a dropped connection keeps its state.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import inspect
import logging
import re
import secrets
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from millwork import context
from millwork.auth import Forbidden, NotFound
from millwork.chat import ChatTurn, Thread, UIMessage
from millwork.files import FileRef, Reject, SessionFiles, content_to_file
from millwork.forms import FormIssues, resolve_files, validate
from millwork.nodes import Component, Tree, build, diff
from millwork.protocol import (
    Answer,
    Command,
    Event,
    Head,
    Mount,
    Patch,
    Reply,
    Request,
    ServerError,
    SessionInfo,
    Stream,
    pack,
    pack_frame,
)
from millwork.tasks import Cancelled, Task
from millwork.ui import Button, Dialog, Text, as_options
from millwork.ui.chat import Chat
from millwork.ui.files import Download, FileUpload
from millwork.ui.form import Form

if TYPE_CHECKING:
    from millwork.app import App, PageDef

log = logging.getLogger("millwork.session")

Send = Callable[[str], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]
Close = Callable[[], Awaitable[None]]

RENDER_COALESCE_SECONDS = 0.05
OUTBOX_KEEP = 500
# Messages from the tab still being handled; further ones are dropped until
# the backlog clears, so a flood cannot grow the task set without bound.
MAX_INFLIGHT = 64


class Session[S]:
    def __init__(self, app: App, page: PageDef, params: dict[str, str], path: str) -> None:
        self.id = secrets.token_urlsafe(16)
        self.resume_token = secrets.token_urlsafe(24)
        self.app = app
        self.page = page
        self.params = params
        self.path = path
        self.user: Any = None
        # Who opened it, for the per-client cap: the user's id, or the address.
        self.client: str | None = None
        self.created = time.monotonic()
        # When its tab last went away, for the caps: the session longest without
        # a tab makes room first. A session being connected or caught up still
        # has its tab, even though nothing can be sent to it yet.
        self.detached_at = self.created
        self.connecting = False
        self.end_reason: str | None = None
        self.state: S = page.make_state()
        self.tree: Tree | None = None
        self.closed = False
        self.files = SessionFiles(self)

        self._send: Send | None = None
        self._close_socket: Close | None = None
        self._seq = 0
        self._outbox: deque[tuple[int, str]] = deque(maxlen=OUTBOX_KEEP)
        self._render_scheduled = False
        self._render_handle: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()
        self._lock_holder: asyncio.Task[Any] | None = None
        self._grace: asyncio.TimerHandle | None = None
        self._loop = asyncio.get_running_loop()
        self.tasks: list[Task[Any]] = []
        self._asks: dict[str, _Ask] = {}
        self._toast_actions: dict[str, Callable[..., Any]] = {}
        # Requests in flight by id, and the byte streams uploads feed into.
        self._requests: dict[str, asyncio.Task[Any]] = {}
        self._inbound: dict[str, _Inbound] = {}
        # The handler request in flight per node and name: a newer one cancels it.
        self._queries: dict[tuple[str, str], asyncio.Task[Any]] = {}
        self._send_bytes: SendBytes | None = None
        # The socket being attached, before it has caught up: unnumbered messages
        # (a request's head or reply) may go to it straight away, since they take
        # no part in the replay order.
        self._catching_up: Send | None = None
        self._file_slots = asyncio.Semaphore(FILE_SLOTS)
        self._busy = False
        # Development warnings: each is said once per session; counters tell a
        # handler that changed nothing, and a thread that changed state, apart.
        self._warned: set[str] = set()
        self._effects = 0
        self._handler_runs = 0
        self._noop_watch: tuple[str, int] | None = None
        self._spawned: set[asyncio.Task[Any]] = set()
        self._threads: dict[str, Thread] = {}

    # ------------------------------------------------------------- connection

    @property
    def connected(self) -> bool:
        return self._send is not None

    @property
    def has_tab(self) -> bool:
        return self.connected or self.connecting or self._catching_up is not None

    @property
    def inflight(self) -> int:
        """Messages from the tab whose handling has not finished."""
        return sum(1 for t in self._spawned if not t.done())

    def owns_resume(self, token: str | None) -> bool:
        return token is not None and hmac.compare_digest(self.resume_token, token)

    async def attach(
        self,
        send: Send,
        last_seq: int,
        close: Close | None = None,
        send_bytes: SendBytes | None = None,
    ) -> None:
        """A tab connected (or reconnected). Replay what it missed, or mount.

        A second attachment replaces the first: the earlier socket is closed
        so a duplicated tab cannot keep dispatching into the session.
        """
        if self.closed:
            return
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None
        previous = self._close_socket
        # Nothing goes to either socket while the switch is made. The new one is
        # published only once it has caught up, so a message sent meanwhile lands
        # in the outbox and is replayed in order instead of racing the replay.
        self._send = None
        self._close_socket = None
        self._send_bytes = send_bytes
        self._catching_up = send
        self._abort_requests("the socket changed")
        if previous is not None:
            try:
                await previous()
            except Exception:
                log.debug("closing the previous socket of %s failed", self.id)
        try:
            info = SessionInfo(
                id=self.id, resume=self.resume_token, components=self.app.component_versions
            )
            await send(pack(self._seq, info))
            if self.tree is not None and self._can_replay(last_seq):
                caught_up = last_seq
                while True:
                    pending = [(seq, text) for seq, text in self._outbox if seq > caught_up]
                    if not pending:
                        break
                    for seq, text in pending:
                        await send(text)
                        caught_up = seq
                self._send, self._close_socket = send, close
                self._catching_up = None
                return
        except Exception:
            log.debug("the socket of %s failed before it caught up; detached", self.id)
            self._catching_up = None
            self.detach()
            return
        self._send, self._close_socket = send, close
        self._catching_up = None
        await self._mount()

    def _can_replay(self, last_seq: int) -> bool:
        if last_seq <= 0 or not self._outbox:
            return False
        first_seq = self._outbox[0][0]
        return first_seq <= last_seq + 1 <= self._seq + 1

    def detach(self, send: Send | None = None) -> None:
        """A socket went away. Only the current one detaches the session."""
        if send is not None and self._send is not send:
            return
        self._send = None
        self._close_socket = None
        self._send_bytes = None
        self._catching_up = None
        self.connecting = False
        self.detached_at = time.monotonic()
        self._abort_requests("the socket went away")
        if self.closed:
            return
        self._grace = self._loop.call_later(self.app.session_grace, self._grace_expired)

    def _grace_expired(self) -> None:
        self._grace = None
        if not self.connected and not self.closed:
            self._loop.create_task(self.close())

    async def end(self, message: str) -> None:
        """Close the session and tell its tab why, so the tab stops instead of
        reconnecting: signed out elsewhere, or made room for a newer session."""
        if not self.closed:
            self.end_reason = message
            with contextlib.suppress(Exception):
                await self._send_now(ServerError(message=message, fatal=True))
            close = self._close_socket
            if close is not None:
                with contextlib.suppress(Exception):
                    await close()
        await self.close()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._render_handle is not None:
            self._render_handle.cancel()
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None
        self.app.sessions.pop(self.id, None)
        self._abort_requests("the session closed")
        for task in list(self.tasks):
            task.cancel()
        for spawned in list(self._spawned):
            spawned.cancel()
        for ask in list(self._asks.values()):
            if not ask.future.done():
                ask.future.cancel()
        if self.page.on_close is not None:
            try:
                await _call(self.page.on_close, self)
            except Exception:
                log.exception("close hook failed for session %s", self.id)
        self.app.files.discard(self.id)

    # ------------------------------------------------------------- sending

    async def _send_now(self, msg: Any) -> None:
        """Number, remember for replay, and send if a tab is attached."""
        self._effects += 1
        self._seq += 1
        text = pack(self._seq, msg)
        self._outbox.append((self._seq, text))
        await self._deliver(text)

    async def _send_direct(self, msg: Any) -> None:
        """Send without entering the replay window (the session info on attach)."""
        await self._deliver(pack(self._seq, msg))

    async def _send_unnumbered(self, msg: Any) -> None:
        """A message outside the sequence: never replayed, never deduplicated, and
        sent even to a socket that is still catching up on the replay."""
        send = self._send or self._catching_up
        if send is None:
            return
        try:
            await send(pack(0, msg))
        except Exception:
            log.debug("unnumbered send failed for session %s", self.id)

    async def _deliver(self, text: str) -> None:
        if self._send is None:
            return
        try:
            await self._send(text)
        except Exception:
            # The socket is dead whatever the endpoint later learns: detach now
            # so the grace timer runs and the session cannot leak.
            log.debug("send failed for session %s; detached", self.id)
            self.detach(self._send)

    def command(self, name: str, **args: Any) -> None:
        """Fire-and-forget instruction to the tab: toast, navigate, clipboard."""
        self._loop.create_task(self._send_now(Command(name=name, args=args)))

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

    def navigate(self, path: str) -> None:
        """Go to another page on this session: its connect runs, the tab's history updates."""
        self._loop.create_task(self.navigate_to(path))

    def clipboard(self, text: str) -> None:
        self.command("clipboard", text=text)

    def logout(self) -> None:
        """Clear the sign-in cookie and send the tab to the login page."""
        self.command("logout")

    def reset(self, key: str) -> None:
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

    async def stream(self, node: str, chunk: dict[str, Any]) -> None:
        """One chunk of the AI SDK UI message stream to a Chat node. Never touches the tree."""
        await self._send_now(Stream(node=node, chunk=chunk))

    async def _chat_message(self, event: Event, component: Chat) -> None:
        """A user turn: record the message, run the handler as this thread's turn."""
        if component.key is None:
            log.warning("a Chat needs a key to keep its messages")
            return
        thread = self.chat(component.key)
        if thread.busy:
            self.toast("Wait for the current reply to finish.", tone="warning")
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        text = str(payload.get("text") or "").strip()
        if len(text) > component.max_chars:
            self.toast("The message is too long.", tone="warning")
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
        command = payload.get("command")
        if not text and not files:
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
        message = UIMessage(id=secrets.token_urlsafe(8), role="user", parts=parts)
        thread.messages.append(message)
        turn = ChatTurn(
            self, event.node, thread, message, files, command if isinstance(command, str) else None
        )
        handler = self.tree.handler(event.node, "message") if self.tree else None
        if handler is None:
            self.refresh()
            return

        async def run() -> None:
            # The lock is not held while a reply streams: tool steps, tasks and
            # inline components render meanwhile; the composer is disabled by `busy`.
            token = context.bind(self)
            try:
                await _call(handler, self, turn)
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("chat handler failed")
                self.toast("The reply failed.", tone="destructive")
            finally:
                context.unbind(token)
                thread.turn_task = None
                if thread.inflight is not None:
                    thread.messages.append(thread.inflight)
                    thread.inflight = None
                self.refresh()

        self.refresh()
        thread.turn_task = self.spawn(run(), "chat turn")

    async def _chat_stop(self, event: Event, component: Chat) -> None:
        thread = self.chat(component.key) if component.key else None
        if thread is not None and thread.turn_task is not None:
            thread.turn_task.cancel()
        handler = self.tree.handler(event.node, "stop") if self.tree else None
        if handler is not None:
            await self._run_handler(handler, self, None)

    def spawn(self, coro: Any, what: str = "work") -> asyncio.Task[Any]:
        """Run a coroutine for this session: tracked, cancelled on close, failures logged."""
        task = self._loop.create_task(coro)
        self._spawned.add(task)

        def done(t: asyncio.Task[Any]) -> None:
            self._spawned.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.error("%s failed for session %s", what, self.id, exc_info=exc)

        task.add_done_callback(done)
        return task

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
        self._effects += 1
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
        self.tasks.append(task)
        if delay:
            task._delay_handle = self._loop.call_later(
                delay, lambda: task._start(work, args, kwargs, timeout)
            )
            self.refresh()
        else:
            task._start(work, args, kwargs, timeout)
        return task

    def later(self, delay: float, work: Any, *args: Any, **kwargs: Any) -> Task[Any]:
        return self.task(work, *args, delay=delay, **kwargs)

    def thread(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Task[Any]:
        return self.task(fn, *args, **kwargs)

    def _task_finished(self, task: Task[Any]) -> None:
        """A task reached a terminal status: run ``on_done`` as a handler, then render."""
        on_done = getattr(task, "_on_done", None)
        if on_done is not None:
            self._loop.create_task(self._run_handler(on_done, self, task))
        if len(self.tasks) > 50:
            self.tasks = [t for t in self.tasks if not t.done][-50:] + [
                t for t in self.tasks if t.done
            ][-10:]
        self.refresh()

    async def _run_handler(self, fn: Callable[..., Any], *args: Any) -> None:
        async with self._hold():
            token = context.bind(self)
            self._handler_runs += 1
            try:
                await _call(fn, *args)
            except Exception:
                log.exception("handler %s failed", getattr(fn, "__name__", fn))
                self.toast("Something went wrong.", tone="destructive")
            finally:
                context.unbind(token)
        self.refresh()

    @contextlib.asynccontextmanager
    async def _hold(self) -> AsyncIterator[None]:
        """The one-handler-at-a-time lock, remembering who holds it so ``ask`` can let go."""
        await self._lock.acquire()
        self._lock_holder = asyncio.current_task()
        try:
            yield
        finally:
            self._lock_holder = None
            self._lock.release()

    # ------------------------------------------------------------- ask

    async def ask(  # noqa: ASYNC109
        self, component: Component, timeout: float | None = None
    ) -> Any:
        """Render a component, wait for its submit or close, return the answer or None.

        The handler lock is released while waiting, so other handlers run.
        A ``Form`` inside answers with its validated model; a ``Dialog``'s
        close, a cancel, or a timeout answers ``None``. The session closing
        cancels the handler itself, as it does any other work.
        """
        request = secrets.token_urlsafe(8)
        component = _askable(component)
        ask = _Ask(request=request, component=component, future=self._loop.create_future())
        self._asks[request] = ask
        self.refresh()
        try:
            async with self._unlocked():
                if timeout:
                    return await asyncio.wait_for(ask.future, timeout)
                return await ask.future
        except TimeoutError:
            return None
        finally:
            self._asks.pop(request, None)
            self.refresh()

    @contextlib.asynccontextmanager
    async def _unlocked(self) -> AsyncIterator[None]:
        """Let go of the handler lock while waiting on the user or a task, then take it back."""
        held = self._lock_holder is asyncio.current_task() and self._lock.locked()
        if held:
            self._lock_holder = None
            self._lock.release()
        try:
            yield
        finally:
            if held:
                await self._lock.acquire()
                self._lock_holder = asyncio.current_task()

    async def wait_for_task(self, task: Task[Any]) -> Any:
        """``await task`` from a handler: renders keep flowing while it runs.

        A cancelled task raises ``millwork.Cancelled`` (an ordinary exception the
        handler can catch), never asyncio's cancellation of the handler itself.
        """
        async with self._unlocked():
            try:
                return await asyncio.shield(task.future)
            except asyncio.CancelledError:
                if task.status == "cancelled":
                    raise Cancelled(task.label) from None
                raise

    async def confirm(
        self,
        title: str,
        description: str | None = None,
        ok: str = "OK",
        cancel: str = "Cancel",
        destructive: bool = False,
    ) -> bool:
        buttons = _ConfirmButtons(
            children=[
                Button(cancel, key="cancel", variant="outline", on_click=_noop),
                Button(
                    ok,
                    key="ok",
                    variant="destructive" if destructive else "primary",
                    on_click=_noop,
                ),
            ]
        )
        dialog = Dialog(
            children=[Text(description)] if description else [],
            title=title,
            size="sm",
            footer=buttons,
        )
        answer = await self.ask(dialog)
        return answer is True

    def _ask_root(self, request: str) -> str:
        return f"{self.tree.root if self.tree else 'root'}/@ask:{request}"

    async def _answer_ask(self, event: Event, component: Component | None) -> bool:
        """An event inside an open ask: resolve it, or let it through to its own handler."""
        for request, ask in self._asks.items():
            prefix = self._ask_root(request)
            if event.node != prefix and not event.node.startswith(prefix + "/"):
                continue
            if ask.future.done():
                return True
            if event.name == "submit" and isinstance(component, Form):
                draft = resolve_files(event.payload, self._form_file(event.node))
                instance, issues = validate(component.model, draft)
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

    # ------------------------------------------------------------- navigation

    async def navigate_to(self, path: str) -> None:
        """Switch this session to another page. State is per page; files and identity stay."""
        # A fragment names a heading: the tab scrolls to it after the mount.
        path, _, fragment = path.partition("#")
        resolved = self.app.resolve(path)
        if resolved is None:
            await self._send_now(ServerError(message=f"No page at {path}.", fatal=False))
            return
        page, params = resolved
        if self.app.auth is not None and not page.public and self.user is None:
            await self._send_now(ServerError(message="Sign in to continue.", fatal=True))
            return
        # Under the handler lock: no render runs against the new page before its
        # connect has finished, and no handler runs across the switch. The switch
        # is provisional until connect succeeds: a page that fails to start leaves
        # the tab on the page it had, still working.
        async with self._hold():
            previous = (self.page, self.params, self.path, self.state, self.tree)
            self.page, self.params, self.path = page, params, path
            self.state = page.make_state()
            self.tree = None
            try:
                await self.connect()
            except (Forbidden, NotFound) as exc:
                self.page, self.params, self.path, self.state, self.tree = previous
                await self._send_now(ServerError(message=exc.message, fatal=False))
                return
            except Exception:
                log.exception("connect failed for %s", path)
                self.page, self.params, self.path, self.state, self.tree = previous
                await self._send_now(ServerError(message="The page failed to start.", fatal=False))
                return
            for ask in list(self._asks.values()):
                if not ask.future.done():
                    ask.future.set_result(None)
            self._asks.clear()
            args: dict[str, Any] = {"path": path, "title": page.title}
            if fragment:
                args["hash"] = fragment
            await self._send_now(Command(name="navigate", args=args))
            await self._mount()

    # ------------------------------------------------------------- rendering

    def refresh(self) -> None:
        """Render soon. Coalesced: many calls in one tick are one patch."""
        if self._render_scheduled or self.closed:
            return
        self._render_scheduled = True
        self._render_handle = self._loop.call_later(RENDER_COALESCE_SECONDS, self._flush)

    def _flush(self) -> None:
        self._render_scheduled = False
        self._render_handle = None
        self._loop.create_task(self._render())

    async def _mount(self) -> None:
        if self.closed:
            return
        tree = self._build()
        if tree is None:
            return
        self.tree = tree
        await self._send_now(Mount(root=tree.root, nodes=tree.nodes, title=self.page.title))

    async def _render(self) -> None:
        """Render under the handler lock, so a page never sees half-mutated state."""
        if self.closed:
            return
        async with self._hold():
            if self.closed:
                return
            if self.tree is None:
                await self._mount()
                return
            tree = self._build()
            if tree is None:
                return
            ops = diff(self.tree, tree)
            self._check_keyless(self.tree, tree)
            self.tree = tree
            if ops:
                await self._send_now(Patch(ops=ops))
            self._signal_activity()
            watch, self._noop_watch = self._noop_watch, None
            if watch is not None and not ops and self._effects == watch[1]:
                self.warn(
                    f"noop:{watch[0]}",
                    f"{watch[0]} changed nothing: no state, no command, no task. "
                    "A forgotten await, or a handler that should not be one?",
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

    def _build(self) -> Tree | None:
        # Bound for the render and the build: wire values (a FileRef, a task)
        # read the current session while the tree is walked.
        token = context.bind(self)
        try:
            started = time.perf_counter()
            root = self.page.render(self)
            took = (time.perf_counter() - started) * 1000
            if took > SLOW_PAGE_MS:
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
        except Exception:
            log.exception("page %s failed to render", self.page.path)
            self._loop.create_task(
                self._send_now(ServerError(message="The page failed to render.", fatal=False))
            )
            return None
        finally:
            context.unbind(token)

    # ------------------------------------------------------------- events

    async def _toast_action(self, token: str) -> None:
        """The button on a toast was pressed: run its handler once, as a handler."""
        handler = self._toast_actions.pop(token, None)
        if handler is None:
            log.debug("toast action %s unknown or already used", token)
            return
        async with self._hold():
            ctx = context.bind(self)
            try:
                await _call(handler, self, None)
            except Exception:
                log.exception("toast action failed")
                self.toast("Something went wrong.", tone="destructive")
            finally:
                context.unbind(ctx)
        self.refresh()

    async def dispatch(self, event: Event) -> None:
        """Run the handler bound to this event, then render.

        Everything the tab sends is untrusted: the node must exist in the
        current tree, a disabled component takes no events, an upload refers
        only to files uploaded for that node, a form submit is validated
        before its handler sees it.
        """
        if self.tree is None or self.closed:
            return
        if event.node.startswith("toast:") and event.name == "action":
            await self._toast_action(event.node[6:])
            return
        component = self.tree.components.get(event.node)
        if component is None:
            log.debug("event %s for unknown node %s", event.name, event.node)
            return
        if self._asks and await self._answer_ask(event, component):
            return
        if getattr(component, "disabled", False):
            log.debug("event %s on disabled node %s dropped", event.name, event.node)
            return
        if (
            isinstance(component, Form)
            and component.read_only
            and event.name in ("submit", "cancel")
        ):
            return
        payload = event.payload

        if isinstance(component, Chat) and event.name in ("message", "stop"):
            if event.name == "message":
                await self._chat_message(event, component)
            else:
                await self._chat_stop(event, component)
            return

        if event.name == "download" and isinstance(component, Download):
            token = context.bind(self)
            try:
                self.download(component.filename, component.content, component.mime)
            except Exception:
                log.exception("download %s failed", component.filename)
                self.toast("The download failed.", tone="destructive")
            finally:
                context.unbind(token)
            return

        handler = self.tree.handler(event.node, event.name)
        if handler is None:
            log.warning("no handler for %s on %s", event.name, event.node)
            return

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
                return

        if event.name == "submit" and isinstance(component, Form):
            draft = resolve_files(payload, self._form_file(event.node))
            instance, issues = validate(component.model, draft)
            if issues:
                self.command(
                    "form_issues", node=event.node, issues=[i.model_dump() for i in issues]
                )
                return
            payload = instance

        question = _confirmation(component, event)
        rejected = False
        async with self._hold():
            token = context.bind(self)
            try:
                if question is not None:
                    title, destructive = question
                    if not await self.confirm(title, destructive=destructive):
                        return
                self._handler_runs += 1
                before = self._effects
                await _call(handler, self, payload)
                self._noop_watch = (f"the {event.name} handler on {event.node}", before)
            except FormIssues as exc:
                rejected = True
                self.command(
                    "form_issues", node=event.node, issues=[i.model_dump() for i in exc.issues]
                )
            except Exception:
                log.exception("handler %s on %s failed", event.name, event.node)
                self.toast("Something went wrong.", tone="destructive")
            finally:
                context.unbind(token)
        if event.name == "submit" and isinstance(component, Form) and not rejected:
            # The empty issue list is the form's acknowledgement: the draft was accepted.
            self.command("form_issues", node=event.node, issues=[])
        self.refresh()

    def _form_file(self, node: str) -> Callable[[str], FileRef | None]:
        """A lookup for the files a form's draft refers to: uploaded for that form, or none."""

        def lookup(file_id: str) -> FileRef | None:
            ref = self.files.get(file_id)
            return ref if ref is not None and ref.node == node else None

        return lookup

    # --------------------------------------------------------- requests

    def start_request(self, msg: Request) -> None:
        """Begin answering a ``request``: registered here, synchronously, so that a
        ``cancel`` or binary frames right behind it on the socket find it."""
        if self.closed:
            return
        if msg.request in self._requests:
            self._send_later(Reply(request=msg.request, error="duplicate request"))
            return
        if len(self._requests) >= MAX_REQUESTS:
            self._send_later(Reply(request=msg.request, error="too many requests"))
            return
        if msg.name == "upload":
            self._inbound[msg.request] = _Inbound(msg.size or 0)
        task = self.spawn(self._request(msg), f"request {msg.name} on {msg.node}")
        self._requests[msg.request] = task

    def _send_later(self, msg: Any) -> None:
        self._loop.create_task(self._send_unnumbered(msg))

    async def feed(self, request: str, data: bytes) -> None:
        """A binary frame for an upload in flight. Unknown or finished: dropped."""
        stream = self._inbound.get(request)
        if stream is None:
            log.debug("frame for unknown request %s dropped", request)
            return
        await stream.put(data)

    def cancel_request(self, request: str) -> None:
        task = self._requests.get(request)
        if task is not None:
            task.cancel()

    def _abort_requests(self, why: str) -> None:
        """Every request belongs to one socket connection: when it goes, so do they.
        Their "cancelled" replies may still reach a socket attached later; the tab
        ignores replies to requests it never made."""
        for stream in self._inbound.values():
            stream.fail(why)
        for task in list(self._requests.values()):
            task.cancel()

    async def _request(self, msg: Request) -> None:
        """Answer a ``request`` with a ``reply``, over the socket, without a render.

        ``file`` streams one of the session's files to the tab; ``upload`` stores the
        bytes that follow the message; any other name is a handler on the node,
        run outside the handler lock (a search never waits on a click), whose
        return value is the payload. A newer handler request on the same node and
        name cancels the one in flight.
        """
        try:
            if msg.name == "file":
                await self._serve_file(msg)
            elif msg.name == "upload":
                await self._receive_upload(msg)
            else:
                await self._ask_handler(msg)
        except asyncio.CancelledError:
            # Cancelled by the tab, a newer request, or the socket going away: the
            # reply, if it still has somewhere to go, says so. The cancellation
            # itself goes on to whoever awaits this task.
            await self._reply(msg.request, error="cancelled")
            raise
        finally:
            self._requests.pop(msg.request, None)
            stream = self._inbound.pop(msg.request, None)
            if stream is not None:
                stream.fail("done")

    async def _reply(self, request: str, payload: Any = None, error: str | None = None) -> None:
        await self._send_unnumbered(Reply(request=request, payload=payload, error=error))

    async def _ask_handler(self, msg: Request) -> None:
        tree = self.tree
        component = tree.components.get(msg.node) if tree is not None else None
        handler = tree.handler(msg.node, msg.name) if tree is not None and component else None
        if handler is None or getattr(component, "disabled", False) or msg.size is not None:
            await self._reply(msg.request, error="unknown request")
            return
        key = (msg.node, msg.name)
        previous = self._queries.pop(key, None)
        if previous is not None:
            previous.cancel()
        self._queries[key] = self._requests[msg.request]
        token = context.bind(self)
        try:
            result = await _call(handler, self, msg.payload)
            if isinstance(result, list):
                result = [
                    o.model_dump(exclude_none=True, exclude_defaults=True)
                    for o in as_options(result)
                ]
            await self._reply(msg.request, payload=result)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("request %s on %s failed", msg.name, msg.node)
            await self._reply(msg.request, error="The request failed.")
        finally:
            context.unbind(token)
            if self._queries.get(key) is self._requests.get(msg.request):
                self._queries.pop(key, None)

    async def _serve_file(self, msg: Request) -> None:
        """One of the session's files, as a ``head`` and binary frames, then the reply.

        A few at a time per session, so a tab cannot hold an open file per request.
        """
        file_id = msg.payload.get("id") if isinstance(msg.payload, dict) else None
        ref = self.files.get(file_id) if isinstance(file_id, str) else None
        if ref is None or not ref.path.is_file():
            await self._reply(msg.request, error="no such file")
            return
        async with self._file_slots:
            head = {"name": ref.name, "mime": ref.mime, "size": ref.size}
            await self._send_unnumbered(Head(request=msg.request, payload=head))
            sent = 0
            with ref.path.open("rb") as fh:
                while True:
                    chunk = await asyncio.to_thread(fh.read, STREAM_CHUNK)
                    if not chunk:
                        break
                    send_bytes = self._send_bytes
                    if send_bytes is None:
                        return
                    frame = pack_frame(msg.request, chunk)
                    try:
                        await send_bytes(frame)
                    except Exception:
                        log.debug("file stream to %s failed; detached", self.id)
                        self.detach(self._send)
                        return
                    sent += len(chunk)
        await self._reply(msg.request, payload={"size": sent})

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

    async def _receive_upload(self, msg: Request) -> None:
        """Store the bytes that follow an ``upload`` request as a session file.

        Frames are taken off the stream on the loop and each write goes to a
        thread, so an upload that stalls holds a queue, never a thread.
        """
        stream = self._inbound.get(msg.request)
        payload = msg.payload if isinstance(msg.payload, dict) else {}
        writer = None
        try:
            if stream is None or msg.size is None:
                raise Reject("an upload needs a size")
            field = payload.get("field")
            accept, max_bytes = self.upload_spec(
                msg.node, field if isinstance(field, str) else None
            )
            if msg.size > max_bytes:
                raise Reject(f"the file is larger than {max_bytes // (1024 * 1024)} MB")
            name = payload.get("name")
            mime = payload.get("mime")
            writer = self.app.files.begin(
                self,
                name if isinstance(name, str) and name else "file",
                mime=mime if isinstance(mime, str) else None,
                max_bytes=max_bytes,
                accept=accept,
                node=msg.node,
            )
            while True:
                chunk = await stream.get()
                if chunk is None:
                    break
                await asyncio.to_thread(writer.write, chunk)
            ref = await asyncio.to_thread(writer.finish)
        except Reject as exc:
            if writer is not None:
                writer.abort()
            await self._reply(msg.request, error=exc.reason)
            return
        except asyncio.CancelledError:
            if writer is not None:
                writer.abort()
            raise
        except Exception:
            log.exception("upload on %s failed", msg.node)
            if writer is not None:
                writer.abort()
            await self._reply(msg.request, error="The upload failed.")
            return
        await self._reply(msg.request, payload=ref.__millwork_wire__())

    async def answer(self, msg: Answer) -> None:
        """The tab answered an ``ask``. Asks arrive with tasks; until then, log."""
        log.warning("answer for unknown request %s", msg.request)

    async def connect(self) -> None:
        """Run the page's connect hook, in the session context."""
        if self.page.on_connect is None:
            return
        token = context.bind(self)
        try:
            await _call(self.page.on_connect, self, **self.params)
        finally:
            context.unbind(token)


def _confirmation(component: Component, event: Event) -> tuple[str, bool] | None:
    """The question to ask before this event's handler runs, if the component wants one.

    ``Button.confirm`` carries its own text; a destructive menu item asks
    with its label, so an irreversible row action is never one slip away.
    """
    if isinstance(component, Button) and event.name == "click" and component.confirm:
        return component.confirm, component.variant == "destructive"
    if event.name == "action":
        payload = event.payload
        action = payload[0] if isinstance(payload, list | tuple) and payload else payload
        items = getattr(component, "row_actions", None) or getattr(component, "actions", None)
        for item in items or []:
            if item.id == action and item.destructive:
                return f"{item.label}?", True
    return None


async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


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


async def _noop(*args: Any, **kwargs: Any) -> None:
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


STREAM_CHUNK = 256 * 1024
# A page function slower than this is doing more than building a tree.
SLOW_PAGE_MS = 20
# Requests in flight per session, of any kind, and files streaming out at once.
MAX_REQUESTS = 32
FILE_SLOTS = 4


class _Inbound:
    """The byte stream of one upload: frames go in from the socket's receive loop,
    the upload task takes them out. Bounded, so a slow disk holds the receive
    loop back instead of buffering a whole file in memory. Failing it wakes
    both sides: a blocked putter, and a getter, which sees the failure."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.received = 0
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=16)
        self.failed: str | None = None
        if size == 0:
            self._queue.put_nowait(None)

    async def put(self, data: bytes) -> None:
        if self.failed is not None:
            return
        self.received += len(data)
        if self.received > self.size:
            self.fail("more bytes than announced")
            return
        await self._queue.put(data)
        if self.failed is not None:
            return
        if self.received == self.size:
            await self._queue.put(None)

    async def get(self) -> bytes | None:
        """The next chunk, or None at the end. Raises ``Reject`` once failed."""
        if self.failed is not None:
            raise Reject(f"the upload was interrupted: {self.failed}")
        item = await self._queue.get()
        if self.failed is not None:
            raise Reject(f"the upload was interrupted: {self.failed}")
        return item

    def fail(self, why: str) -> None:
        if self.failed is not None:
            return
        self.failed = why
        # Drop what is queued: it wakes a putter blocked on a full queue, and makes
        # room for the end marker that wakes a waiting getter.
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)
