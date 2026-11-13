"""Auth: pages gated, password and OAuth flows, the websocket bound to the cookie, intents."""

import asyncio
import contextlib
import datetime as dt
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
from millwork.nodes import build


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


def two_ways(**kw: Any) -> auth.Auth:
    return auth.Auth(
        [
            auth.AzureAD(tenant="t", client_id="c", client_secret="x"),
            auth.Password(lambda username, password: True),
        ],
        intents={"demo": "Try the demo"},
        **kw,
    )


def laid_out(described: dict[str, Any]) -> list[tuple[str, Any]]:
    """The login page's nodes in the order they are drawn, as (type, what it shows)."""
    nodes = described["nodes"]
    out: list[tuple[str, Any]] = []

    def walk(node_id: str) -> None:
        node = nodes[node_id]
        props = node["props"]
        if node["type"] == "SignIn":
            out.append(("SignIn", (props["provider"], props.get("intent"), props["label"])))
        elif node["type"] != "Stack":
            out.append((node["type"], props.get("label") or props.get("content")))
        for child in node["children"]:
            walk(child)

    walk(described["root"])
    return out


def test_the_login_page_offers_every_way_in_with_a_line_between() -> None:
    described = two_ways().describe("/next", either="of")
    assert laid_out(described) == [
        ("SignIn", ("azure-ad", None, None)),
        ("SignIn", ("azure-ad", "demo", "Try the demo")),
        ("Separator", "of"),
        ("SignIn", ("password", None, None)),
    ]
    button = next(n for n in described["nodes"].values() if n["type"] == "SignIn")
    assert button["props"]["kind"] == "oauth" and button["props"]["name"] == "Microsoft"
    assert button["props"]["icon"] == "microsoft"
    assert described["next"] == "/next"
    # The form goes with the provider that checks passwords, whatever an
    # OAuth provider is called.
    named = auth.Auth(
        [
            auth.OAuth(
                "password",
                label="Vault",
                authorize_url="https://idp/a",
                token_url="https://idp/t",
                userinfo_url="https://idp/u",
                client_id="c",
                client_secret="s",
                scopes="openid",
            )
        ]
    ).describe("/")
    assert [n["props"]["kind"] for n in named["nodes"].values() if n["type"] == "SignIn"] == [
        "oauth"
    ]
    # One way in needs no line, and none at all is an empty page.
    only = auth.Auth([auth.Password(lambda u, p: True)]).describe("/")
    assert laid_out(only) == [("SignIn", ("password", None, None))]
    assert laid_out(auth.Auth([]).describe("/")) == []


def test_an_app_lays_its_login_page_out_itself() -> None:
    page = ui.Stack(
        ui.Text("Partners"),
        ui.SignIn("password", label="Sign in as a partner"),
        ui.Separator(label="or"),
        ui.Text("Staff"),
        ui.SignIn("azure-ad"),
        ui.SignIn("azure-ad", intent="demo", label="Look around"),
    )
    assert laid_out(two_ways(login=page).describe("/")) == [
        ("Text", "Partners"),
        ("SignIn", ("password", None, "Sign in as a partner")),
        ("Separator", "or"),
        ("Text", "Staff"),
        ("SignIn", ("azure-ad", None, None)),
        ("SignIn", ("azure-ad", "demo", "Look around")),
    ]


