"""Slice 0 end to end, without a browser: hello, mount, event, patch, resume."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import millwork as mw
from millwork import ui


class State(BaseModel):
    count: int = 0
    name: str = ""


def make_app(tmp_path: Path) -> mw.App:
    app = mw.App("t", state=State, public=None, bundle_dir=tmp_path, session_grace=60)

    @app.page("/", title="Counter")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("+", key="inc", on_click=inc),
            ui.Text(str(s.state.count), key="count"),
            ui.Input(default="", key="name", on_change=named),
            ui.Text(s.state.name, key="greeting") if s.state.name else None,
        )

    async def inc(s: mw.Session[State], _: Any) -> None:
        s.state.count += 1

    async def named(s: mw.Session[State], value: str) -> None:
        s.state.name = value
        s.toast("hi")

    return app


def send(ws: Any, msg: dict[str, Any], seq: int = 1) -> None:
    ws.send_text(json.dumps({"seq": seq, "msg": msg}))


def recv(ws: Any) -> dict[str, Any]:
    env = json.loads(ws.receive_text())
    return env["msg"]


def hello(ws: Any, path: str = "/", **extra: Any) -> dict[str, Any]:
    send(ws, {"type": "hello", "path": path, **extra})
    info = recv(ws)
    assert info["type"] == "session"
    return info


def test_mount_event_patch(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        mount = recv(ws)
        assert mount["type"] == "mount"
        assert mount["title"] == "Counter"
        assert mount["nodes"]["root/count"]["props"]["content"] == "0"
        assert mount["nodes"]["root/inc"]["props"]["on_click"] is True
        assert "root/greeting" not in mount["nodes"]

        send(ws, {"type": "event", "node": "root/inc", "name": "click"})
        patch = recv(ws)
        assert patch["type"] == "patch"
        assert patch["ops"] == [{"op": "set", "id": "root/count", "props": {"content": "1"}}]

        send(ws, {"type": "event", "node": "root/name", "name": "change", "payload": "Ada"})
        first, second = recv(ws), recv(ws)
        by_type = {m["type"]: m for m in (first, second)}
        assert by_type["command"]["name"] == "toast"
        ops = by_type["patch"]["ops"]
        assert ops[0]["op"] == "add" and ops[0]["node"]["id"] == "root/greeting"
        assert ops[-1] == {
            "op": "children",
            "id": "root",
            "children": ["root/inc", "root/count", "root/name", "root/greeting"],
        }


def test_resume_replays_missed_patches(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            info = hello(ws)
            mount_env = json.loads(ws.receive_text())
            assert mount_env["msg"]["type"] == "mount"
            send(ws, {"type": "event", "node": "root/inc", "name": "click"})
            patch_env = json.loads(ws.receive_text())
            last_seq = patch_env["seq"]
        # The tab dropped; the session is still there for the grace period.
        assert info["id"] in app.sessions
        with client.websocket_connect("/_mw/ws") as ws:
            hello(ws, session=info["id"], resume=info["resume"], seq=last_seq - 1)
            replayed = json.loads(ws.receive_text())
            assert replayed["seq"] == last_seq
            assert replayed["msg"]["ops"][0]["props"] == {"content": "1"}
        # A wrong resume token is a fresh session, not someone else's.
        with client.websocket_connect("/_mw/ws") as ws:
            info2 = hello(ws, session=info["id"], resume="nope")
            assert info2["id"] != info["id"]
            assert recv(ws)["type"] == "mount"


def test_unknown_page_and_protocol(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            # No page at the path: the session opens on the not-found page.
            hello(ws, "/nope")
            assert "There is nothing at /nope." in texts(recv(ws))
        with client.websocket_connect("/_mw/ws") as ws:
            send(ws, {"type": "hello", "path": "/", "protocol": 999})
            assert recv(ws) == {"type": "command", "name": "reload", "args": {}}
            assert closed_with(ws) == 4426
        assert client.get("/_mw/health").json()["ok"] is True
        assert client.get("/").status_code == 503  # no bundle in tmp_path
        missing = client.get("/nope")
        assert missing.status_code == 404 and "There is nothing at /nope." in missing.text


def test_superseded_socket_does_not_detach_the_live_one(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        first = client.websocket_connect("/_mw/ws")
        ws1 = first.__enter__()
        info = hello(ws1)
        recv(ws1)
        session = app.sessions[info["id"]]
        with client.websocket_connect("/_mw/ws") as ws2:
            hello(ws2, session=info["id"], resume=info["resume"], seq=0)
            assert recv(ws2)["type"] == "mount"
            # The first socket was told to go; its late disconnect must not detach the session.
            try:
                first.__exit__(None, None, None)
            except Exception:
                pass
            assert session.connected
            send(ws2, {"type": "event", "node": "root/inc", "name": "click"})
            assert recv(ws2)["ops"][0]["props"] == {"content": "1"}


def test_disabled_and_unknown_nodes_take_no_events(tmp_path: Path) -> None:
    app = mw.App("d", state=State, public=None, bundle_dir=tmp_path)
    hits: list[str] = []

    def hit(label: str) -> Any:
        async def handler(s: mw.Session[State], payload: Any) -> None:
            hits.append(label if payload is None else str(payload))
            s.toast(label)

        return handler

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("x", key="off", disabled=True, on_click=hit("off")),
            ui.Button("y", key="on", on_click=hit("on")),
            ui.Select(key="sel", options=["a"], value=None, on_change=hit("sel")),
        )

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        mount = recv(ws)
        # An explicit value=None is on the wire as null; an unset None prop is absent.
        assert mount["nodes"]["root/sel"]["props"]["value"] is None
        assert "default" not in mount["nodes"]["root/sel"]["props"]
        assert "tooltip" not in mount["nodes"]["root/on"]["props"]
        send(ws, {"type": "event", "node": "root/off", "name": "click"})
        send(ws, {"type": "event", "node": "root/ghost", "name": "click"})
        send(ws, {"type": "event", "node": "root/on", "name": "click"})
        send(ws, {"type": "event", "node": "root/sel", "name": "change", "payload": "a"})
        ws.send_bytes(b"\x00binary frame")
        send(ws, {"type": "event", "node": "root/on", "name": "click"})
        # Only the live, enabled nodes ran (each toasts); the binary frame did not end the loop.
        toasts = [recv(ws)["args"]["message"] for _ in range(3)]
        assert toasts == ["on", "sel", "on"] and hits == ["on", "a", "on"]


def test_navigate_keeps_the_session(tmp_path: Path) -> None:
    app = mw.App("n", public=None, bundle_dir=tmp_path)

    @app.page("/", title="Home")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Link(key="go", label="go", href="/other/7"))

    @app.page("/other/{n:int}", title="Other")
    def other(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(f"n={s.params['n']}", key="t"))

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        info = hello(ws)
        assert recv(ws)["title"] == "Home"
        send(ws, {"type": "navigate", "path": "/other/7"})
        cmd = recv(ws)
        assert cmd == {
            "type": "command",
            "name": "navigate",
            "args": {"path": "/other/7", "title": "Other"},
        }
        mount = recv(ws)
        assert mount["title"] == "Other" and mount["nodes"]["root/t"]["props"]["content"] == "n=7"
        assert app.sessions[info["id"]].path == "/other/7"
        send(ws, {"type": "navigate", "path": "/nowhere"})
        assert recv(ws)["args"] == {"path": "/nowhere", "title": "Page not found"}
        assert "There is nothing at /nowhere." in texts(recv(ws))
        assert app.sessions[info["id"]].path == "/nowhere"


def test_origin_check_and_boot_escaping(tmp_path: Path) -> None:
    app = mw.App("o", public=None, bundle_dir=tmp_path)

    @app.page("/docs/{rest:path}")
    def docs(s: mw.Session) -> ui.Component:
        return ui.Page()

    with TestClient(app.asgi) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/_mw/ws", headers={"origin": "https://evil.example", "host": "app.local"}
            ):
                pass
        with client.websocket_connect(
            "/_mw/ws", headers={"origin": "http://app.local", "host": "app.local"}
        ) as ws:
            hello(ws, path="/docs/x")
    # The HTML shell needs a bundle; the escaping is a pure function.
    from millwork.shell import _script_safe

    assert "</script>" not in _script_safe(
        json.dumps({"path": "/docs/</script><script>alert(1)</script>"})
    )


def texts(mount: dict[str, Any]) -> list[str]:
    """Every Text node's content in a mount message."""
    return [n["props"]["content"] for n in mount["nodes"].values() if n["type"] == "Text"]


