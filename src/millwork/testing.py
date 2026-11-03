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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from millwork.auth import Forbidden
from millwork.files import FileRef, _read_chunks
from millwork.nodes import Component
from millwork.protocol import Command, Event, Patch, ServerError, Stream, server_message
from millwork.session import Session
from millwork.ui.chat import Chat
from millwork.ui.files import FileUpload
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
        session.on_failure = self._failed

    def _failed(self, where: str, exc: BaseException) -> None:
        self.failures.append((where, exc))

    def _raise_failures(self) -> None:
        """In a strict harness, what the app raised is raised in the test, where the
        traceback points at the cause instead of at an empty page or a toast."""
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

    def find_all(self, what: type[Component] | str) -> list[Found]:
        """Every node of a component type, or with a key (or a full id)."""
        tree = self.session.tree
        if tree is None:
            return []
        out = []
        for node_id, node in tree.nodes.items():
            if isinstance(what, str):
                component = tree.components.get(node_id)
                hit = (
                    node_id == what
                    or node_id.rsplit("/", 1)[-1] == what
                    or (component is not None and component.key == what)
                )
            else:
                hit = node.type == what.type
            if hit:
                out.append(Found(node, tree.components.get(node_id)))
        return out

    def find(self, what: type[Component] | str) -> Found:
        found = self.find_all(what)
        if not found:
            name = what if isinstance(what, str) else what.__name__
            raise LookupError(f"no {name} on the page")
        return found[0]

    def text(self) -> str:
        """Every string prop of the tree, for a quick "is it there" check."""
        parts: list[str] = []
        for node in self.tree.values():
            for value in node.props.values():
                if isinstance(value, str):
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
        return [str(c.args.get("message", "")) for c in self.commands if c.name == "toast"]

    @property
    def stream(self) -> list[dict[str, Any]]:
        return [m.chunk for m in self.messages if isinstance(m, Stream)]

    @property
    def errors(self) -> list[str]:
        return [m.message for m in self.messages if isinstance(m, ServerError)]

    # ------------------------------------------------------------- acting

    async def event(self, node: Found | str, name: str, payload: Any = None) -> None:
        """One event through the real dispatcher, then everything it set off."""
        node_id = node.id if isinstance(node, Found) else self.find(node).id
        self.session.spawn(
            self.session.dispatch(Event(node=node_id, name=name, payload=payload)), "test event"
        )
        await self.settle()

    async def click(self, node: Found | str) -> None:
        await self.event(node, "click")

    async def toast_action(self, label: str) -> None:
        """Press the button of the latest toast that has one with this label."""
        for command in reversed(self.commands):
            action = command.args.get("action") if command.name == "toast" else None
            if isinstance(action, dict) and action.get("label") == label:
                token = action["id"]
                break
        else:
            raise LookupError(f"no toast with a {label!r} button")
        self.session.spawn(
            self.session.dispatch(Event(node=f"toast:{token}", name="action")), "test toast action"
        )
        await self.settle()

    async def change(self, node: Found | str, value: Any) -> None:
        await self.event(node, "change", value)

    async def submit(self, form: Found | str, draft: Any) -> None:
        """Submit a draft (a dict or a model instance) as the tab would."""
        if hasattr(draft, "model_dump"):
            draft = draft.model_dump(mode="json")
        await self.event(form, "submit", draft)

    async def select(self, table: Found | str, keys: list[Any]) -> None:
        await self.event(table, "select", keys)

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
        text: str,
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
            spawned = [t for t in s._spawned if not t.done()]
            if asyncio.get_running_loop().time() > deadline:
                names = [f"task {t.label!r}" for t in running] + [
                    f"spawned {t.get_name()!r}" for t in spawned
                ]
                raise RuntimeError(
                    f"the session did not settle in {timeout:g} s; still running: "
                    + (", ".join(names) or "nothing the harness can see")
                )
            if running:
                _, still = await asyncio.wait([t.future for t in running], timeout=_TICK)
                if not (still and asking):
                    continue
            if spawned:
                _, still = await asyncio.wait(spawned, timeout=_TICK)
                if not (still and asking):
                    continue
            if s._render_scheduled and s._render_handle is not None:
                s._render_handle.cancel()
                s._render_scheduled = False
                s._render_handle = None
                await s._render()
                continue
            self._raise_failures()
            return


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
        resolved = self.app.resolve(path)
        if resolved is None:
            raise LookupError(f"no page at {path}")
        page_def, params = resolved
        if self.app.auth is not None and not page_def.public and user is None:
            raise Forbidden("Sign in to continue.")
        session: Session[Any] = Session(self.app, page_def, params, path)
        session.user = user
        self.app.sessions[session.id] = session
        page = Page(session, strict=self.strict)

        async def send(text: str) -> None:
            page.messages.append(server_message.validate_python(json.loads(text)["msg"]))

        try:
            if state is not None:
                session.state = state
            else:
                await session.connect()
            await session.attach(send, 0)
            await page.settle()
            yield page
            await page.settle()
        finally:
            await session.close()


__all__ = ["Found", "Page", "TestApp"]