def test_a_login_page_that_cannot_be_drawn_is_refused_at_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(ValueError, match="names no provider.*the app has azure-ad, password"):
        two_ways(login=ui.SignIn("github"))
    with pytest.raises(ValueError, match="not one of Auth\\(intents=\\): demo"):
        two_ways(login=ui.SignIn("azure-ad", intent="trial"))
    with pytest.raises(ValueError, match="an intent goes with an OAuth provider"):
        two_ways(login=ui.SignIn("password", intent="demo"))
    # Nothing on the page can call Python: there is no session before sign-in.
    with pytest.raises(ValueError, match="no session, so Button's click cannot run there"):
        two_ways(login=ui.Stack(ui.SignIn("password"), ui.Button("Help", on_click=print)))
    # Nor can it hold what only talks to Python, handler or not.
    for bound in (
        ui.Download("Get", filename="a.txt", content=b"abc"),
        ui.Chat(key="c"),
        ui.FileUpload(key="f"),
    ):
        with pytest.raises(ValueError, match="does nothing without one"):
            two_ways(login=ui.Stack(ui.SignIn("password"), bound))
    with pytest.raises(TypeError, match="takes one component, a ui.Stack of them for several"):
        two_ways(login=[ui.SignIn("password")])  # type: ignore[arg-type]
    # A provider left off the page is said once, since it may be a slip.
    with caplog.at_level("WARNING", logger="millwork.auth"):
        two_ways(login=ui.SignIn("azure-ad"))
    assert "no ui.SignIn('password')" in caplog.text
    # Outside an app with auth there is no provider to draw.
    with pytest.raises(ValueError, match="needs an app with auth"):
        build(ui.SignIn("password"))


def test_a_provider_shows_a_brand_an_image_or_an_icon() -> None:
    def provider(icon: str | None) -> auth.OAuth:
        return auth.OAuth(
            "x",
            label="X",
            authorize_url="https://idp/a",
            token_url="https://idp/t",
            userinfo_url="https://idp/u",
            client_id="c",
            client_secret="s",
            scopes="openid",
            icon=icon,
        )

    for icon in (None, "google", "microsoft", "/public/okta.svg", "lock"):
        assert provider(icon).icon == icon
    assert auth.Google(client_id="c", client_secret="s").icon == "google"
    with pytest.raises(ValueError, match="no icon named 'octocat'"):
        provider("octocat")
    with pytest.raises(ValueError, match="same-origin path"):
        provider("//evil.example/x.svg")