def closed_with(ws: Any) -> int:
    """The close code the server ended the socket with."""
    with pytest.raises(WebSocketDisconnect) as info:
        ws.receive_text()
    return info.value.code


def test_the_first_frame_must_be_a_hello(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            send(ws, {"type": "event", "node": "root/inc", "name": "click"})
            assert recv(ws) == {"type": "error", "message": "expected hello", "fatal": True}
            assert closed_with(ws) == 4400
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text("{not json")
            assert closed_with(ws) == 4400
        with client.websocket_connect("/_mw/ws") as ws:
            send(ws, {"type": "hello"})  # no path
            assert closed_with(ws) == 4400
        assert app.sessions == {}


def test_bad_frames_after_hello_are_skipped(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        recv(ws)
        ws.send_text("{not json")
        ws.send_text(json.dumps({"seq": 1, "msg": {"type": "bogus"}}))
        ws.send_text(json.dumps({"seq": 1, "msg": {"type": "event", "name": "click"}}))
        ws.send_text(json.dumps({"msg": {"type": "event", "node": "root/inc", "name": "click"}}))
        send(ws, {"type": "answer", "request": "nope", "payload": 1})
        send(ws, {"type": "event", "node": "root/inc", "name": "click", "payload": {"x": [1]}})
        # Only the last one was a message the session could act on.
        assert recv(ws)["ops"] == [{"op": "set", "id": "root/count", "props": {"content": "1"}}]


def test_events_run_one_at_a_time_in_order_while_the_socket_keeps_reading(
    tmp_path: Path,
) -> None:

    app = mw.App("q", state=State, public=None, bundle_dir=tmp_path)
    order: list[str] = []

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("slow", key="slow", on_click=slow),
            ui.Button("fast", key="fast", on_click=fast),
        )

    async def slow(s: mw.Session[State], _: Any) -> None:
        order.append("slow in")
        # Waiting on the user releases the lock; the answer must arrive over the
        # same socket, which only works if the endpoint never waits on a handler.
        order.append(f"slow out {await s.confirm('Go?')}")
        s.toast("slow")

    async def fast(s: mw.Session[State], _: Any) -> None:
        order.append("fast")
        s.toast("fast")

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        recv(ws)
        send(ws, {"type": "event", "node": "root/slow", "name": "click"})
        dialog = recv(ws)
        ok = next(
            op["node"]["id"]
            for op in dialog["ops"]
            if op["op"] == "add" and op["node"]["id"].endswith("/ok")
        )
        send(ws, {"type": "event", "node": "root/fast", "name": "click"})
        assert recv(ws)["args"]["message"] == "fast"
        send(ws, {"type": "event", "node": ok, "name": "click"})
        seen = [recv(ws) for _ in range(2)]
        assert [m["type"] for m in seen] == ["command", "patch"]  # the toast, the dialog gone
        assert seen[0]["args"]["message"] == "slow"
        assert order == ["slow in", "fast", "slow out True"]


def test_connect_failures_land_on_the_error_page_or_end_the_socket(tmp_path: Path) -> None:
    from millwork.auth import NotFound

    app = mw.App("c", public=None, bundle_dir=tmp_path)

    @app.page("/item/{n}")
    def item(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.params["n"], key="t"))

    @item.connect
    async def load(s: mw.Session, n: str) -> None:
        if n == "missing":
            raise NotFound("No such item.")
        if n == "broken":
            raise RuntimeError("db down")

    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            send(ws, {"type": "hello", "path": "/item/broken"})
            # The tab hears which session it has, and then that its page failed.
            assert recv(ws)["type"] == "session"
            assert recv(ws)["message"] == "The page failed to start."
            assert closed_with(ws) == 4500
        # A crashed connect left no session behind.
        assert app.sessions == {}
        with client.websocket_connect("/_mw/ws") as ws:
            # NotFound from connect: the session opens on the not-found page, with
            # the message, under the path that was asked for.
            info = hello(ws, "/item/missing")
            assert "No such item." in texts(recv(ws))
            session = app.sessions[info["id"]]
            assert session.path == "/item/missing" and session.page is app.error_pages["not_found"]
        # A good session navigates into a crash and keeps its page, and into a
        # NotFound and lands on the error page.
        with client.websocket_connect("/_mw/ws") as ws:
            info = hello(ws, "/item/ok")
            recv(ws)
            send(ws, {"type": "navigate", "path": "/item/broken"})
            assert recv(ws) == {
                "type": "error",
                "message": "The page failed to start.",
                "fatal": False,
            }
            assert app.sessions[info["id"]].path == "/item/ok"
            send(ws, {"type": "navigate", "path": "/item/missing"})
            assert recv(ws)["args"]["title"] == "Page not found"
            assert "No such item." in texts(recv(ws))
            assert app.sessions[info["id"]].path == "/item/missing"


