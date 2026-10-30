"""Auth: pages gated, password and OAuth flows, the websocket bound to the cookie, intents."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import millwork as mw
from millwork import auth, ui


def fake_provider() -> Starlette:
    """An OAuth provider that accepts any code and knows one user."""

    async def token(request: Request) -> JSONResponse:
        form = parse_qs((await request.body()).decode())
        assert form["grant_type"] == ["authorization_code"]
        return JSONResponse({"access_token": "tok-" + form["code"][0], "token_type": "bearer"})

    async def me(request: Request) -> JSONResponse:
        assert request.headers["authorization"] == "Bearer tok-abc"
        return JSONResponse(
            {
                "sub": "u1",
                "userPrincipalName": "ada@markteffect.nl",
                "displayName": "Ada",
                "mail": "Ada@Markteffect.nl",
            }
        )

    return Starlette(routes=[Route("/token", token, methods=["POST"]), Route("/me", me)])


def make_app(tmp_path: Path, **kw: Any) -> mw.App:
    hashed = auth.hash_password("pw")
    users = {"demian": hashed}

    def verify(username: str, password: str) -> bool:
        return username in users and auth.check_password(password, users[username])

    async def on_login(identity: auth.Identity) -> auth.User | None:
        if (
            identity.email
            and not identity.email.endswith("@markteffect.nl")
            and identity.provider != "password"
        ):
            return None
        if identity.intent == "demo":
            return auth.User(
                id=identity.email or identity.subject, name="Demo", claims={"projects": ["demo"]}
            )
        return auth.User(
            id=identity.email or identity.subject,
            name=identity.name or identity.subject,
            claims={"projects": ["p1"]},
        )

    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake_provider()), base_url="http://idp"
    )
    app = mw.App(
        "a",
        public=None,
        bundle_dir=tmp_path,
        secret="s3cret-s3cret-s3cret-s3cret-s3cret",
        auth=auth.Auth(
            [
                auth.Password(verify),
                auth.OAuth(
                    "fake",
                    label="Fake IdP",
                    authorize_url="http://idp/authorize",
                    token_url="http://idp/token",
                    userinfo_url="http://idp/me",
                    client_id="c",
                    client_secret="x",
                    scopes="openid",
                    http=http,
                ),
            ],
            on_login=on_login,
            intents={"demo": "Try the demo"},
            log_identity="hashed",
        ),
        **kw,
    )

    @app.page("/", title="Home")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(f"hi {s.user.name}", key="t"))

    @app.page("/terms", public=True)
    def terms(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("terms", key="t"))

    @app.page("/projects/{pid}")
    def project(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.params["pid"], key="t"))

    @project.connect
    async def guard(s: mw.Session, pid: str) -> None:
        if pid not in s.user.claims["projects"]:
            raise auth.Forbidden("Not your project.")

    return app


def ws_hello(ws: Any, path: str = "/") -> dict[str, Any]:
    ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": path}}))
    return json.loads(ws.receive_text())["msg"]


def test_pages_are_gated_and_password_login_sets_the_cookie(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].startswith("/_mw/login?next=%2F")
        assert client.get("/terms").status_code == 503  # public: served (no bundle in tests)
        # The login page describes the providers and nothing more.
        r = client.get("/_mw/login?next=/x")
        assert r.status_code == 503 or "Fake IdP" in r.text
        r = client.post("/_mw/auth/login", json={"username": "demian", "password": "nope"})
        assert r.status_code == 401
        r = client.post("/_mw/auth/login", json={"username": "demian", "password": "pw"})
        assert r.status_code == 200 and r.json()["user"]["name"] == "demian"
        cookie = r.cookies.get("mw_auth")
        assert cookie and r.headers["set-cookie"].lower().count("httponly") == 1
        assert client.get("/", follow_redirects=False).status_code == 503  # signed in: served
        with client.websocket_connect("/_mw/ws") as ws:
            assert ws_hello(ws)["type"] == "session"
            mount = json.loads(ws.receive_text())["msg"]
            assert mount["nodes"]["root/t"]["props"]["content"] == "hi demian"
        with client.websocket_connect("/_mw/ws") as ws:
            # Forbidden from connect: the forbidden page, with the message, same socket.
            assert ws_hello(ws, "/projects/p9")["type"] == "session"
            mount = json.loads(ws.receive_text())["msg"]
            assert "Not your project." in [
                n["props"].get("content") for n in mount["nodes"].values()
            ]
        with client.websocket_connect("/_mw/ws") as ws:
            ws_hello(ws, "/projects/p1")
            assert (
                json.loads(ws.receive_text())["msg"]["nodes"]["root/t"]["props"]["content"] == "p1"
            )
        client.post("/_mw/auth/logout")
        assert client.get("/", follow_redirects=False).status_code == 302


def test_websocket_without_cookie_is_refused_on_a_gated_page(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            msg = ws_hello(ws, "/")
            assert msg["type"] == "error" and msg["fatal"] is True
        with client.websocket_connect("/_mw/ws") as ws:
            assert ws_hello(ws, "/terms")["type"] == "session"


def test_oauth_flow_with_intent_and_denial(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        r = client.get("/_mw/auth/oauth/fake?next=/projects/p1&intent=demo", follow_redirects=False)
        assert r.status_code == 302
        location = r.headers["location"]
        assert location.startswith("http://idp/authorize?") and "client_id=c" in location
        state = dict(p.split("=") for p in location.split("?")[1].split("&"))["state"]
        assert (
            "redirect_uri=http%3A%2F%2Ftestserver%2F_mw%2Fauth%2Foauth%2Ffake%2Fcallback"
            in location
        )
        # A mismatching state is refused.
        r = client.get("/_mw/auth/oauth/fake/callback?code=abc&state=wrong", follow_redirects=False)
        assert r.status_code == 302 and "error=" in r.headers["location"]
        r = client.get(
            "/_mw/auth/oauth/fake/callback?code=abc&state=%C3%A9", follow_redirects=False
        )
        assert r.status_code == 302 and "error=" in r.headers["location"]
        r = client.get(
            f"/_mw/auth/oauth/fake/callback?code=abc&state={state}", follow_redirects=False
        )
        assert r.status_code == 302 and r.headers["location"] == "/projects/p1"
        user = app.auth.read(client.cookies.get("mw_auth"))
        assert user is not None and user.id == "ada@markteffect.nl" and user.name == "Demo"
        assert user.claims == {"projects": ["demo"]}
        # An absolute `next` is never followed.
        r = client.get("/_mw/auth/oauth/fake?next=https://evil.example", follow_redirects=False)
        assert "next" not in r.headers["location"]


def test_claims_limit_dev_provider_and_hashing(tmp_path: Path) -> None:
    big = auth.User(id="x", name="x", claims={"blob": "y" * 3000})
    a = auth.Auth([auth.Password(lambda u, p: True)])
    a.bind("s" * 32, False)
    with pytest.raises(ValueError):
        a.issue(big)
    assert a.read("not a token") is None
    assert a.read(a.issue(auth.User(id="u", name="U"))) == auth.User(id="u", name="U")
    with pytest.raises(RuntimeError):
        mw.App(
            "d",
            public=None,
            bundle_dir=tmp_path,
            secret="s" * 32,
            auth=auth.Auth([auth.Dev(auth.User(id="d", name="D"))]),
        )
    app = mw.App(
        "d",
        public=None,
        bundle_dir=tmp_path,
        secret="s" * 32,
        debug=True,
        auth=auth.Auth([auth.Dev(auth.User(id="d", name="D"))]),
    )

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.user.id, key="t"))

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        ws_hello(ws)
        assert json.loads(ws.receive_text())["msg"]["nodes"]["root/t"]["props"]["content"] == "d"
    h = auth.hash_password("secret")
    assert (
        h.startswith("scrypt$")
        and auth.check_password("secret", h)
        and not auth.check_password("other", h)
    )
    assert (
        auth.email_of({"userPrincipalName": "X@Y.nl"}) == "x@y.nl"
        and auth.email_of({"name": "n"}) is None
    )


def test_resume_is_bound_to_the_user(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        client.post("/_mw/auth/login", json={"username": "demian", "password": "pw"})
        with client.websocket_connect("/_mw/ws") as ws:
            info = ws_hello(ws)
            ws.receive_text()
        resume = {"session": info["id"], "resume": info["resume"], "seq": 2}
        # The same user picks the session back up.
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/", **resume}}))
            assert json.loads(ws.receive_text())["msg"]["id"] == info["id"]
        # Another user with the session id and token gets their own session, not this one.
        # The jar files the login cookie under the test host's domain; the
        # replacement names the same one, or both would be sent.
        client.cookies.set(
            "mw_auth", app.auth.issue(auth.User(id="eve", name="Eve")), domain="testserver.local"
        )
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/", **resume}}))
            msg = json.loads(ws.receive_text())["msg"]
            assert msg["type"] == "session" and msg["id"] != info["id"]
            mount = json.loads(ws.receive_text())["msg"]
            assert mount["nodes"]["root/t"]["props"]["content"] == "hi Eve"
        # No cookie at all: the resume is refused and the gated page needs a sign-in.
        client.cookies.clear()
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/", **resume}}))
            msg = json.loads(ws.receive_text())["msg"]
            assert msg["type"] == "error" and msg["message"] == "Sign in to continue."
        assert app.sessions[info["id"]].user.id == "demian"


def test_the_headers_provider_goes_through_on_login(tmp_path: Path) -> None:
    seen: list[str] = []

    async def on_login(identity: auth.Identity) -> auth.User | None:
        seen.append(identity.provider)
        if identity.subject == "eve":
            return None
        return auth.User(id=identity.subject, name="Ada", claims={"role": "admin"})

    app = mw.App(
        "h",
        public=None,
        bundle_dir=tmp_path,
        secret="x" * 32,
        proxied=True,
        auth=auth.Auth([auth.Headers(user="x-user")], on_login=on_login),
    )

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(f"{s.user.name} {s.user.claims['role']}", key="t"))

    with TestClient(app.asgi) as client:
        assert client.get("/", headers={"x-user": "eve"}, follow_redirects=False).status_code == 302
        assert client.get("/", headers={"x-user": "ada"}, follow_redirects=False).status_code == 503
        assert client.get("/", follow_redirects=False).status_code == 302
        with client.websocket_connect("/_mw/ws", headers={"x-user": "ada"}) as ws:
            ws_hello(ws)
            mount = json.loads(ws.receive_text())["msg"]
            assert mount["nodes"]["root/t"]["props"]["content"] == "Ada admin"
    assert seen and set(seen) == {"header"}


def test_login_needs_json_from_the_same_origin_and_checks_off_the_loop(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        body = '{"username":"demian","password":"pw","x":"=1"}'
        r = client.post("/_mw/auth/login", content=body, headers={"content-type": "text/plain"})
        assert r.status_code == 400 and "mw_auth" not in r.headers.get("set-cookie", "")
        creds = {"username": "demian", "password": "pw"}
        r = client.post("/_mw/auth/login", json=creds, headers={"origin": "https://evil.example"})
        assert r.status_code == 400
        r = client.post("/_mw/auth/login", json=creds, headers={"origin": "http://testserver"})
        assert r.status_code == 200

    where: list[str] = []

    def verify(username: str, password: str) -> bool:
        try:
            asyncio.get_running_loop()
            where.append("loop")
        except RuntimeError:
            where.append("thread")
        return False

    slow = mw.App(
        "p",
        public=None,
        bundle_dir=tmp_path,
        secret="x" * 32,
        auth=auth.Auth([auth.Password(verify)]),
    )
    with TestClient(slow.asgi) as client:
        assert (
            client.post("/_mw/auth/login", json={"username": "a", "password": "b"}).status_code
            == 401
        )
    assert where == ["thread"]


def test_backslash_paths_are_refused_and_auth_needs_a_real_secret(
    tmp_path: Path,
) -> None:
    from millwork.auth import _safe_next

    assert _safe_next("/ok?a=1") == "/ok?a=1"
    assert _safe_next("/\\evil.com") == "/"
    assert _safe_next("/x\\y") == "/"
    assert _safe_next("/a\nb") == "/"
    assert ui.safe_href("/ok") == "/ok"
    with pytest.raises(ValueError):
        ui.safe_href("/\\evil.com")
    for secret in (None, "short"):
        with pytest.raises(ValueError):
            mw.App(
                "s",
                public=None,
                bundle_dir=tmp_path,
                secret=secret,
                auth=auth.Auth([auth.Password(lambda u, p: False)]),
            )


def test_signed_tokens_refuse_everything_but_the_genuine_article() -> None:
    secret = "s" * 32
    exp = int(time.time()) + 60
    token = auth.sign(secret, "auth", {"id": "u", "exp": exp})
    assert auth.verify(secret, "auth", token) == {"id": "u", "exp": exp}
    body, sig = token.split(".")
    # A changed payload, a changed signature, another secret, another purpose.
    forged = auth.sign("x" * 32, "auth", {"id": "admin", "exp": exp}).split(".")[0]
    assert auth.verify(secret, "auth", f"{forged}.{sig}") is None
    assert auth.verify(secret, "auth", f"{body}.{sig[:-2]}AA") is None
    assert auth.verify("t" * 32, "auth", token) is None
    assert auth.verify(secret, "oauth-state", token) is None
    # Expired, no expiry, an expiry that is not a number, a payload that is not an object.
    assert auth.verify(secret, "auth", auth.sign(secret, "auth", {"exp": exp - 120})) is None
    for payload in ({"id": "u"}, {"exp": "9999999999"}, {"exp": True}, {"exp": float("inf")}):
        with pytest.raises(ValueError):
            auth.sign(secret, "auth", payload)
    for raw in (
        b"[1]",
        b'{"id": "u"}',
        b'{"exp": "9999999999"}',
        b'{"exp": true}',
        b'{"exp": NaN}',
        b'{"exp": Infinity}',
        b'{"exp": 1e999}',
    ):
        hand = auth._b64(raw)
        assert auth.verify(secret, "auth", f"{hand}.{auth._mac(secret, 'auth', hand)}") is None
    with pytest.raises(ValueError):
        auth.sign(secret, "auth", {"exp": float("nan")})
    with pytest.raises(ValueError):
        auth.sign("", "auth", {"exp": exp})
    # Only the exact signature text is accepted: no re-padding, re-spelling or stray bytes.
    for spelled in (sig + "=", sig.replace("-", "+").replace("_", "/"), sig[:10] + " " + sig[10:]):
        if spelled != sig:
            assert auth.verify(secret, "auth", f"{body}.{spelled}") is None
    # Malformed, non-ASCII and oversized input is refused before anything is decoded.
    for bad in (None, "", "a", "a.b.c", "!!.!!", f"{body}.{'*' * 10}", "x" * 9000, "\ud800." + sig):
        assert auth.verify(secret, "auth", bad) is None


def test_state_cookie_cannot_pose_as_a_login() -> None:
    a = auth.Auth([auth.Password(lambda u, p: True)])
    a.bind("s" * 32, False)
    state = auth.sign(
        a.secret, "oauth-state", {"id": "eve", "name": "Eve", "exp": int(time.time()) + 60}
    )
    assert a.read(state) is None