async def test_a_public_page_can_hold_a_sign_in(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    app = make_app(tmp_path)

    @app.page("/welcome", public=True)
    def welcome(s: mw.Session) -> ui.Component:
        return ui.Page(ui.SignIn("fake", key="in"))

    async with TestApp(app).open("/welcome") as page:
        props = page.find("in").props
        assert props["kind"] == "oauth" and props["name"] == "Fake IdP"


def sign_in_for(app: mw.App, client: TestClient, user: auth.User, lifetime: float) -> None:
    """Put a sign-in for ``user`` that lasts ``lifetime`` seconds in the client's jar."""
    usual, app.auth.session = app.auth.session, dt.timedelta(seconds=lifetime)
    try:
        client.cookies.set("mw_auth", app.auth.issue(user), domain="testserver.local")
    finally:
        app.auth.session = usual


def opened(ws: Any, path: str = "/") -> str:
    """Open a page on a socket, past its mount, and return the session's id."""
    info = ws_hello(ws, path)
    assert info["type"] == "session"
    ws.receive_text()
    return info["id"]


def left_for(ws: Any) -> str:
    """The destination a tab is sent to as its session ends."""
    left = json.loads(ws.receive_text())["msg"]
    assert left["type"] == "command" and left["name"] == "leave"
    ended = json.loads(ws.receive_text())["msg"]
    assert ended["type"] == "error" and ended["fatal"] is True
    return left["args"]["to"]


def settled(app: mw.App, ids: list[str]) -> bool:
    """Whether the app is left with exactly these sessions, given a moment:
    a session is dropped just after its tab hears that it ended."""
    deadline = time.monotonic() + 2
    while sorted(app.sessions) != sorted(ids) and time.monotonic() < deadline:
        time.sleep(0.01)
    return sorted(app.sessions) == sorted(ids)


def test_a_session_ends_when_its_sign_in_runs_out(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    asked: list[str] = []

    async def on_logout(user: auth.User) -> str | None:
        asked.append(user.id)
        if user.id == "cy":
            # A hook that is cancelled from within, the failure an except
            # clause for ordinary errors does not see.
            raise asyncio.CancelledError
        return "/terms" if user.id == "bob" else None

    app.auth.on_logout = on_logout
    ada, bob, cy = (
        auth.User(id=i, name=i.title(), claims={"projects": []}) for i in "ada bob cy".split()
    )
    with TestClient(app.asgi) as client, contextlib.ExitStack() as tabs:

        def tab(path: str = "/") -> tuple[Any, str]:
            # A socket carries the sign-in the jar holds as it connects.
            ws = tabs.enter_context(client.websocket_connect("/_mw/ws"))
            return ws, opened(ws, path)

        # Ada has two tabs on a sign-in with seconds left, one on a gated page
        # and one on a public page. Bob's hook names a destination, and Cy's
        # fails.
        sign_in_for(app, client, ada, 2)
        gated, _ = tab()
        public, _ = tab("/terms")
        sign_in_for(app, client, bob, 2)
        sent, _ = tab()
        sign_in_for(app, client, cy, 2)
        failed, _ = tab()
        # Ada signed in again in the meantime, and that sign-in lasts.
        sign_in_for(app, client, ada, 3600)
        _, kept = tab()
        # The gated tab goes to the login page and back to its page, the
        # public one reloads where it is, for a visitor.
        assert left_for(gated) == "/_mw/login?next=%2F"
        assert left_for(public) == "/terms"
        assert left_for(sent) == "/terms"
        assert left_for(failed) == "/_mw/login?next=%2F"
        # Asked once for Ada's two tabs, and her lasting sign-in goes on.
        assert sorted(asked) == ["ada", "bob", "cy"]
        assert settled(app, [kept])


def test_on_logout_says_where_the_tab_goes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path)
    seen: list[str] = []

    def sign_in(client: TestClient) -> None:
        r = client.post("/_mw/auth/login", json={"username": "demian", "password": "pw"})
        assert r.status_code == 200

    with TestClient(app.asgi) as client:
        # No hook: the login page, which the tab knows on its own.
        sign_in(client)
        assert client.post("/_mw/auth/logout").json() == {"ok": True, "next": None}

        def to_terms(user: auth.User) -> str:
            seen.append(user.id)
            return "/terms"

        app.auth.on_logout = to_terms
        sign_in(client)
        assert client.post("/_mw/auth/logout").json() == {"ok": True, "next": "/terms"}
        assert seen == ["demian"]
        assert client.get("/", follow_redirects=False).status_code == 302
        # Nobody signed in: nobody to ask about.
        assert client.post("/_mw/auth/logout").json()["next"] is None
        assert seen == ["demian"]

        async def elsewhere(user: auth.User) -> str:
            return "https://example.com/bye"

        app.auth.on_logout = elsewhere
        sign_in(client)
        assert client.post("/_mw/auth/logout").json()["next"] == "https://example.com/bye"

        # A hook that fails, or answers with something that is no destination,
        # is logged, and the person is signed out to the login page all the same.
        def broken(user: auth.User) -> str:
            raise RuntimeError("no database")

        async def stuck(user: auth.User) -> str:
            await asyncio.sleep(60)
            return "/terms"

        monkeypatch.setattr(auth, "LOGOUT_HOOK_TIMEOUT", 0.05)
        for hook, said in (
            (broken, "on_logout failed"),
            (stuck, "on_logout took over"),
            (lambda user: "//evil.example", "on_logout returns a path"),
            (lambda user: "/a/%2e%2e/b", "on_logout returns a path"),
            (lambda user: 5, "on_logout returns a path"),
        ):
            app.auth.on_logout = hook  # type: ignore[assignment]
            sign_in(client)
            caplog.clear()
            assert client.post("/_mw/auth/logout").json() == {"ok": True, "next": None}
            assert said in caplog.text
            assert client.get("/", follow_redirects=False).status_code == 302


def test_a_tab_that_comes_back_follows_the_newer_sign_in(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    ada = auth.User(id="ada", name="Ada", claims={"projects": []})
    with TestClient(app.asgi) as client:
        sign_in_for(app, client, ada, 600)
        with client.websocket_connect("/_mw/ws") as ws:
            info = ws_hello(ws)
            ws.receive_text()
            session = app.sessions[info["id"]]
            first, old_timer = session.sign_in, session._expiry
            assert first is not None and old_timer is not None
            assert 0 < session.sign_in_expires - time.time() <= 600
        # Signed in again while the tab was away: the session it resumes now
        # ends with the new sign-in, and the old one's timer is gone.
        sign_in_for(app, client, ada, 7200)
        resume = {"session": info["id"], "resume": info["resume"], "seq": 2}
        with client.websocket_connect("/_mw/ws") as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/", **resume}}))
            assert json.loads(ws.receive_text())["msg"]["id"] == info["id"]
            assert session.sign_in not in (None, first)
            assert session.sign_in_expires - time.time() > 7000
            assert not old_timer.pending and session._expiry is not old_timer
            assert session._expiry._handle.when() - session._loop.time() > 7000
        # A visitor on a public page has no sign-in to run out.
        client.cookies.clear()
        with client.websocket_connect("/_mw/ws") as ws:
            visitor = ws_hello(ws, "/terms")["id"]
            ws.receive_text()
            assert app.sessions[visitor].sign_in is None
            assert app.sessions[visitor]._expiry is None


def test_only_the_apps_own_pages_can_sign_someone_out(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    asked: list[str] = []
    app.auth.on_logout = lambda user: asked.append(user.id)
    with TestClient(app.asgi) as client:
        client.post("/_mw/auth/login", json={"username": "demian", "password": "pw"})
        r = client.post("/_mw/auth/logout", headers={"origin": "https://evil.example"})
        assert r.status_code == 400 and "set-cookie" not in r.headers
        assert asked == [] and client.get("/", follow_redirects=False).status_code == 503
        r = client.post("/_mw/auth/logout", headers={"origin": "http://testserver"})
        assert r.status_code == 200 and asked == ["demian"]
        assert client.get("/", follow_redirects=False).status_code == 302


def test_an_intent_has_a_button_for_each_provider_that_names_it() -> None:
    two = auth.Auth(
        [
            auth.AzureAD(tenant="t", client_id="c", client_secret="x"),
            auth.Google(client_id="g", client_secret="y"),
        ],
        intents={"demo": "Try the demo"},
    )
    described = two.describe("/", either="or")
    assert laid_out(described) == [
        ("SignIn", ("azure-ad", None, None)),
        ("SignIn", ("google", None, None)),
        ("SignIn", ("azure-ad", "demo", "Try the demo")),
        ("SignIn", ("google", "demo", "Try the demo")),
    ]
    buttons = [n["props"] for n in described["nodes"].values() if n["type"] == "SignIn"]
    # With two ways through, the intent's words alone would be on two buttons.
    assert [(b["name"], b["with_provider"]) for b in buttons if b.get("intent")] == [
        ("Microsoft", True),
        ("Google", True),
    ]
    assert not any(b["with_provider"] for b in buttons if not b.get("intent"))
    # One provider needs no naming, and words of the app's own are left alone.
    one = two_ways().describe("/", either="or")
    alone = [n["props"] for n in one["nodes"].values() if n["type"] == "SignIn"]
    assert not any(b["with_provider"] for b in alone)
    own = auth.Auth(
        [
            auth.AzureAD(tenant="t", client_id="c", client_secret="x"),
            auth.Google(client_id="g", client_secret="y"),
        ],
        intents={"demo": "Try the demo"},
        login=ui.SignIn("google", intent="demo", label="Look around"),
    ).describe("/", either="or")
    (button,) = [n["props"] for n in own["nodes"].values() if n["type"] == "SignIn"]
    assert button["label"] == "Look around" and not button["with_provider"]