def test_resume_of_a_closed_session_starts_a_fresh_one(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            info = hello(ws)
            recv(ws)
        session = app.sessions[info["id"]]
        client.portal.call(session.dismiss)
        with client.websocket_connect("/_mw/ws") as ws:
            info2 = hello(ws, session=info["id"], resume=info["resume"], seq=1)
            assert info2["id"] != info["id"] and recv(ws)["type"] == "mount"


async def test_a_toast_action_runs_its_handler_once(tmp_path: Path) -> None:
    from millwork.protocol import Event
    from millwork.testing import TestApp

    class S(BaseModel):
        undone: int = 0

    app = mw.App("t", state=S, public=None, bundle_dir=tmp_path)

    async def undo(s: mw.Session[S], _: Any) -> None:
        s.state.undone += 1

    async def delete(s: mw.Session[S], _: Any) -> None:
        s.toast("Deleted.", action=("Undo", undo))

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        return ui.Page(
            ui.Button("Delete", key="del", on_click=delete),
            ui.Text(str(s.state.undone), key="n"),
        )

    async with TestApp(app).open("/") as page:
        await page.click("del")
        cmd = page.commands[-1]
        assert cmd.name == "toast" and cmd.args["action"]["label"] == "Undo"
        token = cmd.args["action"]["id"]
        page.session.event(Event(node=f"toast:{token}", name="action"))
        await page.settle()
        assert page.state.undone == 1
        page.session.event(Event(node=f"toast:{token}", name="action"))
        await page.settle()
        assert page.state.undone == 1


def test_new_props_reach_the_wire() -> None:
    from millwork.nodes import build

    alert = ui.Alert(title="Gone", actions=[ui.Button("Undo", key="u"), ui.Button("Close")])
    nodes = build(alert).nodes
    assert nodes["root"].props["actions"] == [
        {"$node": "root/@actions.u"},
        {"$node": "root/@actions.1"},
    ]
    inp = build(ui.Input(prefix_icon="search", suffix="km")).nodes["root"].props
    assert inp["prefix_icon"] == "search" and inp["suffix"] == "km"
    marks = build(ui.Slider(marks=[0, 50])).nodes["root"].props["marks"]
    assert marks == [{"value": 0, "label": None}, {"value": 50, "label": None}]
    import datetime as dt

    picker = build(
        ui.DatePicker(value=[dt.date(2026, 1, 2), None], min=dt.date(2025, 1, 1), range=True)
    )
    assert picker.nodes["root"].props["value"] == ["2026-01-02", None]
    assert picker.nodes["root"].props["min"] == "2025-01-01"
    menu = build(
        ui.DropdownMenu(
            trigger=ui.Button("More", key="t"),
            items=[ui.MenuItem(id="a", label="A")],
            on_select=lambda s, v: None,
        )
    )
    assert menu.nodes["root"].props["trigger"] == {"$node": "root/@trigger"}
    assert menu.nodes["root/@trigger"].props["label"] == "More"
    assert menu.handlers[("root", "select")] is not None
    multi = build(ui.MultiSelect(options=["a", "b"], default=["a"], max=1)).nodes["root"].props
    assert multi["default"] == ["a"] and multi["max"] == 1 and "value" not in multi
    assert multi["sortable"] is False
    sortable = build(ui.MultiSelect(options=["a"], sortable=True)).nodes["root"].props
    assert sortable["sortable"] is True
    field = build(ui.Field(ui.Input(key="i"), label="Name", required=True, error="Needed"))
    assert field.nodes["root"].props["error"] == "Needed" and field.nodes["root"].children == [
        "root/i"
    ]


async def test_a_request_reaches_on_search_and_replies_without_a_render(tmp_path: Path) -> None:
    from millwork.protocol import Reply, Request
    from millwork.testing import TestApp

    class S(BaseModel):
        picked: str | None = None

    app = mw.App("t", state=S, public=None, bundle_dir=tmp_path)
    people = [("a1", "Ada"), ("b1", "Bob")]

    async def search(s: mw.Session[S], q: str) -> list[tuple[str, str]]:
        return [p for p in people if q.lower() in p[1].lower()]

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        return ui.Page(
            ui.Combobox(
                key="who",
                on_search=search,
                on_change=lambda s, v: setattr(s.state, "picked", v),
            ),
            ui.Combobox(key="off", options=["x"], disabled=True, on_search=search),
        )

    async with TestApp(app).open("/") as page:
        node = page.find("who").id
        before = len(page.messages)
        s, conn = page.session, page.session.conn
        s.request(conn, Request(node=node, name="search", request="r1", payload="ad"), None)
        await page.settle()
        reply = page.messages[-1]
        assert isinstance(reply, Reply) and reply.request == "r1"
        assert reply.payload == [{"value": "a1", "label": "Ada"}]
        assert len(page.messages) == before + 1  # no patch: a query does not render
        s.request(conn, Request(node="root/nope", name="search", request="r2"), None)
        await page.settle()
        assert page.messages[-1] == Reply(request="r2", error="unknown request")
        s.request(conn, Request(node=page.find("off").id, name="search", request="r3"), None)
        await page.settle()
        assert page.messages[-1] == Reply(request="r3", error="unknown request")
        await page.change("who", "a1")
        assert page.state.picked == "a1"


def test_health_assets_and_the_thread_pool_are_deployment_ready(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "main-abcd1234.js").write_text("// hashed")
    (dist / "icons.svg").write_text("<svg/>")
    app = mw.App("h", public=None, bundle_dir=dist, threads=3)
    seen: dict[str, Any] = {}

    @app.on_startup
    async def warm() -> None:
        loop = asyncio.get_running_loop()
        seen["workers"] = loop._default_executor._max_workers  # type: ignore[union-attr]

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("hi"))

    client = TestClient(app.asgi)
    # Before the lifespan ran, the app is not ready.
    assert app.ready is False
    with client:
        assert client.get("/_mw/health").status_code == 200
        assert client.get("/_mw/health").json()["ok"] is True
        assert isinstance(seen["workers"], int) and seen["workers"] == 3
        hashed = client.get("/_mw/assets/main-abcd1234.js")
        assert hashed.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert client.get("/_mw/assets/icons.svg").headers["cache-control"] == "no-cache"
    assert app.ready is False


