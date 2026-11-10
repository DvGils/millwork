"""Visitors: a browser's id in a signed cookie, and the session that carries it."""

import base64
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

import millwork as mw
from millwork import auth, ui
from millwork.testing import TestApp

SECRET = "s3cret-s3cret-s3cret-s3cret-s3cret"


def make_app(tmp_path: Path, name: str = "v", **kw: Any) -> mw.App:
    kw.setdefault("identify_visitors", True)
    app = mw.App(name, public=None, bundle_dir=tmp_path, **kw)

    @app.page("/", public=True)
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.visitor.id, key="t"))

    @app.page("/desk")
    def desk(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.visitor.id, key="t"))

    return app


def with_sign_in(tmp_path: Path, **kw: Any) -> mw.App:
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
        assert "httponly" in said and "samesite=lax" in said and "path=/" in said
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
        assert line is not None and "path=/sales" in line.lower()


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
