"""The session's life without a socket: grace, close, replay, delivery, render failures."""

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.protocol import Event
from millwork.session import OUTBOX_KEEP, Session


class State(BaseModel):
    count: int = 0
    boom: bool = False
    not_a_component: bool = False


def make_app(tmp_path: Path, grace: float = 0.05) -> tuple[mw.App, dict[str, Any]]:
    log: dict[str, Any] = {"closed": 0}
    app = mw.App(
        "l",
        state=State,
        public=None,
        bundle_dir=tmp_path,
        session_grace=grace,
        files=mw.Files(tmp_path / "files"),
    )

    @app.page("/")
    def home(s: mw.Session[State]) -> Any:
        if s.state.boom:
            raise RuntimeError("render broke")
        if s.state.not_a_component:
            return "nope"
        return ui.Page(
            ui.Text(str(s.state.count), key="count"),
            ui.Button("+", key="inc", on_click=inc),
            ui.Button("fail", key="fail", on_click=fail),
            ui.Button("ask", key="ask", on_click=ask),
            ui.Button("run", key="run", on_click=run),
        )

    @home.close
    async def closed(s: mw.Session[State]) -> None:
        log["closed"] += 1
        if log.get("close_raises"):
            raise RuntimeError("close hook broke")

    async def inc(s: mw.Session[State], _: Any) -> None:
        s.state.count += 1

    async def fail(s: mw.Session[State], _: Any) -> None:
        raise ValueError("handler broke")

    async def ask(s: mw.Session[State], _: Any) -> None:
        log["answer"] = await s.confirm("Sure?")
        log["after"] = s.closed

    async def run(s: mw.Session[State], _: Any) -> None:
        async def forever() -> None:
            await asyncio.sleep(60)

        log["task"] = s.task(forever, label="forever")

    return app, log