async def test_more_files_than_allowed_are_dropped_and_work_signals_activity(
    tmp_path: Path,
) -> None:
    from millwork.protocol import Event
    from millwork.testing import TestApp

    class S(BaseModel):
        got: int = 0
        run: Any = None

    app = mw.App("m", state=S, public=None, bundle_dir=tmp_path, files=mw.Files(tmp_path))

    async def uploaded(s: mw.Session[S], refs: list[mw.FileRef]) -> None:
        s.state.got = len(refs)

    gate = asyncio.Event()

    async def start(s: mw.Session[S], _: Any) -> None:
        s.state.run = s.task(gate.wait)

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        return ui.Page(
            ui.FileUpload(key="up", multiple=True, max_files=2, on_upload=uploaded),
            ui.FileUpload(key="one", on_upload=uploaded),
            ui.Chat(key="chat", attachments=ui.Accept(max_files=1), on_message=lambda s, t: None),
            ui.Button("go", key="go", on_click=start),
        )

    async with TestApp(app).open("/") as page:
        s = page.session
        refs = []
        for i, node in enumerate(("up", "up", "up", "one", "one", "chat", "chat")):
            ref = app.files.store(s, f"f{i}.txt", [b"x"], node=page.find(node).id)
            refs.append(ref.model_dump(mode="json"))
        await page.event("up", "upload", refs[:3])
        assert page.state.got == 2
        await page.event("one", "upload", refs[3:5])
        assert page.state.got == 1
        await page.event("chat", "message", {"text": "", "files": refs[5:7]})
        assert len(s.chat("chat").messages[0].parts) == 1
        # Starting a task tells the tab the session is busy; its end says so too.
        # The task is held open on a gate, so the first render is forced while it
        # runs rather than raced against the coalesced render timer.
        s.event(Event(node=page.find("go").id, name="click"))
        for _ in range(5):
            await asyncio.sleep(0)
        assert page.state.run.status == "running"
        s.flush()
        for _ in range(5):
            await asyncio.sleep(0)
        activity = [c.args["busy"] for c in page.commands if c.name == "activity"]
        assert activity == [True]
        gate.set()
        await page.settle()
        activity = [c.args["busy"] for c in page.commands if c.name == "activity"]
        assert activity == [True, False]


