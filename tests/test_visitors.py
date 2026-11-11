"""Visitors: a browser's id in a signed cookie, and the session that carries it."""

import base64
import datetime as dt
import json
import logging
import time
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

import millwork as mw
from millwork import auth, ui
from millwork.testing import TestApp

SECRET = "s3cret-s3cret-s3cret-s3cret-s3cret"


def make_app(tmp_path: Path | None, name: str = "v", **kw: Any) -> mw.App:
    """An app that shows the visitor. Without a folder it serves the real bundle."""
    kw.setdefault("identify_visitors", True)
    if tmp_path is not None:
        kw["bundle_dir"] = tmp_path
    app = mw.App(name, public=None, **kw)

    @app.page("/", public=True)
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.visitor.id, key="t"))

    @app.page("/desk")
    def desk(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.visitor.id, key="t"))

    return app


def with_sign_in(tmp_path: Path | None, **kw: Any) -> mw.App:
    def verify(username: str, password: str) -> bool:
        return password == "pw"

    def admit(identity: auth.Identity) -> auth.User:
        return auth.User(id=identity.subject, name=identity.subject)

    sign_ins = auth.Auth([auth.Password(verify)], on_login=admit)
    return make_app(tmp_path, secret=SECRET, auth=sign_ins, **kw)


def sign_in(client: TestClient, name: str) -> None:
    r = client.post("/_mw/auth/login", json={"username": name, "password": "pw"})
    assert r.status_code == 200


def visitor_of(client: TestClient, path: str = "/") -> str:
    """The id a new session opened by this browser shows."""
    with client.websocket_connect("/_mw/ws") as ws:
        ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": path}}))
        assert json.loads(ws.receive_text())["msg"]["type"] == "session"
        mount = json.loads(ws.receive_text())["msg"]
        return mount["nodes"]["root/t"]["props"]["content"]


def cookie_set(response: Any, name: str = "mw_visitor") -> str | None:
    """The Set-Cookie line a response carries for one cookie, if it does."""
    lines = response.headers.get_list("set-cookie")
    mine = [line for line in lines if line.startswith(f"{name}=")]
    assert len(mine) <= 1
    return mine[0] if mine else None


def payload(cookie: str) -> dict[str, Any]:
    body = cookie.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def test_an_app_that_does_not_ask_sets_no_cookie_and_has_no_visitor(tmp_path: Path) -> None:
    app = make_app(tmp_path, identify_visitors=False)
    with TestClient(app.asgi) as client:
        assert cookie_set(client.get("/")) is None
        assert "mw_visitor" not in client.cookies


async def test_reading_the_visitor_without_the_argument_names_the_argument() -> None:
    app = mw.App("plain", public=None)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.visitor.id))

    with pytest.raises(RuntimeError, match=r"App\(identify_visitors=True\)"):
        async with TestApp(app).open("/"):
            pass


