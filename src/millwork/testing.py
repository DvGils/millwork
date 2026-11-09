"""Drive an app from a test: the real session, dispatcher, tasks and render, no socket.

``TestApp(app).open(path)`` yields a ``Page`` whose
actions are events through ``Session.dispatch``; what the server would have
sent to a tab is collected in ``messages``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import mimetypes
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin

from millwork.auth import Forbidden
from millwork.connection import Connection
from millwork.files import FileRef, _read_chunks
from millwork.nodes import Component
from millwork.protocol import Command, Event, Patch, ServerError, Stream, server_message
from millwork.scope import Scope
from millwork.session import Session
from millwork.ui import Button, Link
from millwork.ui.chat import Chat
from millwork.ui.files import Download, FileUpload
from millwork.ui.form import Form

if TYPE_CHECKING:
    from millwork.app import App
    from millwork.protocol import Node

# How long to let a handler run between looks at whether it is waiting on the user.
_TICK = 0.01


class Found:
    """A node of the current tree, with the component that produced it."""

    def __init__(self, node: Node, component: Component | None) -> None:
        self.id = node.id
        self.type = node.type
        self.props = node.props
        self.children = node.children
        self.component = component

    @property
    def rows(self) -> list[dict[str, Any]]:
        """A Table's rows as the tab receives them."""
        rows = self.props.get("rows")
        return list(rows) if isinstance(rows, list) else []

    def __repr__(self) -> str:
        return f"<{self.type} {self.id}>"