async def test_a_gated_page_needs_a_user_in_tests(tmp_path: Path) -> None:
    from millwork import auth
    from millwork.testing import TestApp

    app = mw.App(
        "g",
        public=None,
        bundle_dir=tmp_path,
        secret="x" * 32,
        auth=auth.Auth([auth.Password(lambda u, p: p == "b")]),
    )

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.user.name if s.user else "nobody", key="t"))

    @app.page("/open", public=True)
    def landing(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("open"))

    with pytest.raises(mw.Forbidden):
        async with TestApp(app).open("/"):
            pass
    async with TestApp(app).open("/open") as page:
        assert "open" in page.text()
    async with TestApp(app).open("/", user=auth.User(id="a", name="Ada")) as page:
        assert "Ada" in page.text()


async def test_development_warnings_name_the_four_mistakes(tmp_path: Path) -> None:
    import time

    from millwork.testing import TestApp

    class S(BaseModel):
        n: int = 0
        rows: list[str] = ["a", "b", "c", "d"]

    app = mw.App("w", state=S, public=None, bundle_dir=tmp_path, debug=True)

    def from_thread() -> None:
        s = mw.session()
        s.state.n = 99  # the mistake: state changed from the worker thread

    async def nothing(s: mw.Session[S], _: Any) -> None:
        pass

    async def start(s: mw.Session[S], _: Any) -> None:
        s.task(from_thread, label="worker")

    async def add_row(s: mw.Session[S], _: Any) -> None:
        s.state.rows.append("e")

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        time.sleep(0.03)  # the mistake: a page function that waits
        return ui.Page(
            ui.Stack(*(ui.Text(r) for r in s.state.rows), key="list"),  # keyless rows
            ui.Button("noop", key="noop", on_click=nothing),
            ui.Button("start", key="start", on_click=start),
            ui.Button("add", key="add", on_click=add_row),
        )

    async with TestApp(app).open("/") as page:
        warnings = lambda: [  # noqa: E731
            c.args["message"]
            for c in page.commands
            if c.name == "toast" and c.args.get("title") == "millwork"
        ]
        # One slow build is a hiccup; the second in a row is the page's fault.
        assert not any("page function took" in w for w in warnings())
        assert not any("without keys" in w for w in warnings())  # a static list is fine
        await page.click("add")
        assert any("page function took" in w for w in warnings())
        assert any("without keys" in w for w in warnings())  # one that changed length is not
        await page.click("noop")
        assert any("changed nothing" in w for w in warnings())
        await page.click("start")
        await page.settle()
        assert any("from its thread" in w for w in warnings())
        # Each warning is said once per session.
        await page.click("noop")
        assert sum("changed nothing" in w for w in warnings()) == 1