def test_the_first_page_load_gives_the_browser_its_cookie(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        first = client.get("/")
        line = cookie_set(first)
        assert line is not None
        said = line.lower()
        assert "httponly" in said and "samesite=lax" in said
        assert "path=/" in said.split("; ")
        # No lifetime: the browser drops it when it closes.
        assert "max-age" not in said and "expires" not in said and "secure" not in said
        # The answer names one browser, so a shared cache keeps out of it.
        assert first.headers["cache-control"] == "private"
        again = client.get("/")
        assert cookie_set(again) is None and "cache-control" not in again.headers
        # A page that is not there names the browser all the same.
        client.cookies.clear()
        assert cookie_set(client.get("/nowhere")) is not None


def test_the_cookie_is_secure_over_https(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi, base_url="https://testserver") as client:
        assert "secure" in (cookie_set(client.get("/")) or "").lower()


def test_every_tab_of_a_browser_is_one_visitor_and_another_browser_is_another(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        client.get("/")
        mine = visitor_of(client)
        assert mine == visitor_of(client) == payload(client.cookies["mw_visitor"])["id"]
        # A browser with a jar of its own.
        client.cookies.clear()
        client.get("/")
        theirs = visitor_of(client)
        assert theirs != mine and theirs == visitor_of(client)


def test_a_browser_without_the_cookie_is_a_visitor_of_its_own_in_every_tab(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        first, second = visitor_of(client), visitor_of(client)
        assert first and second and first != second


def test_a_cookie_nobody_issued_names_no_visitor(tmp_path: Path) -> None:
    app = make_app(tmp_path, secret=SECRET)
    stranger = make_app(tmp_path, name="other", secret=SECRET)
    with TestClient(app.asgi) as client:
        client.get("/")
        good = client.cookies["mw_visitor"]
        mine = payload(good)["id"]
        body, sig = good.split(".")
        altered = base64.urlsafe_b64encode(
            json.dumps({**payload(good), "id": "someone-else"}).encode()
        ).decode()
        forged = [
            f"{altered.rstrip('=')}.{sig}",
            f"{body}.{'B' if sig[0] == 'A' else 'A'}{sig[1:]}",
            "someone-else",
            # Another app's, signed with the same secret.
            stranger.visitors.issue("someone-else", None),
        ]
        for token in forged:
            client.cookies.clear()
            client.cookies.set("mw_visitor", token, domain="testserver.local")
            shown = visitor_of(client)
            assert shown not in (mine, "someone-else")
            # The page load replaces it with one of the app's own.
            line = cookie_set(client.get("/"))
            assert line is not None and "someone-else" not in line


def test_a_session_keeps_its_visitor_when_the_cookie_changes(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        client.get("/")
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
            info = json.loads(ws.receive_text())["msg"]
            ws.receive_text()
        mine = app.sessions[info["id"]].visitor.id
        client.cookies.clear()
        client.get("/")
        assert payload(client.cookies["mw_visitor"])["id"] != mine
        resume = {"session": info["id"], "resume": info["resume"], "seq": 2}
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/", **resume}}))
            assert json.loads(ws.receive_text())["msg"]["id"] == info["id"]
        assert app.sessions[info["id"]].visitor.id == mine


def test_the_cookie_carries_the_app_prefix(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi, root_path="/sales") as client:
        line = cookie_set(client.get("/"), "mw_visitor_sales")
        assert line is not None and "path=/sales" in line.lower().split("; ")
        # It is read back under that name, by a socket and by a page load.
        mine = payload(client.cookies["mw_visitor_sales"])["id"]
        for _ in range(2):
            with client.websocket_connect("/sales/_mw/ws") as ws:
                ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
                ws.receive_text()
                mount = json.loads(ws.receive_text())["msg"]
                assert mount["nodes"]["root/t"]["props"]["content"] == mine
        # The jar sends the cookie where its path says, as a browser does.
        assert cookie_set(client.get("/sales/"), "mw_visitor_sales") is None


def test_an_id_that_is_not_text_names_no_visitor(tmp_path: Path) -> None:
    app = make_app(tmp_path, secret=SECRET)
    with TestClient(app.asgi) as client:
        for odd in (5, "", None, ["a"], {"a": 1}):
            token = auth.sign(SECRET, "visitor:v", {"id": odd, "user": None, "exp": 2**40})
            client.cookies.clear()
            client.cookies.set("mw_visitor", token, domain="testserver.local")
            shown = visitor_of(client)
            assert shown and shown != str(odd)
            assert cookie_set(client.get("/")) is not None


def test_a_secret_that_signs_visitors_is_long_or_left_out(tmp_path: Path) -> None:
    for short in ("", "a", "x" * 31):
        with pytest.raises(ValueError, match="32 characters"):
            make_app(tmp_path, secret=short)
    make_app(tmp_path, secret="x" * 32)
    # Nothing is signed for an app that identifies nobody.
    make_app(tmp_path, secret="a", identify_visitors=False)


def test_what_remembers_the_user_is_no_visitor_of_another_app(tmp_path: Path) -> None:
    # Two apps share a secret, and the name of one is the other's with a
    # suffix. Someone who picks their own user id on the first reads what
    # their cookie remembers them by, and offers it to the second as the
    # signature of a visitor they made up.
    first = with_sign_in(tmp_path, name="x")
    second = make_app(tmp_path, name="x:user", secret=SECRET)
    made_up = (
        base64.urlsafe_b64encode(
            json.dumps({"id": "anyone", "user": None, "exp": 2**40}, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    with TestClient(first.asgi) as client:
        sign_in(client, made_up)
        client.get("/desk")
        remembered = payload(client.cookies["mw_visitor"])["user"]
    assert second.visitors.read(f"{made_up}.{remembered}", None) is None


def test_two_browsers_of_one_person_are_not_told_apart_by_their_cookies(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    remembered = []
    for _ in range(2):
        with TestClient(app.asgi) as client:
            sign_in(client, "ada")
            client.get("/desk")
            remembered.append(payload(client.cookies["mw_visitor"])["user"])
    assert remembered[0] != remembered[1]


def test_a_sign_in_has_a_visitor_of_its_own(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    with TestClient(app.asgi) as client:
        client.get("/")
        nobody = visitor_of(client)
        sign_in(client, "ada")
        # The page load after the sign-in issues an id to the person, and the
        # cookie says nothing of who they are.
        assert cookie_set(client.get("/desk")) is not None
        adas = visitor_of(client, "/desk")
        assert adas != nobody and adas == visitor_of(client)
        assert "ada" not in json.dumps(payload(client.cookies["mw_visitor"]))
        assert cookie_set(client.get("/desk")) is None
        # Signing out: the browser has a new id before anyone loads a page.
        left = client.post("/_mw/auth/logout")
        assert cookie_set(left) is not None
        after = visitor_of(client)
        assert after not in (nobody, adas) and after == visitor_of(client)
        assert cookie_set(client.get("/")) is None
        # Signing in again starts over.
        sign_in(client, "ada")
        client.get("/desk")
        assert visitor_of(client, "/desk") not in (nobody, adas, after)


def test_a_tab_from_before_the_sign_in_keeps_its_own_visitor(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    with TestClient(app.asgi) as client:
        client.get("/")
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
            early = json.loads(ws.receive_text())["msg"]["id"]
            ws.receive_text()
            sign_in(client, "ada")
            client.get("/desk")
            adas = visitor_of(client, "/desk")
            # Still open, still nobody's, and not the visitor Ada is.
            assert app.sessions[early].user is None
            assert app.sessions[early].visitor.id != adas
        # Every session that holds Ada's visitor is one of Ada's.
        holders = [s for s in app.sessions.values() if s.visitor.id == adas]
        assert holders and all(s.user is not None and s.user.id == "ada" for s in holders)


def test_a_page_that_sends_to_the_login_names_the_browser_too(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    with TestClient(app.asgi) as client:
        sent = client.get("/desk", follow_redirects=False)
        assert sent.status_code == 302 and cookie_set(sent) is not None
        assert sent.headers["cache-control"] == "private"


def test_a_sign_in_that_ran_out_takes_its_visitor_along_at_the_login_page() -> None:
    app = with_sign_in(None)
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        client.get("/desk")
        adas = payload(client.cookies["mw_visitor"])["id"]
        # The sign-in is gone, and the tab is sent to the login page.
        client.cookies.delete("mw_auth")
        login = client.get("/_mw/login?next=/desk")
        assert login.status_code == 200 and cookie_set(login) is not None
        between = payload(client.cookies["mw_visitor"])["id"]
        # The same person again is a new visitor, as after a sign-out.
        sign_in(client, "ada")
        client.get("/desk")
        again = payload(client.cookies["mw_visitor"])["id"]
        assert len({adas, between, again}) == 3
        # Someone who is signed in is sent on from the login page as they are.
        on = client.get("/_mw/login?next=/desk", follow_redirects=False)
        assert on.status_code == 302 and cookie_set(on) is None


def test_a_sign_out_asked_from_another_site_changes_nothing(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        client.get("/desk")
        refused = client.post("/_mw/auth/logout", headers={"origin": "https://evil.example"})
        assert refused.status_code == 400 and cookie_set(refused) is None


def test_a_visitor_is_not_passed_on_to_the_next_person(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        client.get("/desk")
        adas = visitor_of(client, "/desk")
        # Ada's sign-in is gone without a sign-out, as when it ran out, and
        # someone else signs in on the same browser.
        client.cookies.delete("mw_auth")
        sign_in(client, "grace")
        # A socket that arrives before any page load is not Ada's visitor.
        assert visitor_of(client, "/desk") != adas
        assert cookie_set(client.get("/desk")) is not None
        graces = visitor_of(client, "/desk")
        assert graces != adas and graces == visitor_of(client, "/desk")
        # Nor is a socket that arrives right after a sign-in, with the cookie
        # of whoever was there before.
        client.post("/_mw/auth/logout")
        nobody = visitor_of(client)
        sign_in(client, "ada")
        assert visitor_of(client, "/desk") not in (nobody, adas, graces)


def test_a_visitor_does_not_outlast_the_sign_in_it_was_issued_to(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        client.get("/desk")
        adas = visitor_of(client, "/desk")
        client.cookies.delete("mw_auth")
        # Nobody is signed in now. A public page is not shown Ada's visitor,
        # by a socket that comes first or after the page load.
        assert visitor_of(client) != adas
        assert cookie_set(client.get("/")) is not None
        assert visitor_of(client) != adas


def test_without_a_secret_the_log_says_ids_do_not_last(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="millwork"):
        make_app(tmp_path)
    assert any("new id every time the app starts" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="millwork"):
        make_app(tmp_path, secret=SECRET)
        make_app(tmp_path, identify_visitors=False)
    assert not any("new id" in r.getMessage() for r in caplog.records)


def test_a_restart_with_the_same_secret_keeps_the_visitor(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path, secret=SECRET).asgi) as client:
        client.get("/")
        cookie = client.cookies["mw_visitor"]
        mine = visitor_of(client)
    for secret, kept in ((SECRET, True), (None, False)):
        with TestClient(make_app(tmp_path, secret=secret).asgi) as client:
            client.cookies.set("mw_visitor", cookie, domain="testserver.local")
            assert (visitor_of(client) == mine) is kept
            assert (cookie_set(client.get("/")) is None) is kept


async def test_the_harness_opens_pages_as_a_named_visitor() -> None:
    app = mw.App("harness", public=None, identify_visitors=True)
    seen: list[str] = []

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        seen.append(s.visitor.id)
        return ui.Page(ui.Text(s.visitor.id, key="t"))

    harness = TestApp(app)
    async with harness.open("/", visitor="a") as one, harness.open("/", visitor="a") as two:
        assert one.find("t").props["content"] == two.find("t").props["content"] == "a"
    async with harness.open("/") as one, harness.open("/") as two:
        ids = {one.find("t").props["content"], two.find("t").props["content"]}
        assert len(ids) == 2 and "a" not in ids


async def test_the_harness_refuses_a_visitor_the_app_does_not_identify() -> None:
    app = mw.App("harness", public=None)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page()

    with pytest.raises(ValueError, match="identify_visitors"):
        async with TestApp(app).open("/", visitor="a"):
            pass


def said_by_a_route(request: Any) -> Any:
    from starlette.responses import JSONResponse

    visitor = request.state.visitor
    user = getattr(request.state, "user", None)
    return JSONResponse(
        {"visitor": visitor.id if visitor else None, "user": user.id if user else None}
    )


def test_a_route_finds_the_visitor_a_page_would(tmp_path: Path) -> None:
    app = make_app(tmp_path, secret=SECRET)
    app.route("/api/me", said_by_a_route)
    with TestClient(app.asgi) as client:
        # No page was loaded, so the browser has no id, and a route issues none.
        first = client.get("/api/me")
        assert first.json() == {"visitor": None, "user": None}
        assert cookie_set(first) is None
        client.get("/")
        mine = visitor_of(client)
        assert client.get("/api/me").json()["visitor"] == mine
        # A cookie nobody issued is no visitor here either.
        client.cookies.clear()
        client.cookies.set("mw_visitor", "someone-else", domain="testserver.local")
        assert client.get("/api/me").json()["visitor"] is None


def test_what_is_mounted_finds_the_visitor(tmp_path: Path) -> None:
    from starlette.applications import Starlette
    from starlette.routing import Route

    app = make_app(tmp_path)
    app.mount("/inner", Starlette(routes=[Route("/me", said_by_a_route)]))
    with TestClient(app.asgi) as client:
        client.get("/")
        assert client.get("/inner/me").json()["visitor"] == visitor_of(client)


def test_a_route_of_an_app_that_identifies_nobody_has_no_visitor(tmp_path: Path) -> None:
    from starlette.responses import JSONResponse

    app = make_app(tmp_path, identify_visitors=False)
    app.route("/api/me", lambda request: JSONResponse(hasattr(request.state, "visitor")))
    with TestClient(app.asgi) as client:
        assert client.get("/api/me").json() is False


def test_a_route_tells_the_visitor_by_who_is_signed_in(tmp_path: Path) -> None:
    app = with_sign_in(tmp_path)
    app.route("/api/me", said_by_a_route)
    app.route("/api/open", said_by_a_route, public=True)
    with TestClient(app.asgi) as client:
        client.get("/")
        nobody = visitor_of(client)
        assert client.get("/api/open").json() == {"visitor": nobody, "user": None}
        sign_in(client, "ada")
        # Signed in, and no page loaded since: the id in the cookie is nobody's.
        assert client.get("/api/me").json() == {"visitor": None, "user": "ada"}
        client.get("/desk")
        adas = visitor_of(client, "/desk")
        assert adas != nobody
        assert client.get("/api/me").json() == {"visitor": adas, "user": "ada"}
        # A route open to anyone is told the same visitor, and no user.
        assert client.get("/api/open").json() == {"visitor": adas, "user": None}
        # The sign-in is gone: the id was Ada's, and is nobody's now.
        client.cookies.delete("mw_auth")
        assert client.get("/api/open").json() == {"visitor": None, "user": None}
        assert client.get("/api/me").status_code == 401


def test_a_public_route_answers_when_nobody_can_say_who_is_signed_in(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    asked = []

    def admit(identity: auth.Identity) -> auth.User:
        return auth.User(id=identity.subject, name=identity.subject)

    def recheck(user: auth.User) -> auth.User:
        asked.append(user.id)
        if len(asked) > 1:
            raise RuntimeError("the directory is down")
        return user

    sign_ins = auth.Auth(
        [auth.Password(lambda u, p: p == "pw")],
        on_login=admit,
        recheck=recheck,
        recheck_every=dt.timedelta(microseconds=1),
    )
    app = make_app(tmp_path, secret=SECRET, auth=sign_ins)
    app.route("/hook", said_by_a_route, public=True)
    with TestClient(app.asgi) as client:
        # Something that brings no cookie is not looked up at all.
        assert client.get("/hook").json() == {"visitor": None, "user": None}
        assert asked == []
        sign_in(client, "ada")
        client.get("/desk")
        assert asked == ["ada"]
        # An answer is kept for two steps of the clock at the least, which is
        # some 30 ms where the clock is coarse, so the next request waits
        # that out to be one that asks again.
        time.sleep(3 * auth.TICK)
        with caplog.at_level(logging.ERROR, logger="millwork"):
            answer = client.get("/hook")
        assert answer.status_code == 200 and answer.json()["visitor"] is None
        assert any("has no visitor" in r.getMessage() for r in caplog.records)


def test_a_user_the_app_put_on_the_request_itself_is_not_taken_for_a_sign_in(
    tmp_path: Path,
) -> None:
    class Own:
        """Middleware of the app's own that names a user its own way."""

        def __init__(self, inner: Any) -> None:
            self.inner = inner

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] == "http":
                scope.setdefault("state", {})["user"] = "someone the app knows"
            await self.inner(scope, receive, send)

    from starlette.responses import JSONResponse

    app = make_app(tmp_path)
    app.middleware(Own)
    app.route(
        "/api/me",
        lambda request: JSONResponse(request.state.visitor and request.state.visitor.id),
    )
    with TestClient(app.asgi) as client:
        client.get("/")
        assert client.get("/api/me").json() == visitor_of(client)


def test_a_request_from_another_site_that_changes_something_has_no_visitor(
    tmp_path: Path,
) -> None:
    app = with_sign_in(tmp_path)
    app.route("/api/open", said_by_a_route, methods=["GET", "POST"], public=True)
    with TestClient(app.asgi) as client:
        client.get("/")
        mine = visitor_of(client)
        elsewhere = {"origin": "https://evil.example"}
        here = {"origin": "http://testserver"}
        assert client.post("/api/open", headers=here).json()["visitor"] == mine
        assert client.post("/api/open").json()["visitor"] == mine
        assert client.post("/api/open", headers=elsewhere).json()["visitor"] is None
        # Reading changes nothing, and the answer goes to the visitor's own browser.
        assert client.get("/api/open", headers=elsewhere).json()["visitor"] == mine


def test_a_socket_of_the_apps_own_finds_the_visitor(tmp_path: Path) -> None:
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    from starlette.websockets import WebSocket

    async def feed(ws: WebSocket) -> None:
        await ws.accept()
        visitor = ws.state.visitor
        await ws.send_json(visitor.id if visitor else None)
        await ws.close()

    app = make_app(tmp_path)
    app.mount("/live", Starlette(routes=[WebSocketRoute("/feed", feed)]), public=True)
    with TestClient(app.asgi) as client:
        client.get("/")
        mine = visitor_of(client)
        with client.websocket_connect("/live/feed") as ws:
            assert ws.receive_json() == mine
        with client.websocket_connect(
            "/live/feed", headers={"origin": "https://evil.example"}
        ) as ws:
            assert ws.receive_json() is None


def test_a_public_route_asks_about_nobody_who_brought_no_visitor(tmp_path: Path) -> None:
    asked = []

    def admit(identity: auth.Identity) -> auth.User:
        return auth.User(id=identity.subject, name=identity.subject)

    def recheck(user: auth.User) -> auth.User:
        asked.append(user.id)
        return user

    sign_ins = auth.Auth(
        [auth.Password(lambda u, p: p == "pw")],
        on_login=admit,
        recheck=recheck,
        recheck_every=dt.timedelta(microseconds=1),
    )
    app = make_app(tmp_path, secret=SECRET, auth=sign_ins)
    app.route("/hook", said_by_a_route, public=True)
    with TestClient(app.asgi) as client:
        sign_in(client, "ada")
        before = len(asked)
        # Signed in, and no visitor cookie yet: nobody is looked up.
        assert "mw_visitor" not in client.cookies
        assert client.get("/hook").json()["visitor"] is None
        assert len(asked) == before
