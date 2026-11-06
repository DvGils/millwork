"""Who may open what: rules on pages, routes and mounts, asked at every way
in, and a user kept current by ``Auth(recheck=)``."""

import asyncio
import datetime as dt
import importlib
import json
import time
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

import millwork as mw
from millwork import auth, ui
from millwork.access import ALLOWED, REFUSED, Forbidden, ask, rule_for
from millwork.cli import main
from millwork.session import Session
from millwork.testing import TestApp


def is_admin(user: auth.User) -> bool:
    return user.claims.get("role") == "admin"


def owns(user: auth.User, owner: str) -> bool:
    return user.id == owner or is_admin(user)


class World:
    """What the app's own data says about people, changed by a test mid-flight."""

    def __init__(self) -> None:
        self.roles = {"ada": "admin", "cy": "candidate"}
        self.asked: list[str] = []
        self.connected: list[str] = []
        self.acted: list[str] = []
        self.closed: list[str] = []
        self.broken = False
        # How long the app's recheck takes to answer, in seconds.
        self.slow = 0.0
        # How long the slow page's connect hook takes, in seconds.
        self.connecting = 0.0


def make_app(
    tmp_path: Path,
    world: World,
    *,
    recheck: bool = False,
    providers: list[Any] | None = None,
    **kw: Any,
) -> mw.App:
    def admit(identity: auth.Identity) -> auth.User | None:
        role = world.roles.get(identity.subject)
        return auth.User(id=identity.subject, name=identity.subject, claims={"role": role})

    def current(user: auth.User) -> auth.User | None:
        world.asked.append(user.id)
        if world.slow:
            time.sleep(world.slow)
        if world.broken:
            raise RuntimeError("no database")
        role = world.roles.get(user.id)
        return user.model_copy(update={"claims": {"role": role}}) if role else None

    app = mw.App(
        "a",
        public=None,
        bundle_dir=tmp_path,
        secret="s3cret-s3cret-s3cret-s3cret-s3cret",
        auth=auth.Auth(
            providers or [auth.Password(lambda u, p: p == "pw")],
            on_login=admit,
            recheck=current if recheck else None,
            recheck_every=dt.timedelta(seconds=0.05),
        ),
        **kw,
    )

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Text(f"home of {s.user.id}, {s.user.claims['role']}", key="t"),
            ui.Text("admin link", key="link") if s.can("/admin") else None,
            ui.Button("poke", key="poke", on_click=lambda s, _: s.toast("poked")),
            # Drawn for an admin only: a handler nobody else is given.
            ui.Button("wipe", key="wipe", on_click=wipe) if s.can("/admin") else None,
        )

    def wipe(s: mw.Session, _: Any) -> None:
        world.acted.append(f"{s.user.id} wiped as {s.user.claims['role']}")

    @app.page("/admin", allow=is_admin)
    def admin(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Text("the admin page", key="t"),
            ui.Button("act", key="act", on_click=act),
        )

    def act(s: mw.Session, _: Any) -> None:
        world.acted.append(f"{s.user.id} acted")
        s.toast("acted")

    @admin.connect
    def opened(s: mw.Session) -> None:
        world.connected.append(s.user.id)

    @admin.close
    async def left(s: mw.Session) -> None:
        await asyncio.sleep(0)
        world.closed.append(s.user.id)

    @app.page("/desk/{owner}", allow=owns)
    def desk(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(f"desk of {s.params['owner']}", key="t"))

    @app.page("/welcome", public=True)
    def welcome(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("welcome", key="t"))

    @app.page("/slow")
    def slow(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("the slow page", key="t"))

    @slow.connect
    async def slowly(s: mw.Session) -> None:
        await asyncio.sleep(world.connecting)
        world.connected.append(f"{s.user.id} slowly")
        # Work the page starts as it opens, which has to end with the session.
        s.task(asyncio.sleep(30), label="poll")

    @slow.close
    def slow_left(s: mw.Session) -> None:
        world.closed.append(f"{s.user.id} from the slow page")

    async def who(request: Request) -> PlainTextResponse:
        return PlainTextResponse(f"for {request.state.user.id}")

    def plain(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def feed(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(f"feed for {ws.state.user.id}")
        await ws.close()

    inner = Starlette(routes=[Route("/report", who), WebSocketRoute("/feed", feed)])
    app.route("/api/export", who, allow=is_admin)
    app.route("/api/mine", who)
    app.route("/api/save", who, methods=["POST"])
    app.route("/api/desk/{owner}", who, allow=owns)
    app.route("/hooks/ping", plain, methods=["GET", "POST"], public=True)
    app.mount("/tools", inner, allow=is_admin)
    app.mount("/open", Starlette(routes=[Route("/x", plain)]), public=True)
    return app


def sign_in(client: TestClient, who: str) -> None:
    client.cookies.clear()
    r = client.post("/_mw/auth/login", json={"username": who, "password": "pw"})
    assert r.status_code == 200, r.text


def opened(ws: Any, path: str = "/", resume: dict[str, Any] | None = None) -> dict[str, Any]:
    """Say hello on a socket and return the session info with what the page shows."""
    hello = {"type": "hello", "path": path, **(resume or {})}
    ws.send_text(json.dumps({"seq": 1, "msg": hello}))
    info = json.loads(ws.receive_text())["msg"]
    assert info["type"] == "session", info
    mount = json.loads(ws.receive_text())["msg"]
    info["shows"] = [
        n["props"]["content"] for n in mount["nodes"].values() if "content" in n["props"]
    ]
    info["nodes"] = set(mount["nodes"])
    return info


def click(ws: Any, node: str, seq: int = 2) -> None:
    ws.send_text(json.dumps({"seq": seq, "msg": {"type": "event", "node": node, "name": "click"}}))


def until(ws: Any, wanted: Any) -> dict[str, Any]:
    while True:
        msg = json.loads(ws.receive_text())["msg"]
        if wanted(msg):
            return msg


# ------------------------------------------------------------------ rules


def test_a_rule_is_checked_when_it_is_declared(tmp_path: Path) -> None:
    app = make_app(tmp_path, World())

    async def later(user: auth.User) -> bool:
        return True

    class Asks:
        async def __call__(self, user: auth.User) -> bool:
            return True

    for bad, said in (
        (later, "is async"),
        (Asks(), "is async"),
        ("admin", "takes a function of the user"),
        (lambda: True, "takes the user as its first argument"),
        (lambda user, project: True, "asks for 'project', which is not a parameter"),
    ):
        with pytest.raises(TypeError, match=said):
            app.page("/x/{owner}", allow=bad)(lambda s: ui.Page())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="asks for 'owner'"):
        app.mount("/m", Starlette(), allow=owns)
    with pytest.raises(ValueError, match="is public and has a rule"):
        app.page("/p", public=True, allow=is_admin)
    with pytest.raises(ValueError, match="is public and has a rule"):
        app.route("/r", lambda r: None, public=True, allow=is_admin)
    plain = mw.App("n", public=None, bundle_dir=tmp_path)
    with pytest.raises(ValueError, match="the app has no auth"):
        plain.page("/p", allow=is_admin)
    # A parameter with a default, and one that takes them all, are fine.
    app.page("/y/{owner}", allow=lambda user, owner="", **rest: True)(lambda s: ui.Page())


def test_only_true_lets_someone_in(caplog: pytest.LogCaptureFixture) -> None:
    ada = auth.User(id="ada", name="Ada", claims={"role": "admin"})

    def named(user: auth.User) -> Any:
        return user.claims.get("role")  # truthy for any role, and not an answer

    def broken(user: auth.User) -> bool:
        raise KeyError("role")

    def refuses(user: auth.User) -> bool:
        raise Forbidden("Admins only.")

    def rule(fn: Any) -> Any:
        return rule_for(fn, ["owner"], "the page /x")

    assert ask(None, ada, {}, "x") == ALLOWED
    assert ask(rule(is_admin), ada, {}, "x") == ALLOWED
    assert ask(rule(lambda user: False), ada, {}, "x") == REFUSED
    assert ask(rule(owns), ada.model_copy(update={"claims": {}}), {"owner": "bo"}, "x") == REFUSED
    assert ask(rule(owns), ada, {"owner": "bo", "extra": "1"}, "x") == ALLOWED
    said = ask(rule(refuses), ada, {}, "x")
    assert (said.ok, said.message) == (False, "Admins only.")
    for wrong, logged in ((named, "answered 'str'"), (broken, "failed; access refused")):
        caplog.clear()
        assert ask(rule(wrong), ada, {}, "the page /x") == REFUSED
        assert logged in caplog.text


# ------------------------------------------------------------------ pages


def test_a_page_asks_its_rule_at_every_way_in(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world)
    with TestClient(app.asgi) as client:
        sign_in(client, "cy")
        # The page load says 403, and the socket lands on the forbidden page
        # without the guarded page's connect hook ever running.
        assert client.get("/admin", follow_redirects=False).status_code == 403
        assert client.get("/", follow_redirects=False).status_code == 503  # served, no bundle
        with client.websocket_connect("/_mw/ws") as ws:
            info = opened(ws, "/admin")
            assert "No access" in info["shows"] and "the admin page" not in info["shows"]
            # An event for the guarded page's button finds nothing to run: the
            # next thing the session does is answer a click it does know.
            click(ws, "root/act")
            assert "root/act" not in info["nodes"]
        assert world.connected == [] and world.acted == []
        # Navigation on an open session asks too.
        with client.websocket_connect("/_mw/ws") as ws:
            assert opened(ws, "/")["shows"] == ["home of cy, candidate"]
            ws.send_text(json.dumps({"seq": 2, "msg": {"type": "navigate", "path": "/admin"}}))
            mount = until(ws, lambda m: m["type"] == "mount")
            shown = [n["props"].get("content") for n in mount["nodes"].values()]
            assert "No access" in shown and "the admin page" not in shown
        assert world.connected == []
        # A rule with the path's parameter, however the path is spelled.
        for path, own in (
            ("/desk/cy", True),
            ("/desk/cy?tab=2", True),
            ("/desk/%63y", True),
            ("/desk/ada", False),
            ("/desk/ada?owner=cy", False),
            ("/desk/cy%2F..%2Fada", False),
            ("/desk/%2563y", False),
        ):
            with client.websocket_connect("/_mw/ws") as ws:
                shows = opened(ws, path)["shows"]
                # In, or not: a path that decodes to something else finds no
                # desk at all, which is as closed as a refusal.
                assert (shows == ["desk of cy"]) is own, (path, shows)
                # The page load and the socket agree on every spelling.
                status = client.get(path, follow_redirects=False).status_code
                assert (status == 503) is own, (path, status)
                assert own or not any(str(x).startswith("desk of") for x in shows)
        sign_in(client, "ada")
        assert client.get("/admin", follow_redirects=False).status_code == 503
        with client.websocket_connect("/_mw/ws") as ws:
            assert opened(ws, "/admin")["shows"] == ["the admin page"]
            click(ws, "root/act")
            assert until(ws, lambda m: m.get("name") == "toast")["args"]["message"] == "acted"
        # The admin got in, and only then did connect and the handler run.
        assert world.connected == ["ada"] and world.acted == ["ada acted"]
        # A public page asks nobody, and a signed-out visitor is sent to sign in.
        client.cookies.clear()
        with client.websocket_connect("/_mw/ws") as ws:
            assert opened(ws, "/welcome")["shows"] == ["welcome"]
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code == 302 and "/_mw/login" in r.headers["location"]


async def test_the_harness_and_links_ask_the_same_rule(tmp_path: Path) -> None:
    app = make_app(tmp_path, World())
    cy = auth.User(id="cy", name="Cy", claims={"role": "candidate"})
    ada = auth.User(id="ada", name="Ada", claims={"role": "admin"})
    harness = TestApp(app)
    with pytest.raises(mw.Forbidden):
        async with harness.open("/admin", user=cy):
            pass
    async with harness.open("/admin", user=ada) as page:
        assert page.find("t").props["content"] == "the admin page"
    async with harness.open("/", user=cy) as page:
        assert not page.find_all("link")
        assert page.session.can("/desk/cy") and not page.session.can("/desk/ada")
        assert page.session.can("/welcome")
        with pytest.raises(LookupError, match="no page at /nowhere"):
            page.session.can("/nowhere")
        # Following a link there lands on the forbidden page, as in a tab.
        await page.navigate("/admin")
        assert "No access" in page.text() and "the admin page" not in page.text()
    async with harness.open("/", user=ada) as page:
        assert page.find_all("link") and page.session.can("/admin")


# ------------------------------------------------------------------ routes and mounts


def test_routes_and_mounts_are_closed_unless_marked_public(tmp_path: Path) -> None:
    app = make_app(tmp_path, World())
    with TestClient(app.asgi) as client:
        # Signed out: an API call is told so, a link followed in a browser is
        # sent to sign in and back, and what is marked public answers.
        for path in ("/api/mine", "/api/export", "/api/desk/cy", "/tools/report"):
            r = client.get(path)
            assert r.status_code == 401 and r.json() == {"reason": "Sign in to continue."}, path
        r = client.get("/api/mine", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/_mw/login?next=%2Fapi%2Fmine"
        assert client.post("/api/save").status_code == 401
        assert client.get("/hooks/ping").json() == {"ok": True}
        assert client.post("/hooks/ping").json() == {"ok": True}
        assert client.get("/open/x").json() == {"ok": True}

        sign_in(client, "cy")
        assert client.get("/api/mine").text == "for cy"
        assert client.get("/api/desk/cy").text == "for cy"
        for path in ("/api/export", "/api/desk/ada", "/tools/report"):
            r = client.get(path)
            assert r.status_code == 403 and r.json() == {"reason": "You may not open this page."}
        # A request that changes something comes from the app's own pages.
        assert client.post("/api/save").text == "for cy"
        assert client.post("/api/save", headers={"origin": "http://testserver"}).text == "for cy"
        r = client.post("/api/save", headers={"origin": "https://evil.example"})
        assert r.status_code == 403
        with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/tools/feed"):
            pass
        assert closed.value.code == 4403

        sign_in(client, "ada")
        assert client.get("/api/export").text == "for ada"
        assert client.get("/api/desk/cy").text == "for ada"
        assert client.get("/tools/report").text == "for ada"
        # A socket under a mount is behind the same door, and like a request
        # that changes something it has to come from the app's own pages.
        with client.websocket_connect("/tools/feed") as ws:
            assert ws.receive_text() == "feed for ada"
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            client.websocket_connect("/tools/feed", headers={"origin": "https://evil.example"}),
        ):
            pass
        assert closed.value.code == 4403
        client.cookies.clear()
        with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/tools/feed"):
            pass
        assert closed.value.code == 4401

    # Without auth there is nobody to ask about: routes are as they were.
    plain = mw.App("n", public=None, bundle_dir=tmp_path)
    plain.route("/api", lambda request: JSONResponse({"ok": True}))
    with TestClient(plain.asgi) as client:
        assert client.get("/api").json() == {"ok": True}


def test_the_listing_says_who_may_reach_what(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = make_app(tmp_path, World())
    assert app.access() == [
        ("page", "/", "signed in"),
        ("page", "/admin", "signed in and is_admin"),
        ("page", "/desk/{owner}", "signed in and owns"),
        ("page", "/welcome", "anyone"),
        ("page", "/slow", "signed in"),
        ("route", "/api/export", "signed in and is_admin"),
        ("route", "/api/mine", "signed in"),
        ("route", "/api/save", "signed in"),
        ("route", "/api/desk/{owner}", "signed in and owns"),
        ("route", "/hooks/ping", "anyone"),
        ("mount", "/tools", "signed in and is_admin"),
        ("mount", "/open", "anyone"),
    ]
    # What is served without asking anyone is on the list too.
    (tmp_path / "public").mkdir()
    (tmp_path / "components").mkdir()
    served = mw.App("s", public=tmp_path / "public", components=tmp_path / "components")
    assert served.access() == [
        ("files", "/public", "anyone (the app has no auth)"),
        ("files", "/_mw/components", "anyone (the app has no auth)"),
    ]
    (tmp_path / "listed.py").write_text(
        "import millwork as mw\n"
        "from millwork import ui\n"
        "app = mw.App('l', public=None)\n"
        "@app.page('/')\n"
        "def home(s): return ui.Page()\n"
    )
    assert main(["routes", str(tmp_path / "listed.py")]) == 0
    assert capsys.readouterr().out.split() == [
        "page",
        "/",
        "anyone",
        "(the",
        "app",
        "has",
        "no",
        "auth)",
    ]


# ------------------------------------------------------------------ recheck


def stale(app: mw.App) -> None:
    """Let every kept answer run out, as the interval passing would."""
    app.auth._answers.clear()
    app.auth._failed.clear()


def test_recheck_is_asked_once_per_interval_and_ends_a_sign_in(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        for _ in range(3):
            assert client.get("/api/export").text == "for ada"
            assert client.get("/admin", follow_redirects=False).status_code == 503
        # Six requests, one question: the answer is kept for the interval.
        assert world.asked == ["ada"]
        # Demoted in the app's data: the rule sees it once the interval is over.
        world.roles["ada"] = "candidate"
        assert client.get("/api/export").text == "for ada"
        stale(app)
        assert client.get("/api/export").status_code == 403
        assert client.get("/admin", follow_redirects=False).status_code == 403
        # Removed: no longer signed in. The login page says why and the cookie goes.
        del world.roles["ada"]
        stale(app)
        assert client.get("/api/mine").status_code == 401
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302 and "error=Access+denied." in r.headers["location"]
        assert "mw_auth=" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
            refused = json.loads(ws.receive_text())["msg"]
            assert refused["type"] == "error" and refused["fatal"] is True


def test_a_recheck_that_cannot_answer_is_neither_a_yes_nor_a_no(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        assert client.get("/api/export").text == "for ada"
        stale(app)
        world.broken = True
        # New access is refused while nothing is known, and the hook is left
        # alone for a moment rather than asked again by every request.
        asked = len(world.asked)
        for _ in range(3):
            with pytest.raises(auth.Unanswered):
                client.get("/api/export")
        assert len(world.asked) == asked + 1
        # Signing out works all the same: it asks nobody who the person is now.
        r = client.post("/_mw/auth/logout")
        assert r.status_code == 200 and "Max-Age=0" in r.headers["set-cookie"]
        world.broken = False
        stale(app)
        sign_in(client, "ada")
        assert client.get("/api/export").text == "for ada"


def test_a_session_belongs_to_the_user_it_started_with(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with (
            client.websocket_connect("/_mw/ws") as on_admin,
            client.websocket_connect("/_mw/ws") as on_home,
        ):
            guarded = opened(on_admin, "/admin")
            home = opened(on_home, "/")
            assert home["shows"] == ["home of ada, admin", "admin link"]
            assert "root/wipe" in home["nodes"]
            # Demoted. Each session ends and its tab is sent to load its page
            # anew, as the user they are now: the admin page will refuse, and
            # the home page will be drawn without what only an admin is given.
            world.roles["ada"] = "candidate"
            assert until(on_admin, lambda m: m.get("name") == "leave")["args"] == {"to": "/admin"}
            assert until(on_home, lambda m: m.get("name") == "leave")["args"] == {"to": "/"}
        assert guarded["id"] not in app.sessions and home["id"] not in app.sessions
        with client.websocket_connect("/_mw/ws") as ws:
            again = opened(ws, "/")
            assert (
                again["shows"] == ["home of ada, candidate"] and "root/wipe" not in again["nodes"]
            )
        with client.websocket_connect("/_mw/ws") as ws:
            assert "No access" in opened(ws, "/admin")["shows"]
        assert world.acted == []


def test_no_event_runs_ahead_of_the_answer(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as ws:
            opened(ws, "/admin")
            # Removed, and the answer is slow in coming. Clicks sent while it
            # is on its way wait for it, and none of them runs.
            del world.roles["ada"]
            world.slow = 0.3
            stale(app)
            asked = len(world.asked)
            for seq in range(2, 6):
                click(ws, "root/act", seq)
            assert until(ws, lambda m: m.get("name") == "leave")["args"]["to"].startswith(
                "/_mw/login"
            )
            assert len(world.asked) == asked + 1
        assert world.acted == [] and app.sessions == {}
        # Demoted rather than removed, on a page that still admits them: the
        # click that finds it out does not run on the page drawn for an admin.
        world.roles["ada"], world.slow = "admin", 0.0
        stale(app)
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as ws:
            assert "root/wipe" in opened(ws, "/")["nodes"]
            world.roles["ada"] = "candidate"
            stale(app)
            click(ws, "root/wipe")
            assert until(ws, lambda m: m.get("name") == "leave")["args"] == {"to": "/"}
        assert world.acted == []


def test_a_changed_user_does_not_get_their_old_session_back(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0

    def resume(first: dict[str, Any]) -> dict[str, Any]:
        return {"session": first["id"], "resume": first["resume"], "seq": 2}

    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as ws:
            first = opened(ws, "/")
            assert "root/wipe" in first["nodes"]
        # Unchanged: the same session comes back, with nothing to mount anew.
        with client.websocket_connect("/_mw/ws") as ws:
            hello = {"type": "hello", "path": "/", **resume(first)}
            ws.send_text(json.dumps({"seq": 1, "msg": hello}))
            assert json.loads(ws.receive_text())["msg"]["id"] == first["id"]
        # Demoted while the tab was away. The home page still admits them, and
        # the old session, drawn for an admin, is not handed back: a new one
        # is drawn for who they are, without the admin's button.
        world.roles["ada"] = "candidate"
        stale(app)
        with client.websocket_connect("/_mw/ws") as ws:
            again = opened(ws, "/", resume(first))
            assert again["id"] != first["id"] and "root/wipe" not in again["nodes"]
            assert again["shows"] == ["home of ada, candidate"]
            click(ws, "root/wipe")
            click(ws, "root/poke", 3)
            assert until(ws, lambda m: m.get("name") == "toast")["args"]["message"] == "poked"
        assert first["id"] not in app.sessions and world.acted == []


def test_a_rule_that_breaks_on_the_changed_user_refuses_them(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0

    # Written carelessly, the way a rule easily is: it raises, or answers
    # None, once the role is no longer there to read.
    @app.page("/raises", allow=lambda user: user.claims["level"] == "admin")
    def raises(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("raises", key="t"))

    @app.page("/none", allow=lambda user: user.claims.get("level") and True)
    def none(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("none", key="t"))

    def current(user: auth.User) -> auth.User | None:
        claims = {"level": "admin"} if world.roles.get(user.id) == "admin" else {}
        return user.model_copy(update={"claims": {"role": world.roles[user.id], **claims}})

    app.auth.recheck = current
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        firsts = {}
        for path in ("/raises", "/none"):
            with client.websocket_connect("/_mw/ws") as ws:
                firsts[path] = opened(ws, path)
                assert firsts[path]["shows"] == [path.strip("/")]
        world.roles["ada"] = "candidate"
        stale(app)
        for path, first in firsts.items():
            resume = {"session": first["id"], "resume": first["resume"], "seq": 2}
            with client.websocket_connect("/_mw/ws") as ws:
                again = opened(ws, path, resume)
                assert again["id"] != first["id"] and "No access" in again["shows"], path
            assert client.get(path, follow_redirects=False).status_code == 403


def test_an_open_session_outlasts_a_moment_without_an_answer_and_not_an_outage(
    tmp_path: Path,
) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 0.15
    app.auth._retry_after = 0.02
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as ws:
            opened(ws, "/")
            # The database is away. Within twice the interval of the last
            # answer the session goes on as it was.
            world.broken = True
            time.sleep(0.18)
            click(ws, "root/poke")
            assert until(ws, lambda m: m.get("name") == "toast")["args"]["message"] == "poked"
            # It stays away, and the session ends rather than run on an
            # answer that old. The sign-in is untouched: nobody said no.
            ended = until(ws, lambda m: m["type"] == "error")
            assert ended["fatal"] is True and ended["message"] == "Try again in a moment."
        assert app.sessions == {}
        world.broken = False
        stale(app)
        assert client.get("/api/mine").text == "for ada"


def test_a_proxys_user_is_put_to_recheck_like_any_other(tmp_path: Path) -> None:
    world = World()
    app = make_app(
        tmp_path, world, recheck=True, providers=[auth.Headers(user="X-User")], proxied=True
    )
    app.auth.recheck_every = 30.0
    headers = {"x-user": "ada"}
    with TestClient(app.asgi) as client:
        assert client.get("/api/export", headers=headers).text == "for ada"
        with client.websocket_connect("/_mw/ws", headers=headers) as ws:
            assert opened(ws, "/admin")["shows"] == ["the admin page"]
            # Removed in the app's data, while the proxy still vouches for
            # them: not signed in any more, on a page load, for a route and in
            # the tab that is open.
            del world.roles["ada"]
            stale(app)
            assert client.get("/api/export", headers=headers).status_code == 401
            r = client.get("/admin", headers=headers, follow_redirects=False)
            assert r.status_code == 302 and "/_mw/login" in r.headers["location"]
            click(ws, "root/act")
            assert until(ws, lambda m: m.get("name") == "leave")
        assert world.acted == [] and app.sessions == {}
        with client.websocket_connect("/_mw/ws", headers=headers) as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/admin"}}))
            assert json.loads(ws.receive_text())["msg"]["type"] == "error"


def test_a_refused_page_load_gives_away_nothing_of_the_page(tmp_path: Path) -> None:
    (tmp_path / ".vite").mkdir()
    (tmp_path / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "main-abc.js", "isEntry": True, "css": []}})
    )
    world = World()
    app = make_app(tmp_path, world)

    @app.page("/plans", title="Project Apollo: layoffs", allow=is_admin)
    def plans(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("plans", key="t"))

    with TestClient(app.asgi) as client:
        sign_in(client, "cy")
        r = client.get("/plans")
        assert r.status_code == 403 and "Apollo" not in r.text
        sign_in(client, "ada")
        r = client.get("/plans")
        assert r.status_code == 200 and "<title>Project Apollo: layoffs</title>" in r.text
        # The tab says hello with the path the page gave it, which is the
        # address as the browser spelled it: the load and the session read
        # one spelling the same way, however it is encoded.
        sign_in(client, "cy")
        for address, own in (("/desk/%63y", True), ("/desk/%2563y", False), ("/desk/c%79", True)):
            r = client.get(address)
            boot = json.loads(r.text.split("window.__mw = ")[1].split(";</script>")[0])
            assert boot["path"] == address and (r.status_code == 200) is own, address
            with client.websocket_connect("/_mw/ws") as ws:
                assert (opened(ws, boot["path"])["shows"] == ["desk of cy"]) is own, address


async def test_a_tab_that_does_not_listen_holds_nothing_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The module, which the package's ``session()`` function hides by name.
    monkeypatch.setattr(importlib.import_module("millwork.session"), "END_NOTICE_SECONDS", 0.05)
    world = World()
    app = make_app(tmp_path, world)
    ada = auth.User(id="ada", name="Ada", claims={"role": "admin"})
    harness = TestApp(app)
    async with harness.open("/admin", user=ada) as deaf, harness.open("/", user=ada) as fine:
        heard: list[str] = []

        async def never(text: str) -> None:
            await asyncio.Event().wait()

        async def hears(text: str) -> None:
            heard.append(json.loads(text)["msg"].get("name") or json.loads(text)["msg"]["type"])

        deaf.session._send, fine.session._send = never, hears
        deaf.session.sign_in = fine.session.sign_in = "one-sign-in"
        # The sign-in ends. Both sessions are over at once, before anything is
        # awaited, and the tab that listens is told while the other is not
        # listening.
        app.end_sign_in("one-sign-in", ada)
        assert deaf.session.closed and fine.session.closed and app.sessions == {}
        assert app.ending == {deaf.session, fine.session}
        await asyncio.sleep(0.02)
        assert heard == ["leave", "error"]
        # The deaf one is given its moment and then finished all the same:
        # its page is closed and nothing is left owing.
        await asyncio.sleep(0.1)
        assert world.closed == ["ada"] and app.ending == set() and app._ending == {}
        # Ending one on its own is the same: over first, and not kept waiting.
    async with harness.open("/", user=ada) as page:
        page.session._send = never
        started = time.monotonic()
        await page.session.end("gone")
        assert page.session.closed and time.monotonic() - started < 1.0


async def test_an_answer_about_one_user_is_no_answer_about_another(tmp_path: Path) -> None:
    asked: list[str] = []

    async def as_given(user: auth.User) -> auth.User | None:
        asked.append(user.claims["role"])
        await asyncio.sleep(0.05)
        return user

    a = auth.Auth([auth.Password(lambda u, p: True)], recheck=as_given)
    admin = auth.User(id="ada", name="Ada", claims={"role": "admin"})
    staff = auth.User(id="ada", name="Ada", claims={"role": "staff"})
    # Behind a proxy one person can be identified as two different users, and
    # each question gets its own answer, even while the other is in flight.
    answers = await asyncio.gather(
        a.current("user:ada", admin), a.current("user:ada", staff), a.current("user:ada", admin)
    )
    assert [u.claims["role"] for u in answers if u] == ["admin", "staff", "admin"]
    assert sorted(asked) == ["admin", "staff"]
    # Each answer is kept on its own, so the two taking turns ask no more.
    for user in (admin, staff) * 5:
        assert await a.current("user:ada", user) == user
    assert len(asked) == 2


def test_a_session_ends_when_the_proxy_says_its_person_is_someone_else(tmp_path: Path) -> None:
    world = World()

    def admit(identity: auth.Identity) -> auth.User | None:
        groups = identity.raw.get("groups", [])
        role = "admin" if "admins" in groups else "candidate"
        return auth.User(id=identity.subject, name=identity.subject, claims={"role": role})

    app = make_app(
        tmp_path,
        world,
        providers=[auth.Headers(user="X-User", groups="X-Groups")],
        proxied=True,
    )
    app.auth.on_login = admit
    as_admin = {"x-user": "ada", "x-groups": "admins"}
    as_staff = {"x-user": "ada", "x-groups": "staff"}
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws", headers=as_admin) as ws:
            assert opened(ws, "/admin")["shows"] == ["the admin page"]
            # The proxy now names the same person without the group. Their
            # next request says so, and the session opened on the old word
            # ends at its next event instead of going on as an admin.
            assert client.get("/api/export", headers=as_staff).status_code == 403
            click(ws, "root/act")
            assert until(ws, lambda m: m.get("name") == "leave")["args"] == {"to": "/admin"}
        assert world.acted == [] and app.sessions == {}


def test_a_tab_still_on_a_session_that_is_not_resumed_is_told(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as first_tab:
            first = opened(first_tab, "/")
            world.roles["ada"] = "candidate"
            stale(app)
            # A second tab holding the same session, a duplicate, comes in
            # after the demotion. It gets a session of its own, and the first
            # tab is sent to load its page again rather than left on a session
            # that is gone.
            resume = {"session": first["id"], "resume": first["resume"], "seq": 2}
            with client.websocket_connect("/_mw/ws") as second_tab:
                assert opened(second_tab, "/", resume)["id"] != first["id"]
                assert until(first_tab, lambda m: m.get("name") == "leave")["args"] == {"to": "/"}


def test_a_request_that_finds_the_user_changed_ends_the_session_properly(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as ws:
            opened(ws, "/admin")
            world.roles["ada"] = "candidate"
            stale(app)
            # The first thing the tab sends after the change is a request, not
            # an event. The request is the one that ends the session, and it
            # is not cut off by the ending it started: the tab is sent away,
            # told why, and the page's close hook runs to its end.
            request = {"type": "request", "request": "r1", "node": "root/t", "name": "file"}
            ws.send_text(json.dumps({"seq": 2, "msg": {**request, "payload": {"id": "none"}}}))
            assert until(ws, lambda m: m.get("name") == "leave")["args"] == {"to": "/admin"}
            assert until(ws, lambda m: m["type"] == "error")["fatal"] is True
        assert app.sessions == {} and app.ending == set() and world.closed == ["ada"]


async def test_a_session_ended_from_two_sides_is_told_once_and_closed_once(tmp_path: Path) -> None:
    app = mw.App("two", public=None, bundle_dir=tmp_path)
    closes: list[str] = []
    went_on: list[str] = []

    async def leave(s: mw.Session, _: Any) -> None:
        await s.end("the handler said so")
        went_on.append("handler")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Button("leave", key="leave", on_click=leave))

    @home.close
    async def closed(s: mw.Session) -> None:
        closes.append("started")
        await asyncio.sleep(0.05)
        closes.append("finished")

    async with TestApp(app).open("/") as page:
        clicking = asyncio.create_task(page.click("leave"))
        await asyncio.sleep(0.01)
        # The handler is waiting for its own session's end, and someone else
        # ends it too. The first word is the one the tab gets, the page is
        # closed once, and the handler sees the end through.
        await page.session.end("someone else said so")
        await clicking
        fatal = [m.message for m in page.messages if getattr(m, "fatal", False)]
        assert fatal == ["the handler said so"]
        assert closes == ["started", "finished"] and went_on == ["handler"]


async def test_a_session_that_joins_a_sign_in_as_it_ends_leaves_with_the_rest(
    tmp_path: Path,
) -> None:
    world = World()
    app = make_app(tmp_path, world)

    async def slow(user: auth.User) -> str | None:
        await asyncio.sleep(0.1)
        return "/welcome"

    app.auth.on_logout = slow
    ada = auth.User(id="ada", name="Ada", claims={"role": "admin"})
    harness = TestApp(app)
    async with harness.open("/", user=ada) as early, harness.open("/", user=ada) as late:
        early.session.sign_in = "ending"
        app.end_sign_in("ending", ada)
        # While the app is asked where the tabs should go, a session whose
        # connect was still running gets onto the same sign-in, and its own
        # timer says the sign-in is over. It leaves with the first.
        await asyncio.sleep(0.02)
        late.session.sign_in = "ending"
        app.end_sign_in("ending", ada)
        assert late.session.closed
        await asyncio.sleep(0.2)
        for page in (early, late):
            assert [c.args for c in page.commands if c.name == "leave"] == [{"to": "/welcome"}]
        assert app.sessions == {} and app.ending == set() and app._ending == {}


def gone(ws: Any) -> list[Any]:
    """What a tab hears as its session ends: where it is sent, then that it ended."""
    heard = []
    while True:
        msg = json.loads(ws.receive_text())["msg"]
        if msg["type"] == "command" and msg["name"] == "leave":
            heard.append(msg["args"]["to"])
        if msg["type"] == "error":
            heard.append(msg["message"])
            return heard


def test_tabs_hear_where_to_go_however_the_ending_finds_them(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0
    asked: list[str] = []

    async def slow_answer(user: auth.User) -> str | None:
        asked.append(user.id)
        await asyncio.sleep(0.3)
        return "/welcome"

    app.auth.on_logout = slow_answer
    world.connecting = 0.15
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with (
            client.websocket_connect("/_mw/ws") as busy,
            client.websocket_connect("/_mw/ws") as idle,
            client.websocket_connect("/_mw/ws") as arriving,
        ):
            opened(busy, "/admin")
            opened(idle, "/")
            # A third tab is still in its connect hook when the person is
            # removed and the busy tab's click finds it out.
            arriving.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/slow"}}))
            del world.roles["ada"]
            stale(app)
            click(busy, "root/act")
            # The app is being asked where the tabs should go, which takes a
            # while, and the busy tab clicks again meanwhile. Every tab is
            # sent where the app said: the one that kept clicking, the one
            # that sat idle, and the one that was still arriving.
            click(busy, "root/act", 3)
            sent = "Sign in to continue."
            assert gone(busy) == ["/welcome", sent]
            assert gone(idle) == ["/welcome", sent]
            assert gone(arriving) == ["/welcome", sent]
        assert world.acted == [] and asked == ["ada"]
        # The page that was still opening is closed, and what it started is not left running.
        assert sorted(world.closed) == ["ada", "ada from the slow page"]
        assert app.sessions == {} and app.ending == set()


def test_a_tab_that_was_not_reading_is_told_when_it_speaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.import_module("millwork.session"), "END_NOTICE_SECONDS", 0.05)
    world = World()
    app = make_app(tmp_path, world)

    async def never(text: str) -> None:
        await asyncio.Event().wait()

    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as ws:
            session = app.sessions[opened(ws, "/admin")["id"]]
            # The tab stops taking what it is sent, and its session is ended.
            session._send = never
            client.portal.call(lambda: session.dismiss("It is over.", to="/welcome"))
            time.sleep(0.15)
            assert session.closed and app.ending == set() and world.closed == ["ada"]
            # When it speaks again it is told then, and let go.
            click(ws, "root/act")
            assert gone(ws) == ["/welcome", "It is over."]
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        assert world.acted == []


def test_a_session_on_its_way_out_closes_its_page_before_the_app_shuts_down(tmp_path: Path) -> None:
    world = World()
    app = make_app(tmp_path, world, recheck=True)
    app.auth.recheck_every = 30.0
    order: list[str] = []
    app.on_shutdown(lambda: order.append(f"shutdown, closed so far: {world.closed}"))

    async def very_slow(user: auth.User) -> str | None:
        await asyncio.sleep(30)
        return None

    app.auth.on_logout = very_slow
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        with client.websocket_connect("/_mw/ws") as ws:
            session = app.sessions[opened(ws, "/admin")["id"]]
            del world.roles["ada"]
            stale(app)
            click(ws, "root/act")
            deadline = time.monotonic() + 2
            while not session.closed and time.monotonic() < deadline:
                time.sleep(0.01)
            # Over, and still owed its end while the app is asked where its
            # tab should go. The app stops in that moment.
            assert session in app.ending and app.sessions == {} and world.closed == []
    assert order == ["shutdown, closed so far: ['ada']"] and world.acted == []


async def test_the_end_of_a_session_is_not_at_the_mercy_of_the_apps_code(tmp_path: Path) -> None:
    app = mw.App("mercy", public=None, bundle_dir=tmp_path, max_sessions=1)
    seen: list[str] = []
    waiting: dict[str, Any] = {}

    async def work() -> None:
        await asyncio.sleep(30)

    def finished(s: mw.Session, task: Any) -> None:
        seen.append("on_done ran")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("home", key="t"))

    def start_work(s: mw.Session) -> None:
        s.task(work, label="work", on_done=finished)
        waiting[s.id] = s.spawn(asyncio.sleep(30))

    @home.close
    async def closed(s: mw.Session) -> None:
        seen.append("close started")
        # A close hook may end the session it is closing, start work on it,
        # and wait on work of its own that the end has just cancelled.
        await s.end("said by the close hook")
        late = s.task(work, label="late")
        assert late.status == "cancelled" and s.spawn(asyncio.sleep(30)).cancelling()
        await asyncio.sleep(0.05)
        seen.append("close finished")
        await waiting[s.id]

    harness = TestApp(app)
    async with harness.open("/") as page:
        session = page.session
        start_work(session)
        # Whoever asks for the end is cancelled while it is under way.
        asking = asyncio.create_task(session.end("gone"))
        await asyncio.sleep(0.01)
        asking.cancel()
        assert session.closed
        await asyncio.sleep(0.15)
        # The page was closed all the same, to the end of its hook, once. The
        # task the end cancelled did not come back as a handler.
        assert seen == ["close started", "close finished"]
        assert app.ending == set() and session._finishing.done()
        fatal = [m.message for m in page.messages if getattr(m, "fatal", False)]
        assert fatal == ["gone"]

    # Making room for a newcomer does not wait for the close hook of the
    # session that is put out.
    seen.clear()
    async with harness.open("/") as page:
        start_work(page.session)
        page.session.detach()
        resolved = app.resolve("/")
        assert resolved is not None
        newcomer = Session(app, resolved[0], resolved[1], "/")
        started = time.monotonic()
        assert await app.admit(newcomer) and time.monotonic() - started < 0.04
        assert page.session.closed and "close finished" not in seen
        await asyncio.sleep(0.15)
        assert seen == ["close started", "close finished"]
        await newcomer._close()