async def test_a_changed_custom_component_is_pushed_to_open_tabs(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    comps = tmp_path / "components"
    comps.mkdir()
    (comps / "Hello.jsx").write_text("export default () => null;")
    app = mw.App("c", public=None, bundle_dir=tmp_path, components=comps, debug=True)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Custom("Hello"))

    async with TestApp(app).open("/") as page:
        assert await app.check_components() == ["Hello"]  # the first look sees every file
        assert await app.check_components() == []
        (comps / "Hello.jsx").write_text("export default () => 'changed';")
        import os

        os.utime(comps / "Hello.jsx", (1, 1))  # a distinct mtime whatever the clock does
        assert await app.check_components() == ["Hello"]
        await page.settle()
        reloads = [c for c in page.commands if c.name == "reload_component"]
        assert reloads and reloads[-1].args["name"] == "Hello"
        # The new source has a new version, so the tab fetches it under a new URL.
        version = reloads[-1].args["version"]
        assert version == app.component_versions["Hello"] and len(version) == 16


async def test_the_replay_window_is_bounded_in_bytes(tmp_path: Path) -> None:
    from millwork.outbox import GAP, OUTBOX_KEEP_BYTES
    from millwork.testing import TestApp

    app = mw.App("outbox", public=None, bundle_dir=tmp_path)

    class S(BaseModel):
        n: int = 0

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        return ui.Page(
            ui.Text("x" * 300_000 + str(s.state.n), key="big"),
            ui.Button(
                "More", key="more", on_click=lambda s, _: setattr(s.state, "n", s.state.n + 1)
            ),
        )

    async with TestApp(app).open("/", state=S()) as page:
        for _ in range(30):
            await page.click("more")
        outbox = page.session.outbox
        held = sum(len(t) for _, t in outbox._items)
        assert held <= OUTBOX_KEEP_BYTES and len(outbox._items) < 30
        assert outbox._bytes == held
        # The newest message is always kept, so a tab one step behind still replays.
        assert outbox.after(outbox.seq - 1) is not GAP
        assert outbox.after(1) is GAP