class Page:
    """One open session, driven from the test and observed on its wire."""

    def __init__(self, session: Session[Any], strict: bool = True) -> None:
        self.session = session
        self.messages: list[Any] = []
        self.failures: list[tuple[str, BaseException]] = []
        """What the app's code raised, in order: ``(where, exception)``."""
        self._strict = strict
        self._tab: asyncio.Task[Any] | None = None
        self._conn: Connection | None = None
        session.on_failure = self._failed

    def _said_goodbye(self) -> bool:
        return self._tab is None or self._tab.done()

    def _heard_everything(self) -> bool:
        conn = self._conn
        if conn is None or conn.closed:
            return True
        return conn.cursor == self.session.outbox.seq and not conn._lane

    def _failed(self, where: str, exc: BaseException) -> None:
        self.failures.append((where, exc))

    def _raise_failures(self) -> None:
        """In a strict harness, what the app raised is raised in the test, where the
        traceback points at the cause instead of at a failure page or a toast."""
        if not self._strict or not self.failures:
            return
        where, exc = self.failures[0]
        exc.add_note(f"raised by {where}")
        raise exc

    # ------------------------------------------------------------- reading

    @property
    def tree(self) -> dict[str, Node]:
        return self.session.tree.nodes if self.session.tree is not None else {}

    @property
    def state(self) -> Any:
        return self.session.state

    def find_all(
        self,
        what: type[Component] | str,
        *,
        within: Found | str | None = None,
        **props: Any,
    ) -> list[Found]:
        """Every node of a component type, or with a key (or a full id).

        A type finds its subclasses too, so ``ui.Custom`` finds every custom
        component, and ``found.type`` says which one each is. ``within``
        narrows the search to what is inside one node, for a key that several
        cards or rows each have. Any other keyword is a prop the node has to
        have with that value: ``find_all(ui.Button, label="Delete")``."""
        tree = self.session.tree
        if tree is None:
            return []
        inside = None
        if within is not None:
            scope = within if isinstance(within, Found) else self.find(within)
            inside = scope.id + "/"
        out = []
        for node_id, node in tree.nodes.items():
            if inside is not None and not node_id.startswith(inside):
                continue
            component = tree.components.get(node_id)
            if isinstance(what, str):
                hit = (
                    node_id == what
                    or node_id.rsplit("/", 1)[-1] == what
                    or (component is not None and component.key == what)
                )
            else:
                hit = isinstance(component, what) or node.type == what.type
            if hit and all(_has(node, component, k, v) for k, v in props.items()):
                out.append(Found(node, component))
        return out

    def find(
        self,
        what: type[Component] | str,
        *,
        within: Found | str | None = None,
        **props: Any,
    ) -> Found:
        """The first node of a component type, or with a key; raises when
        there is none. ``within`` looks inside one node only, and any other
        keyword is a prop it has to have: ``find(ui.Button, label="Delete")``."""
        found = self.find_all(what, within=within, **props)
        if not found:
            name = what if isinstance(what, str) else what.__name__
            having = "".join(f" with {k}={v!r}" for k, v in props.items())
            where = "on the page" if within is None else f"in {within!r}"
            raise LookupError(f"no {name}{having} {where}")
        return found[0]

    def text(self) -> str:
        """Every string prop of the tree, for a quick "is it there" check. A
        prop that picks from a fixed set, a variant or an alignment, is not
        text and is left out."""
        parts: list[str] = []
        built = self.session.tree
        components = built.components if built is not None else {}
        for node in self.tree.values():
            component = components.get(node.id)
            fields = type(component).model_fields if component is not None else {}
            for name, value in node.props.items():
                if isinstance(value, str) and not _is_choice(fields.get(name)):
                    parts.append(value)
        return "\n".join(parts)

    @property
    def patches(self) -> list[Patch]:
        return [m for m in self.messages if isinstance(m, Patch)]

    @property
    def last_patch(self) -> Patch | None:
        patches = self.patches
        return patches[-1] if patches else None

    @property
    def commands(self) -> list[Command]:
        return [m for m in self.messages if isinstance(m, Command)]

    @property
    def toasts(self) -> list[str]:
        return [n.message for n in self.notices]

    @property
    def notices(self) -> list[Notice]:
        """Every toast shown, with its tone and title."""
        return [
            Notice(
                str(c.args.get("message", "")),
                str(c.args.get("tone") or "default"),
                c.args.get("title") if isinstance(c.args.get("title"), str) else None,
            )
            for c in self.commands
            if c.name == "toast"
        ]

    @property
    def stream(self) -> list[dict[str, Any]]:
        """Every chunk the chats on the page streamed, in order, in the AI SDK's
        UI message stream format. A reply runs from ``{"type": "start"}`` to
        ``{"type": "finish"}``, and its words are the ``delta`` of each
        ``{"type": "text-delta"}`` chunk.

        The finished reply is easier to read off the thread, as
        ``page.session.chat(key).messages[-1].text``."""
        return [m.chunk for m in self.messages if isinstance(m, Stream)]

    @property
    def errors(self) -> list[str]:
        return [m.message for m in self.messages if isinstance(m, ServerError)]

    # ------------------------------------------------------------- acting

    async def event(self, node: Found | str, name: str, payload: Any = None) -> None:
        """One event through the real dispatcher, then everything it set off."""
        node_id = node.id if isinstance(node, Found) else self.find(node).id
        self.session.event(Event(node=node_id, name=name, payload=payload))
        await self.settle()

    async def click(self, node: Found | str) -> None:
        """Click it. A ``Download``'s button starts the download, so that is
        what clicking one does here, and a ``Link`` or a button with an
        ``href`` to a page of the app takes the session there. One that
        leaves the app does nothing here, as the session sees nothing of it."""
        found = node if isinstance(node, Found) else self.find(node)
        href = getattr(found.component, "href", None)
        if isinstance(found.component, Button | Link) and href is not None:
            inside = href.startswith("/") and not href.startswith(("/_mw/", "/public/"))
            if inside and found.component.target == "_self":
                await self.navigate(href)
            return
        name = "download" if isinstance(found.component, Download) else "click"
        await self.event(found, name)

    async def toast_action(self, label: str) -> None:
        """Press the button of the latest toast that has one with this label."""
        for command in reversed(self.commands):
            action = command.args.get("action") if command.name == "toast" else None
            if isinstance(action, dict) and action.get("label") == label:
                token = action["id"]
                break
        else:
            raise LookupError(f"no toast with a {label!r} button")
        if token not in self.session._toast_actions:
            raise LookupError(f"the {label!r} button was already pressed, or its toast is gone")
        self.session.event(Event(node=f"toast:{token}", name="action"))
        await self.settle()

    async def change(self, node: Found | str, value: Any) -> None:
        """An input's new value, as the tab would send it."""
        await self.event(node, "change", value)

    async def submit(self, form: Found | str, draft: Any) -> None:
        """Submit a draft (a dict or a model instance) as the tab would."""
        if hasattr(draft, "model_dump"):
            draft = draft.model_dump(mode="json")
        await self.event(form, "submit", draft)

    async def select(self, table: Found | str, keys: list[Any]) -> None:
        """Select rows of a table by key."""
        await self.event(table, "select", keys)

    async def choose(self, menu: Found | str, item: str) -> None:
        """Choose an item of a ``DropdownMenu``, by its id or its label. An
        item with ``confirm`` then waits for ``answer``, like a button."""
        found = menu if isinstance(menu, Found) else self.find(menu)
        items = getattr(found.component, "items", None) or []
        match = next((i for i in items if i.id == item), None) or next(
            (i for i in items if i.label == item), None
        )
        if match is None:
            raise LookupError(f"{found!r} has no item {item!r}")
        if match.disabled:
            raise LookupError(f"the item {item!r} of {found!r} is disabled")
        await self.event(found, "select", match.id)

    async def action(self, node: Found | str, action: str, key: Any = None) -> None:
        """A row action on a Table (``[action, key]``) or a card action (``action``)."""
        await self.event(node, "action", [action, key] if key is not None else action)

    def _store(self, node_id: str, path: Path | str, accept: list[str] | None) -> FileRef:
        p = Path(path)
        mime = mimetypes.guess_type(p.name)[0]
        files = self.session.app.files
        return files.store(
            self.session,
            p.name,
            _read_chunks(p),
            mime=mime,
            max_bytes=files.max_session_bytes,
            accept=accept,
            node=node_id,
        )

    async def upload(
        self, node: Found | str, path: Path | str, *, field: str | None = None
    ) -> FileRef:
        """Put a file into the session for a node, as the upload route would.

        For a ``FileUpload`` the ``upload`` event follows. For a ``Form`` the
        file is stored for the form and returned, to go into a draft at
        ``field``'s pointer; the submit then resolves it.
        """
        found = node if isinstance(node, Found) else self.find(node)
        component = found.component
        accept: list[str] | None = None
        if isinstance(component, FileUpload):
            accept = component.accept
        elif isinstance(component, Form):
            if field is None:
                raise ValueError("uploading to a Form takes field=, the file field's pointer")
        elif not isinstance(component, Chat):
            raise TypeError(f"{found.type} takes no uploads")
        ref = self._store(found.id, path, accept)
        if isinstance(component, FileUpload):
            await self.event(found, "upload", [ref.model_dump(mode="json")])
        return ref

    async def send(
        self,
        chat: Found | str,
        text: str = "",
        *,
        files: Iterable[Path | str] = (),
        command: str | None = None,
    ) -> None:
        """A chat turn: the message event with text, attachments and a command."""
        found = chat if isinstance(chat, Found) else self.find(chat)
        refs = [self._store(found.id, p, None) for p in files]
        payload = {
            "text": text,
            "files": [r.model_dump(mode="json") for r in refs],
            "command": command,
        }
        await self.event(found, "message", payload)

    async def stop(self, chat: Found | str) -> None:
        """Press stop on a chat's running reply."""
        await self.event(chat, "stop")

    async def answer(self, payload: Any = None) -> None:
        """Answer the open ``ask``: ``True``/``False`` press OK or Cancel, a dict
        or model submits the form inside, ``None`` closes the dialog."""
        asks = [a for a in self.session._asks.values() if not a.future.done()]
        if not asks:
            raise LookupError("nothing is being asked")
        ask = asks[-1]
        prefix = self.session._ask_root(ask.request)
        inside = [n for n in self.tree.values() if n.id == prefix or n.id.startswith(prefix + "/")]
        if payload is True or payload is False:
            label = "ok" if payload else "cancel"
            button = next((n for n in inside if n.id.rsplit("/", 1)[-1] == label), None)
            if button is None:
                raise LookupError(f"the ask has no {label} button")
            await self.event(button.id, "click")
            return
        if payload is None:
            await self.event(prefix, "close")
            return
        form = next((n for n in inside if n.type == "Form"), None)
        if form is None:
            raise LookupError("the ask has no form to answer")
        await self.submit(form.id, payload)

    async def navigate(self, path: str) -> None:
        """Take the session to another page, and wait for it to connect and render."""
        await self.session.navigate_to(path)
        await self.settle()

    async def settle(self, timeout: float = 10.0) -> None:
        """Wait until the session has nothing left to do, or is waiting on the user.

        Running tasks and spawned work are awaited; a handler blocked on an
        open ``ask`` is left there for ``answer``. A quiet task is not waited
        for: it waits for something outside the session, a change made
        elsewhere, and would never let a test go on. The coalesced render
        runs at once rather than after its timer. After ``timeout`` seconds
        the wait gives up and names what is still running.
        """
        s = self.session
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            asking = any(not a.future.done() for a in s._asks.values())
            # Delayed tasks (``s.later``) are not waited for; a running task or
            # handler that is blocked on an open ask is left for ``answer``.
            running = [t for t in s.tasks if t.status == "running" and not t.quiet]
            # What else the session has under way: handlers in or waiting for
            # their turn, requests, a reply, a page being connected.
            # A child counts until the scope has seen it out, which is a
            # moment after it finished: only then is its turn given back.
            bodies = {t._child for t in s.tasks}
            working = [c for c in s.scope.children if c not in bodies]
            # A page being left or opened, which the session's life does.
            switching = not s.over and (not s.ready or bool(s._wanted))
            if asyncio.get_running_loop().time() > deadline:
                names = [f"task {t.label!r}" for t in running] + [
                    f"{c.get_name()!r}" for c in working
                ]
                raise RuntimeError(
                    f"the session did not settle in {timeout:g} s; still running: "
                    + (
                        ", ".join(names)
                        or ("a page switch" if switching else "nothing the harness can see")
                    )
                )
            if running:
                # The harness waiting is not the app observing the task, so a
                # failure nobody awaits still gets its toast and its report.
                _, still = await asyncio.wait([t._future for t in running], timeout=_TICK)
                if not (still and asking):
                    continue
            if working:
                _, still = await asyncio.wait(working, timeout=_TICK)
                if not (still and asking):
                    continue
            if switching:
                await asyncio.sleep(_TICK)
                continue
            if s.over and not (s.gone.done() and self._said_goodbye()):
                # Over: settled when its page is closed and its tab was told.
                await asyncio.sleep(_TICK)
                continue
            if s._render_due:
                # At once, where a running app waits out its timer.
                s.flush()
                if not s._render_due:
                    continue
            if not self._heard_everything():
                # What the session said is on its way to the tab.
                await asyncio.sleep(0)
                continue
            self._raise_failures()
            return


