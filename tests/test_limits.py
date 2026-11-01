"""The bounds a public host relies on: session caps, the in-flight bound, the
chat message length, the app-wide file quota, logout ending live sessions
and versioned custom components."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import millwork as mw
from millwork import auth, ui
from millwork.files import Files, Reject
from millwork.session import MAX_INFLIGHT


def hello(ws: Any, path: str = "/") -> dict[str, Any]:
    ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": path}}))
    return json.loads(ws.receive_text())["msg"]


def wait_until(check: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "the condition did not come about"
        time.sleep(0.01)


def counter_app(tmp_path: Path, **kw: Any) -> mw.App:
    class S(BaseModel):
        n: int = 0

    app = mw.App("caps", state=S, public=None, bundle_dir=tmp_path, **kw)

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        return ui.Page(ui.Text(str(s.state.n), key="n"))

    return app


def test_a_client_over_its_cap_loses_its_oldest_tabless_session_first(tmp_path: Path) -> None:
    app = counter_app(tmp_path, max_sessions_per_client=2)
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as first:
            first_id = hello(first)["id"]
        wait_until(lambda: first_id in app.sessions and not app.sessions[first_id].connected)
        with client.websocket_connect("/_mw/ws") as second:
            assert hello(second)["type"] == "session"
            # At the cap: the session whose tab went away makes room.
            with client.websocket_connect("/_mw/ws") as third:
                assert hello(third)["type"] == "session"
                wait_until(lambda: first_id not in app.sessions)
                assert len(app.sessions) == 2
                # Every session of this client has a tab: the next one is refused.
                with client.websocket_connect("/_mw/ws") as fourth:
                    msg = hello(fourth)
                    assert msg == {
                        "type": "error",
                        "message": "Too many open sessions.",
                        "fatal": True,
                    }
                    with pytest.raises(WebSocketDisconnect) as info:
                        fourth.receive_text()
                    assert info.value.code == 4429
                assert len(app.sessions) == 2


def test_the_app_wide_cap_makes_room_from_any_client(tmp_path: Path) -> None:
    app = counter_app(tmp_path, max_sessions=1, max_sessions_per_client=10)
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as first:
            first_id = hello(first)["id"]
            with client.websocket_connect("/_mw/ws") as second:
                assert hello(second)["type"] == "error"
            assert list(app.sessions) == [first_id]
        wait_until(lambda: not app.sessions[first_id].connected)
        with client.websocket_connect("/_mw/ws") as second:
            second_id = hello(second)["id"]
            wait_until(lambda: list(app.sessions) == [second_id])
            assert app.sessions[second_id].client == "addr:testclient"


def test_a_session_being_connected_keeps_its_place(tmp_path: Path) -> None:
    app = counter_app(tmp_path, max_sessions_per_client=2)
    loop: list[asyncio.AbstractEventLoop] = []

    @app.on_startup
    def ready() -> None:
        loop.append(asyncio.get_running_loop())

    @app.page("/slow")
    def slow(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("slow", key="t"))

    @slow.connect
    async def lookup(s: mw.Session) -> None:
        await asyncio.sleep(0.4)

    with TestClient(app.asgi) as client:
        with (
            client.websocket_connect("/_mw/ws") as first,
            client.websocket_connect("/_mw/ws") as second,
            client.websocket_connect("/_mw/ws") as third,
        ):
            assert hello(first)["type"] == "session"
            second.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/slow"}}))
            wait_until(lambda: any(s.connecting for s in app.sessions.values()))
            # The second session has no socket yet but it has its tab: the third
            # hello is refused rather than evicting it.
            assert hello(third)["type"] == "error"
            assert json.loads(second.receive_text())["msg"]["type"] == "session"
            assert json.loads(second.receive_text())["msg"]["type"] == "mount"
        # Signed out (or evicted) while connecting: the tab is told once the
        # connect finishes, since nothing could reach it before.
        wait_until(lambda: all(not s.has_tab for s in app.sessions.values()))
        with client.websocket_connect("/_mw/ws") as late:
            late.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/slow"}}))
            wait_until(lambda: any(s.connecting for s in app.sessions.values()))
            connecting = next(s for s in app.sessions.values() if s.connecting)
            asyncio.run_coroutine_threadsafe(connecting.end("Signed out."), loop[0]).result(2)
            msg = json.loads(late.receive_text())["msg"]
            assert msg == {"type": "error", "message": "Signed out.", "fatal": True}
            with pytest.raises(WebSocketDisconnect) as info:
                late.receive_text()
            assert info.value.code == 4409


def test_an_answer_to_an_open_ask_passes_the_inflight_bound(tmp_path: Path) -> None:
    class S(BaseModel):
        confirmed: int = 0

    app = mw.App("ask", state=S, public=None, bundle_dir=tmp_path)
    loop: list[asyncio.AbstractEventLoop] = []
    gate: list[asyncio.Event] = []

    @app.on_startup
    def ready() -> None:
        loop.append(asyncio.get_running_loop())
        gate.append(asyncio.Event())

    async def slow(s: mw.Session[S], _: Any) -> None:
        await gate[0].wait()

    async def danger(s: mw.Session[S], _: Any) -> None:
        if await s.confirm("Sure?"):
            s.state.confirmed += 1

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        return ui.Page(
            ui.Button("slow", key="slow", on_click=slow),
            ui.Button("danger", key="danger", on_click=danger),
        )

    def send(ws: Any, seq: int, msg: dict[str, Any]) -> None:
        ws.send_text(json.dumps({"seq": seq, "msg": msg}))

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        session_id = hello(ws)["id"]
        assert json.loads(ws.receive_text())["msg"]["type"] == "mount"
        send(ws, 2, {"type": "event", "node": "root/danger", "name": "click"})
        session = app.sessions[session_id]
        # The dialog is on screen once its patch has arrived; only then can it be answered.
        ok = ""
        while not ok:
            msg = json.loads(ws.receive_text())["msg"]
            if msg["type"] == "patch":
                ids = [op["node"]["id"] for op in msg["ops"] if isinstance(op.get("node"), dict)]
                ok = next((i for i in ids if i.endswith("/@footer/ok")), "")
        for i in range(MAX_INFLIGHT + 5):
            send(ws, 10 + i, {"type": "event", "node": "root/slow", "name": "click"})
        wait_until(lambda: session.inflight == MAX_INFLIGHT)
        send(ws, 500, {"type": "event", "node": ok, "name": "click"})
        loop[0].call_soon_threadsafe(gate[0].set)
        wait_until(lambda: session.inflight == 0, timeout=5)
        assert session.state.confirmed == 1 and not session._asks
        # One toast for the whole backlog, not one per dropped click.
        errors = []
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not errors:
            msg = json.loads(ws.receive_text())["msg"]
            if msg["type"] == "error":
                errors.append(msg)
        assert errors == [
            {"type": "error", "message": "Too many actions at once; wait a moment.", "fatal": False}
        ]


def test_messages_beyond_the_inflight_bound_are_dropped(tmp_path: Path) -> None:
    class S(BaseModel):
        n: int = 0

    app = mw.App("flood", state=S, public=None, bundle_dir=tmp_path)
    loop: list[asyncio.AbstractEventLoop] = []
    gate: list[asyncio.Event] = []

    @app.on_startup
    def ready() -> None:
        loop.append(asyncio.get_running_loop())
        gate.append(asyncio.Event())

    async def bump(s: mw.Session[S], _: Any) -> None:
        if s.state.n == 0:
            await gate[0].wait()
        s.state.n += 1

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        return ui.Page(ui.Text(str(s.state.n), key="n"), ui.Button("go", key="go", on_click=bump))

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        session_id = hello(ws)["id"]
        assert json.loads(ws.receive_text())["msg"]["type"] == "mount"
        for i in range(MAX_INFLIGHT + 20):
            ws.send_text(
                json.dumps(
                    {"seq": i + 2, "msg": {"type": "event", "node": "root/go", "name": "click"}}
                )
            )
        session = app.sessions[session_id]
        # The first click holds the lock; the bound counts what is queued behind it.
        wait_until(lambda: session.inflight == MAX_INFLIGHT)
        time.sleep(0.1)
        assert session.inflight == MAX_INFLIGHT
        loop[0].call_soon_threadsafe(gate[0].set)
        last = ""
        deadline = time.monotonic() + 5
        while last != str(MAX_INFLIGHT) and time.monotonic() < deadline:
            msg = json.loads(ws.receive_text())["msg"]
            if msg["type"] == "patch":
                last = msg["ops"][-1]["props"]["content"]
        assert last == str(MAX_INFLIGHT)
        wait_until(lambda: session.inflight == 0)
        assert session.state.n == MAX_INFLIGHT


async def test_a_chat_message_over_its_length_is_refused(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    app = mw.App("chat", public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Chat(key="chat", on_message=lambda s, t: None),
            ui.Chat(key="short", max_chars=10, on_message=lambda s, t: None),
        )

    async with TestApp(app).open("/") as page:
        await page.event("chat", "message", {"text": "x" * 16_000})
        assert len(page.session.chat("chat").messages) == 1
        await page.event("chat", "message", {"text": "x" * 16_001})
        assert len(page.session.chat("chat").messages) == 1
        await page.event("short", "message", {"text": "x" * 11})
        assert page.session.chat("short").messages == []
        assert page.toasts == ["The message is too long.", "The message is too long."]


async def test_the_app_wide_file_quota_counts_every_session(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    files = Files(tmp_path / "files", max_session_mb=1, max_total_mb=1)
    files.max_total_bytes = 1000
    app = mw.App("quota", public=None, bundle_dir=tmp_path, files=files)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("x"))

    async with TestApp(app).open("/") as one, TestApp(app).open("/") as two:
        a = one.session.files.add(b"a" * 600, name="a.bin")
        assert files.used(one.session.id) == 600 and files.used() == 600
        with pytest.raises(Reject, match="file space") as info:
            two.session.files.add(b"b" * 500, name="b.bin")
        assert info.value.status == 507
        # A refused stream holds no space, and gives back only what it held: the
        # refused chunk was never counted, so the count stays exact.
        assert files.used() == 600 and two.session.files.all() == []
        for _ in range(3):
            with pytest.raises(Reject, match="file space"):
                two.session.files.add(b"b" * 500, name="b.bin")
        assert files.used() == 600 and files.used(one.session.id) == 600
        assert one.session.files.remove(a.id)
        assert files.used() == 0
        two.session.files.add(b"b" * 500, name="b.bin")
        one.session.files.add(b"c" * 500, name="c.bin")
        assert files.used() == 1000
    # Closed sessions free theirs.
    assert files.used() == 0


def test_logout_ends_the_users_live_sessions(tmp_path: Path) -> None:
    hashed = auth.hash_password("pw")
    app = mw.App(
        "a",
        public=None,
        bundle_dir=tmp_path,
        secret="s3cret-s3cret-s3cret-s3cret-s3cret",
        auth=auth.Auth(
            [auth.Password(lambda u, p: u == "demian" and auth.check_password(p, hashed))],
            on_login=lambda identity: auth.User(id=identity.subject, name=identity.subject),
        ),
    )

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("hi", key="t"))

    with TestClient(app.asgi) as client:
        r = client.post("/_mw/auth/login", json={"username": "demian", "password": "pw"})
        assert r.status_code == 200
        with client.websocket_connect("/_mw/ws") as ws:
            session_id = hello(ws)["id"]
            assert json.loads(ws.receive_text())["msg"]["type"] == "mount"
            assert client.post("/_mw/auth/logout").status_code == 200
            msg = json.loads(ws.receive_text())["msg"]
            assert msg == {"type": "error", "message": "Signed out.", "fatal": True}
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        assert session_id not in app.sessions


def test_custom_components_are_versioned_by_content(tmp_path: Path) -> None:
    comps = tmp_path / "components"
    comps.mkdir()
    (comps / "Hello.jsx").write_text("export default () => null;")
    app = mw.App("c", public=None, bundle_dir=tmp_path, components=comps)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Custom("Hello"))

    with TestClient(app.asgi) as client:
        version = app.component_versions["Hello"]
        assert len(version) == 16
        # The current version may be cached for good; anything else is checked each time.
        r = client.get(f"/_mw/components/Hello.jsx?v={version}")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        r = client.get("/_mw/components/Hello.jsx?v=stale")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        assert client.get("/_mw/components/Hello.jsx").headers["cache-control"] == "no-cache"
        # A new session tells the tab the versions, so a tab that outlived a
        # deploy fetches the changed source.
        with client.websocket_connect("/_mw/ws") as ws:
            assert hello(ws)["components"] == {"Hello": version}
        (comps / "Hello.jsx").write_text("export default () => 'v2';")
        app.component_versions = app._component_hashes()
        assert app.component_versions["Hello"] != version