def test_the_tree_page_title_names_the_tab(tmp_path: Path) -> None:
    app = mw.App("t", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/", title="App")
    def home(s: mw.Session[State]) -> ui.Component:
        title = f"Count {s.state.count}" if s.state.count else None
        return ui.Page(ui.Button("+", key="inc", on_click=inc), title=title)

    async def inc(s: mw.Session[State], _: Any) -> None:
        s.state.count += 1

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        assert recv(ws)["title"] == "App"
        send(ws, {"type": "event", "node": "root/inc", "name": "click"})
        msgs = [recv(ws) for _ in range(2)]
        assert {"type": "command", "name": "title", "args": {"title": "Count 1"}} in msgs


def test_state_stays_across_pages_and_a_page_closes_on_leaving(tmp_path: Path) -> None:
    app = mw.App("keep", state=State, public=None, bundle_dir=tmp_path)
    left: list[str] = []

    @app.page("/", title="Home")
    def home(s: mw.Session[State]) -> ui.Component:
        s.state.count += 1
        return ui.Page(ui.Text(f"count={s.state.count}", key="t"))

    @home.close
    def leave_home(s: mw.Session[State]) -> None:
        left.append(f"home at {s.state.count}")

    @app.page("/other", title="Other")
    def other(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text(f"still {s.state.count}", key="t"))

    @other.close
    def leave_other(s: mw.Session[State]) -> None:
        left.append("other")

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        assert recv(ws)["nodes"]["root/t"]["props"]["content"] == "count=1"
        send(ws, {"type": "navigate", "path": "/other"})
        recv(ws)  # the navigate command
        assert recv(ws)["nodes"]["root/t"]["props"]["content"] == "still 1"
        assert left == ["home at 1"]
    assert left == ["home at 1", "other"]


def test_pages_close_before_the_shutdown_hooks_run(tmp_path: Path) -> None:
    """A close hook releases what the page took, and may need what a shutdown
    hook takes away, so the sessions end first."""
    app = make_app(tmp_path)
    order: list[str] = []
    app.pages[0].close(lambda s: order.append("page closed"))
    app.on_shutdown(lambda: order.append("shutdown hook"))
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        recv(ws)
    assert order == ["page closed", "shutdown hook"]


async def test_a_literal_path_wins_over_a_parameter_in_either_order(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    # Parameters first and the exact pages after them, the order a file is
    # often written in and the one where the first match is the wrong page.
    paths = {
        "/orders/{order_id}": "one order",
        "/orders/new": "a new order",
        "/orders/{order_id}/lines/{line}": "a line",
        "/orders/{order_id}/lines/all": "all lines",
        "/files/{rest:path}": "any file",
        "/files/{name}": "one file",
        "/files/{name}/versions": "its versions",
        "/files/{rest:path}/edit": "edit any file",
        "/items/{slug}": "an item by name",
        "/items/{item_id:int}": "an item by number",
        "/v{n}/about": "about a version",
        "/{tenant}/about": "about a tenant",
    }
    expected = (
        ("/orders/new", "a new order", {}),
        ("/orders/7", "one order", {"order_id": "7"}),
        ("/orders/7/lines/all", "all lines", {"order_id": "7"}),
        ("/orders/7/lines/3", "a line", {"order_id": "7", "line": "3"}),
        ("/files/a", "one file", {"name": "a"}),
        ("/files/a/versions", "its versions", {"name": "a"}),
        ("/files/a/b/c", "any file", {"rest": "a/b/c"}),
        # A page that goes on after the rest of the path is more exact than
        # the one that stops there.
        ("/files/a/b/edit", "edit any file", {"rest": "a/b"}),
        # A converter narrows a parameter, and so does text around it.
        ("/items/12", "an item by number", {"item_id": 12}),
        ("/items/twelve", "an item by name", {"slug": "twelve"}),
        ("/v2/about", "about a version", {"n": "2"}),
        ("/acme/about", "about a tenant", {"tenant": "acme"}),
    )
    for order in (list(paths), list(reversed(paths))):
        app = mw.App("r", public=None, bundle_dir=tmp_path)
        for path in order:
            name = paths[path]
            app.page(path)(lambda s, name=name: ui.Page(ui.Text(name, key="t")))
        for path, page_name, params in expected:
            async with TestApp(app).open(path) as page:
                assert page.find("t").props["content"] == page_name, (path, order[0])
                assert page.session.params == params, path
        assert app.resolve("/nothing/here/at/all") is None

    # Equally exact: the first one added stays the page.
    app = mw.App("t", public=None, bundle_dir=tmp_path)
    app.page("/tie/{a}")(lambda s: ui.Page(ui.Text("first", key="t")))
    app.page("/tie/{b}")(lambda s: ui.Page(ui.Text("second", key="t")))
    async with TestApp(app).open("/tie/x") as page:
        assert page.find("t").props["content"] == "first"