class _Tab:
    """The harness's end of a connection: what the session says is kept on
    the page, and nothing is ever said back over it."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self._closed: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def send_text(self, data: str) -> None:
        self._page.messages.append(server_message.validate_python(json.loads(data)["msg"]))

    async def send_bytes(self, data: bytes) -> None:
        pass

    async def receive(self) -> dict[str, Any]:
        await self._closed
        return {"type": "websocket.disconnect"}

    async def close(self, code: int = 1000) -> None:
        if not self._closed.done():
            self._closed.set_result(None)


@dataclass(frozen=True)
class Notice:
    """A toast as the page showed it."""

    message: str
    tone: str
    title: str | None = None


_MISSING: Any = object()


def _has(node: Node, component: Component | None, name: str, value: Any) -> bool:
    """Whether a node has a prop with this value: as it goes to the tab, or as
    the component holds it, which differ where the wire form is another shape."""
    if node.props.get(name, _MISSING) == value:
        return True
    return component is not None and getattr(component, name, _MISSING) == value


def _is_choice(field: Any) -> bool:
    """Whether a field's type is a Literal, or a union with one in it."""
    if field is None:
        return False
    annotation = field.annotation
    options = get_args(annotation) if get_origin(annotation) is not Literal else (annotation,)
    return any(get_origin(a) is Literal for a in (*options, annotation))