class Wire:
    """A fake socket: what the session sent, decoded, and a switch to make sends fail."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.seqs: list[int] = []
        self.broken = False
        self.closed = 0
        # One callable per socket, as the endpoint captures ``ws.send_text`` once:
        # the session tells sockets apart by identity.
        self.sender = self.send

    async def send(self, text: str) -> None:
        if self.broken:
            raise ConnectionError("gone")
        env = json.loads(text)
        self.seqs.append(env["seq"])
        self.messages.append(env["msg"])

    async def close(self) -> None:
        self.closed += 1

    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]


async def open_session(app: mw.App, wire: Wire) -> Session[Any]:
    resolved = app.resolve("/")
    assert resolved is not None
    page, params = resolved
    session: Session[Any] = Session(app, page, params, "/")
    app.sessions[session.id] = session
    await session.connect()
    await session.attach(wire.sender, 0, close=wire.close)
    return session


async def flush(session: Session[Any]) -> None:
    """Run what the session queued, then its coalesced render now instead of after the timer."""
    for _ in range(20):
        await asyncio.sleep(0)
    if session._render_scheduled and session._render_handle is not None:
        session._render_handle.cancel()
        session._render_scheduled = False
        session._render_handle = None
        await session._render()
    for _ in range(5):
        await asyncio.sleep(0)


async def click(session: Session[Any], key: str) -> None:
    await session.dispatch(Event(node=f"root/{key}", name="click"))
    await flush(session)


async def test_grace_closes_the_session_once_and_a_reattach_cancels_it(tmp_path: Path) -> None:
    app, log = make_app(tmp_path, grace=0.05)
    wire = Wire()
    session = await open_session(app, wire)
    session.files.add(b"x", name="x.bin")
    assert app.files.session_dir(session.id).is_dir()

    # Detaching starts the grace timer; reattaching in time cancels it.
    session.detach(wire.sender)
    assert not session.connected and session._grace is not None
    await session.attach(wire.sender, 0, close=wire.close)
    assert session._grace is None and session.connected
    await asyncio.sleep(0.1)  # the grace timer is the thing under test
    assert not session.closed and log["closed"] == 0

    # A stale socket's detach is ignored; the live one's detach starts the clock.
    other = Wire()
    session.detach(other.sender)
    assert session.connected
    session.detach(wire.sender)
    await asyncio.sleep(0.1)
    assert session.closed and log["closed"] == 1
    assert session.id not in app.sessions
    assert not app.files.session_dir(session.id).exists()

    # Closing again is a no-op, and a detach after close starts no timer.
    await session.close()
    session.detach()
    assert log["closed"] == 1 and session._grace is None


async def test_close_cancels_work_and_the_handler_waiting_on_an_ask(tmp_path: Path) -> None:
    app, log = make_app(tmp_path)
    wire = Wire()
    session = await open_session(app, wire)

    await click(session, "run")
    task = log["task"]
    assert task.status == "running"
    asking = session.spawn(session.dispatch(Event(node="root/ask", name="click")), "ask")
    await flush(session)
    assert session._asks and any(n.endswith("/ok") for n in session.tree.nodes)  # type: ignore[union-attr]

    log["close_raises"] = True
    await session.close()
    await flush(session)
    # The hook's failure is logged, not raised, and the session is still closed.
    assert session.closed and log["closed"] == 1
    assert task.status == "cancelled"
    # The handler was cancelled at the ask: it never ran on past a closed session.
    assert asking.cancelled() and "answer" not in log and "after" not in log
    assert not session._lock.locked()
    # Nothing renders or dispatches after close.
    session.refresh()
    assert not session._render_scheduled
    before = len(wire.messages)
    await session.dispatch(Event(node="root/inc", name="click"))
    assert len(wire.messages) == before


async def test_replay_window_and_full_mount_outside_it(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    wire = Wire()
    session = await open_session(app, wire)
    assert wire.types() == ["session", "mount"]
    for _ in range(3):
        await click(session, "inc")
    assert wire.types().count("patch") == 3
    last = wire.seqs[-1]

    # Exactly caught up: nothing to replay, and no mount either.
    again = Wire()
    await session.attach(again.sender, last)
    assert again.types() == ["session"]
    # Behind by two patches: those two come back, in order, with their original seqs.
    again = Wire()
    await session.attach(again.sender, last - 2)
    assert again.types() == ["session", "patch", "patch"] and again.seqs[1:] == [last - 1, last]
    # A tab that claims more than was ever sent, or one that sent nothing, gets a mount.
    for claimed in (last + 5, 0):
        again = Wire()
        await session.attach(again.sender, claimed)
        assert again.types() == ["session", "mount"]
        assert again.messages[1]["nodes"]["root/count"]["props"]["content"] == "3"

    # Once the outbox has forgotten the tab's position, the mount is the only option.
    for _ in range(OUTBOX_KEEP + 2):
        session.toast("x")
    await flush(session)
    first = session._outbox[0][0]
    assert first > last
    again = Wire()
    await session.attach(again.sender, first - 1)  # the oldest kept message is the next one
    assert again.types() == ["session"] + ["command"] * OUTBOX_KEEP and again.seqs[1] == first
    again = Wire()
    await session.attach(again.sender, first - 2)  # one message older than kept: a mount
    assert again.types() == ["session", "mount"]
    await session.close()


async def test_a_failing_send_detaches_replays_later_and_runs_out_the_grace(
    tmp_path: Path,
) -> None:
    app, log = make_app(tmp_path, grace=0.05)
    wire = Wire()
    session = await open_session(app, wire)
    last = wire.seqs[-1]
    wire.broken = True
    await click(session, "inc")
    # The socket is treated as gone: detached, grace running, the message kept for replay.
    assert not session.connected and session._grace is not None
    assert len(wire.messages) == 2 and session._seq == last + 1
    # The endpoint's own detach for that socket, arriving later, changes nothing.
    session.detach(wire.sender)
    assert session._grace is not None and not session.closed
    fresh = Wire()
    await session.attach(fresh.sender, last)
    assert session._grace is None
    assert fresh.types() == ["session", "patch"]
    assert fresh.messages[1]["ops"] == [
        {"op": "set", "id": "root/count", "props": {"content": "1"}}
    ]
    # With no tab coming back, the grace closes the session.
    fresh.broken = True
    await click(session, "inc")
    await asyncio.sleep(0.1)  # the grace timer is the thing under test
    assert session.closed and log["closed"] == 1 and session.id not in app.sessions


async def test_a_second_attach_closes_the_first_socket(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    first, second = Wire(), Wire()
    session = await open_session(app, first)
    await session.attach(second.sender, 0, close=second.close)
    assert first.closed == 1 and second.closed == 0
    await click(session, "inc")
    # The superseded socket receives nothing more; the new one gets the patch.
    assert len(first.messages) == 2 and second.types() == ["session", "mount", "patch"]
    await session.close()


async def test_render_coalesces_and_failures_become_errors_not_crashes(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    wire = Wire()
    session = await open_session(app, wire)

    # Many refreshes in one tick are one patch; a refresh with nothing changed is none.
    session.state.count = 5
    for _ in range(10):
        session.refresh()
    assert session._render_scheduled
    await flush(session)
    assert wire.types().count("patch") == 1
    session.refresh()
    await flush(session)
    assert wire.types().count("patch") == 1

    # A handler that raises: a toast, and nothing else.
    await click(session, "fail")
    assert wire.messages[-1] == {
        "type": "command",
        "name": "toast",
        "args": {"message": "Something went wrong.", "tone": "destructive", "title": None},
    }

    # A page that raises keeps the last tree and tells the tab, without a fatal error.
    kept = session.tree
    session.state.boom = True
    session.refresh()
    await flush(session)
    assert wire.messages[-1] == {
        "type": "error",
        "message": "The page failed to render.",
        "fatal": False,
    }
    assert session.tree is kept
    # Events still dispatch against that tree, and the page recovers once it renders again.
    session.state.boom = False
    await click(session, "inc")
    assert wire.messages[-1]["type"] == "patch"
    assert session.tree.nodes["root/count"].props["content"] == "6"  # type: ignore[union-attr]
    # A page that returns something other than a component is the same failure.
    session.state.not_a_component = True
    session.refresh()
    await flush(session)
    assert wire.messages[-1]["type"] == "error"
    await session.close()


async def test_a_failed_navigate_leaves_the_session_on_its_page(tmp_path: Path) -> None:
    from millwork.auth import NotFound

    app, _ = make_app(tmp_path)

    @app.page("/bad")
    def bad(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("never", key="t"))

    @bad.connect
    async def load(s: mw.Session[State]) -> None:
        raise RuntimeError("db down")

    @app.page("/gone")
    def gone(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("never", key="t"))

    @gone.connect
    async def missing(s: mw.Session[State]) -> None:
        raise NotFound("No such thing.")

    wire = Wire()
    session = await open_session(app, wire)
    await click(session, "inc")
    tree = session.tree
    await session.navigate_to("/bad")
    assert wire.messages[-1] == {
        "type": "error",
        "message": "The page failed to start.",
        "fatal": False,
    }
    # Page, path, state and tree are what they were; the next click still works.
    assert session.path == "/" and session.state.count == 1 and session.tree is tree
    await click(session, "inc")
    assert wire.messages[-1]["ops"] == [
        {"op": "set", "id": "root/count", "props": {"content": "2"}}
    ]
    # NotFound from connect is not a failure: the session moves to the not-found
    # page under the path it asked for, with the message.
    await session.navigate_to("/gone")
    assert session.path == "/gone" and session.page is app.error_pages["not_found"]
    assert session.params == {"path": "/gone", "message": "No such thing."}
    assert wire.messages[-2]["args"] == {"path": "/gone", "title": "Page not found"}
    assert "No such thing." in [
        n["props"].get("content") for n in wire.messages[-1]["nodes"].values()
    ]
    await session.close()


async def test_seqs_only_grow_and_direct_messages_do_not_count(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    wire = Wire()
    session = await open_session(app, wire)
    for _ in range(3):
        await click(session, "inc")
    session.toast("a")
    session.command("clipboard", text="b")
    await flush(session)
    numbered = [s for s, m in zip(wire.seqs, wire.messages, strict=True) if m["type"] != "session"]
    assert numbered == sorted(numbered) and len(set(numbered)) == len(numbered)
    assert numbered[-1] == session._seq
    # The session info on attach repeats the current seq rather than consuming one.
    again = Wire()
    await session.attach(again.sender, session._seq)
    assert again.seqs == [session._seq]
    await session.close()


class SlowWire(Wire):
    """A socket whose writes yield, as a real one does."""

    async def send(self, text: str) -> None:
        await asyncio.sleep(0)
        await super().send(text)


async def test_a_message_during_a_replay_is_delivered_once_and_in_order(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    wire = Wire()
    session = await open_session(app, wire)
    for _ in range(3):
        await click(session, "inc")
    behind = wire.seqs[-3]  # the tab missed the last two patches
    again = SlowWire()
    attaching = asyncio.ensure_future(session.attach(again.sender, behind))
    await asyncio.sleep(0)  # the session info is being written
    session.toast("mid")  # lands while the replay is in flight
    await attaching
    await flush(session)
    numbered = again.seqs[1:]
    assert numbered == sorted(numbered) and len(set(numbered)) == len(numbered)
    assert again.types() == ["session", "patch", "patch", "command"]
    assert session.connected
    # A socket that dies during the replay never becomes the session's socket.
    dead = SlowWire()
    dead.broken = True
    await session.attach(dead.sender, behind)
    assert not session.connected and session._grace is not None
    good = Wire()
    await session.attach(good.sender, behind)
    assert session.connected and good.types()[0] == "session"
    await session.close()


async def test_navigate_renders_nothing_before_the_new_page_is_connected(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)

    @app.page("/slow")
    def slow(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("ready" if s.state.count else "not connected", key="t"))

    @slow.connect
    async def load(s: mw.Session[State]) -> None:
        await asyncio.sleep(0.1)  # longer than the render coalesce window
        s.state.count = 1

    wire = Wire()
    session = await open_session(app, wire)
    before = len(wire.messages)
    session.refresh()  # a render falls due while the connect runs
    await session.navigate_to("/slow")
    await flush(session)
    new = wire.messages[before:]
    assert [m["type"] for m in new] == ["command", "mount"]
    assert new[0]["name"] == "navigate"
    assert new[1]["nodes"]["root/t"]["props"]["content"] == "ready"
    await session.close()


async def test_a_reply_reaches_a_socket_still_catching_up(tmp_path: Path) -> None:
    """A request answered while the new socket replays the backlog is not lost."""
    from millwork.protocol import Reply

    app, _ = make_app(tmp_path)
    wire = Wire()
    session = await open_session(app, wire)
    await session.attach(wire.sender, 0, close=wire.close)
    await flush(session)
    for _ in range(3):
        session.refresh()
        await flush(session)
    last = session._seq
    again = Wire()
    replied: list[str] = []

    async def slow_send(text: str) -> None:
        await again.send(text)
        if len(again.messages) == 1:  # right after the session info, mid-replay
            await session._send_unnumbered(Reply(request="r", payload=1))
            replied.append("sent")

    again.sender = slow_send
    await session.attach(again.sender, last - 2)
    assert replied == ["sent"]
    assert any(m.get("type") == "reply" and m.get("request") == "r" for m in again.messages)
    assert 0 in again.seqs


async def test_a_page_closes_before_the_next_connects_and_only_once(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    class Project(BaseModel):
        item: str = ""

    calls: list[str] = []
    app = mw.App("order", state=Project, public=None, bundle_dir=tmp_path)

    @app.page("/p/{n:int}")
    def project(s: mw.Session[Project]) -> ui.Component:
        return ui.Page(ui.Text(f"project {s.state.item}", key="t"))

    @project.connect
    def load(s: mw.Session[Project], n: int) -> None:
        s.state.item = f"#{n}"
        calls.append(f"load {n}")

    @project.close
    def release(s: mw.Session[Project]) -> None:
        calls.append(f"release {s.state.item}")

    @app.page("/bad")
    def bad(s: mw.Session[Project]) -> ui.Component:
        return ui.Page(ui.Text("never", key="t"))

    @bad.connect
    def broken(s: mw.Session[Project], **_: Any) -> None:
        raise RuntimeError("db down")

    # The same page with other parameters: closed with the old state, then connected.
    async with TestApp(app, strict=False).open("/p/1") as page:
        await page.navigate("/p/2")
        assert page.find("t").props["content"] == "project #2"
        assert calls == ["load 1", "release #1", "load 2"]
        # A page that fails to start: the one left has closed and is not closed again.
        await page.navigate("/bad")
        assert page.session.path == "/p/2" and page.failures[-1][0] == "the connect hook of /bad"
        assert calls == ["load 1", "release #1", "load 2", "release #2"]
        # A navigate after the end does nothing.
        await page.session.close()
        await page.session.navigate_to("/p/3")
    assert calls == ["load 1", "release #1", "load 2", "release #2"]