class TestApp:
    """Build the app once; open pages as sessions without a socket."""

    __test__ = False  # not a pytest collectable, despite the name

    def __init__(self, app: App, *, strict: bool = True) -> None:
        """``strict`` raises in the test what the app's code raised: a page
        function, a handler, a hook. ``strict=False`` leaves it in the log and
        in ``page.failures``, the way a running app treats it."""
        self.app = app
        self.strict = strict
        self._started = False

    async def startup(self) -> None:
        """Run the app's startup hooks, once, before the first page opens."""
        if self._started:
            return
        self._started = True
        self.app._begin()
        for fn in self.app._startup:
            result = fn()
            if asyncio.iscoroutine(result):
                await result

    async def shutdown(self) -> None:
        for fn in self.app._shutdown:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
        self._started = False

    @contextlib.asynccontextmanager
    async def open(
        self, path: str = "/", *, user: Any = None, state: Any = None
    ) -> AsyncIterator[Page]:
        """Open a page as a new session: connect (unless ``state`` is given), mount, yield."""
        await self.startup()
        resolved = self.app.locate(path)
        if resolved is None:
            raise LookupError(f"no page at {path}")
        page_def, params = resolved
        if self.app.auth is not None and not page_def.public and user is None:
            raise Forbidden("Sign in to continue.")
        verdict = self.app.may(user, page_def, params)
        if not verdict.ok:
            raise Forbidden(verdict.message or self.app.theme.text("forbidden_text"))
        session: Session[Any] = Session(self.app, page_def, params, path)
        session.user = user
        # What a page refuses with is raised in the test, where a running app
        # would land on its page for that.
        session.falls_back = False
        page = Page(session, strict=self.strict)
        if state is not None:
            session.state = state
            session.runs_connect = False
        scope = Scope("test harness")
        conn = Connection(_Tab(page), "test")

        async def close() -> None:
            # The page's close hook runs as the session ends.
            session.dismiss()
            await session.gone
            conn.close()
            await scope.wait(1.0)

        if not self.app.admit(session):
            raise RuntimeError("the app has no room for another session")
        session.attached(conn, 0)
        page._conn = conn
        page._tab = scope.start(conn.run(), "tab")
        try:
            refused = await session.opened
            if refused is not None:
                raise refused
            # From here the session behaves as in a running app: a page it
            # navigates to runs its connect, and lands on the app's page for
            # what a connect refuses.
            session.falls_back = session.runs_connect = True
            await page.settle()
            yield page
            await page.settle()
        except BaseException:
            await close()
            raise
        # What the close hook raises is the app's code failing like any other.
        seen = len(page.failures)
        await close()
        if self.strict and len(page.failures) > seen:
            where, exc = page.failures[seen]
            exc.add_note(f"raised by {where}")
            raise exc


__all__ = ["Found", "Notice", "Page", "TestApp"]
