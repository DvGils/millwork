"""Behind a reverse proxy: one switch decides whether its headers are believed."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import millwork as mw
from millwork import auth, ui
from millwork.proxy import _host_port


def test_forwarded_values_parse() -> None:
    assert _host_port("1.2.3.4") == ("1.2.3.4", 0)
    assert _host_port("1.2.3.4:5000") == ("1.2.3.4", 5000)
    assert _host_port("[2001:db8::1]:443") == ("2001:db8::1", 443)
    assert _host_port("[2001:db8::1]") == ("2001:db8::1", 0)
    assert _host_port("2001:db8::1") == ("2001:db8::1", 0)
    assert _host_port("host:x") == ("host:x", 0)


def make_app(tmp_path: Path, **kw: Any) -> mw.App:
    app = mw.App("p", public=None, bundle_dir=tmp_path, **kw)

    async def who(request: Request) -> JSONResponse:
        client = request.client
        return JSONResponse(
            {
                "peer": client.host if client else None,
                "scheme": request.url.scheme,
                "proxied": request.scope.get("millwork.proxied"),
            }
        )

    app.route("/who", who)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("hi", key="t"))

    return app


# The browser may send its own X-Forwarded-For; the proxy appends what it saw.
FORWARDED = {"x-forwarded-for": "8.8.8.8, 1.2.3.4", "x-forwarded-proto": "https"}


def test_the_switch_decides_whether_forwarded_headers_count(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path, proxied=True).asgi) as client:
        plain = client.get("/who").json()
        assert plain == {"peer": "testclient", "scheme": "http", "proxied": True}
        seen = client.get("/who", headers=FORWARDED).json()
        assert seen == {"peer": "1.2.3.4", "scheme": "https", "proxied": True}
        # The forwarded address is what the session caps count.
        with client.websocket_connect("/_mw/ws", headers=FORWARDED) as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
            info = json.loads(ws.receive_text())["msg"]
            session = client.app.app.state.millwork.sessions[info["id"]]
            assert session.client == "addr:1.2.3.4"
    with TestClient(make_app(tmp_path).asgi) as client:
        seen = client.get("/who", headers=FORWARDED).json()
        assert seen == {"peer": "testclient", "scheme": "http", "proxied": False}
    # The switch is read per connection, so the CLI can set it after the build.
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        assert client.get("/who", headers=FORWARDED).json()["proxied"] is False
        app.proxied = True
        assert client.get("/who", headers=FORWARDED).json()["peer"] == "1.2.3.4"


def test_odd_forwarded_values_change_nothing(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path, proxied=True).asgi) as client:
        odd = {"x-forwarded-proto": "javascript", "x-forwarded-for": ""}
        seen = client.get("/who", headers=odd)
        assert seen.json() == {"peer": "testclient", "scheme": "http", "proxied": True}


def test_a_proxy_that_sends_no_address_is_said_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = make_app(tmp_path, proxied=True)
    with caplog.at_level(logging.WARNING), TestClient(app.asgi) as client:
        for _ in range(2):
            with client.websocket_connect("/_mw/ws") as ws:
                ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
                ws.receive_text()
    assert len([r for r in caplog.records if "sends no X-Forwarded-For" in r.message]) == 1


def auth_app(tmp_path: Path, provider: auth.Headers, **kw: Any) -> mw.App:
    def on_login(identity: auth.Identity) -> auth.User | None:
        if identity.subject == "eve":
            return None
        return auth.User(
            id=identity.subject,
            name=identity.name or identity.subject,
            claims={"groups": identity.raw.get("groups", []), "email": identity.email},
            picture_url=identity.picture_url,
        )

    app = make_app(tmp_path, secret="s" * 32, auth=auth.Auth([provider], on_login=on_login), **kw)

    async def me(request: Request) -> JSONResponse:
        user = await app.user_for(request)
        return JSONResponse(user.model_dump() if user else None)

    app.route("/me", me)
    return app


PROVIDER = dict(
    user="X-Auth-Request-User",
    email="X-Auth-Request-Email",
    name="X-Auth-Request-Preferred-Username",
    groups="X-Auth-Request-Groups",
    picture="X-Auth-Request-Picture",
    sign_out="/oauth2/sign_out",
)


def test_identity_headers_are_read_only_behind_a_proxy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    headers = {
        "x-auth-request-user": "ada",
        "x-auth-request-email": "Ada@Example.COM",
        "x-auth-request-preferred-username": b"Ada Lovelace".decode("latin-1"),
        "x-auth-request-groups": "staff, admins,,",
        "x-auth-request-picture": "https://pics.example/ada.png",
    }
    app = auth_app(tmp_path, auth.Headers(**PROVIDER), proxied=True)
    with TestClient(app.asgi) as client:
        me = client.get("/me", headers=headers).json()
        assert me == {
            "id": "ada",
            "name": "Ada Lovelace",
            "claims": {"groups": ["staff", "admins"], "email": "ada@example.com"},
            "picture_url": "https://pics.example/ada.png",
        }
        assert client.get("/me").json() is None
        assert client.get("/me", headers={"x-auth-request-user": "eve"}).json() is None
        assert client.get("/", headers=headers, follow_redirects=False).status_code == 503
    with caplog.at_level(logging.WARNING, logger="millwork.auth"):
        app = auth_app(tmp_path, auth.Headers(**PROVIDER))
        with TestClient(app.asgi) as client:
            assert client.get("/me", headers=headers).json() is None
            assert client.get("/me", headers=headers).json() is None
            r = client.get("/", headers=headers, follow_redirects=False)
            assert r.status_code == 302 and "/_mw/login" in r.headers["location"]
    warnings = [r.message for r in caplog.records if "not marked as behind a proxy" in r.message]
    assert len(warnings) == 1


def test_header_values_are_normalised_and_odd_ones_ignored() -> None:
    provider = auth.Headers(user="Remote-User", email="Remote-Email", groups="Remote-Groups")
    ident = provider.identity({"remote-user": "  ada  ", "remote-groups": "a,b"})
    assert ident is not None and ident.subject == "ada" and ident.email is None
    assert ident.raw == {"user": "ada", "groups": ["a", "b"]}
    ident = provider.identity({"remote-user": "Ada@Example.com"})
    assert ident is not None and ident.email == "ada@example.com"
    assert ident.subject == "Ada@Example.com"
    ident = provider.identity({"remote-email": "ADA@example.com"})
    assert ident is not None and ident.subject == "ada@example.com"
    assert provider.identity({}) is None
    assert provider.identity({"remote-user": " "}) is None
    assert provider.identity({"remote-user": "a" * 1025}) is None
    assert provider.identity({"remote-user": "ada\x7f"}) is None
    assert provider.identity({"remote-user": "José".encode().decode("latin-1")}).subject == "José"
    assert provider.present({"remote-groups": "x"}) and not provider.present({"other": "x"})
    with pytest.raises(ValueError):
        auth.Headers(name="X-Name")
    with pytest.raises(ValueError):
        auth.Headers(user="X-User", sign_out="javascript:alert(1)")
    with pytest.raises(ValueError):
        auth.Headers(user="X-User", sign_out="evil.example/out")
    for bad in ("//evil.example/out", "/\\evil.example", "/out javascript:", "https://", "/x\x7f"):
        with pytest.raises(ValueError):
            auth.Headers(user="X-User", sign_out=bad)
    # A header that arrives twice is ignored: a proxy that appends would let
    # the visitor's own value through first.
    from starlette.datastructures import Headers as H

    twice = H(raw=[(b"remote-user", b"mallory"), (b"remote-user", b"ada")])
    assert provider.identity(twice) is None
    assert provider.identity(H(raw=[(b"remote-user", b"ada")])) is not None
    assert auth.Headers(user="X-User", sign_out="https://idp.example/out").sign_out


def test_a_slow_or_broken_hook_does_not_take_the_server_down(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import threading

    where: list[str] = []
    mode = {"raise": False}

    def on_login(identity: auth.Identity) -> auth.User | None:
        where.append(threading.current_thread().name)
        if mode["raise"]:
            raise RuntimeError("directory down")
        return auth.User(id=identity.subject, name=identity.subject)

    app = make_app(
        tmp_path,
        secret="s" * 32,
        proxied=True,
        auth=auth.Auth([auth.Headers(user="X-User")], on_login=on_login),
    )
    headers = {"x-user": "ada"}
    # The error page is what a visitor sees; the test client would re-raise.
    with TestClient(app.asgi, raise_server_exceptions=False) as client:
        assert client.get("/", headers=headers, follow_redirects=False).status_code == 503
        assert where and all(name != "MainThread" for name in where)  # off the loop
        mode["raise"] = True
        with caplog.at_level(logging.ERROR):
            assert client.get("/", headers=headers).status_code == 500
            with client.websocket_connect("/_mw/ws", headers=headers) as ws:
                ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
                msg = json.loads(ws.receive_text())["msg"]
                assert msg["type"] == "error" and msg["fatal"] is True
        assert any("identity lookup failed" in r.message for r in caplog.records)


def manifest(tmp_path: Path) -> None:
    (tmp_path / ".vite").mkdir(exist_ok=True)
    (tmp_path / ".vite" / "manifest.json").write_text(
        json.dumps({"index.html": {"file": "main.js", "isEntry": True, "css": ["main.css"]}})
    )


def test_the_login_page_moves_on_or_says_why(tmp_path: Path) -> None:
    manifest(tmp_path)
    app = auth_app(tmp_path, auth.Headers(**PROVIDER), proxied=True)
    with TestClient(app.asgi) as client:
        r = client.get(
            "/_mw/login?next=/other",
            headers={"x-auth-request-user": "ada"},
            follow_redirects=False,
        )
        assert r.status_code == 302 and r.headers["location"] == "/other"
        login = boot_of(client.get("/_mw/login", headers={"x-auth-request-user": "eve"}).text)
        assert "does not admit you" in login["login"]["error"]
        login = boot_of(client.get("/_mw/login").text)
        assert login["login"]["error"] is None and login["login"]["proxied"] is True


def test_long_group_lists_are_kept_and_a_dropped_value_is_said_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = auth.Headers(user="X-User", groups="X-Groups", name="X-Name")
    groups = ",".join(f"{i:08x}-0000-0000-0000-000000000000" for i in range(60))
    assert len(groups) > 1024
    ident = provider.identity({"x-user": "ada", "x-groups": groups})
    assert ident is not None and len(ident.raw["groups"]) == 60
    with caplog.at_level(logging.WARNING, logger="millwork.auth"):
        for _ in range(3):
            ident = provider.identity({"x-user": "ada", "x-name": "n" * 2000})
        assert ident is not None and ident.name is None
    said = [r.message for r in caplog.records if "was ignored" in r.message]
    assert len(said) == 1 and "name" in said[0]


def boot_of(html: str) -> dict[str, Any]:
    start = html.index("window.__mw = ") + len("window.__mw = ")
    return json.loads(html[start : html.index(";</script>", start)])


def test_sign_out_goes_through_the_proxy(tmp_path: Path) -> None:
    manifest(tmp_path)
    headers = {"x-auth-request-user": "ada"}
    app = auth_app(tmp_path, auth.Headers(**PROVIDER), proxied=True)
    with TestClient(app.asgi) as client:
        user = boot_of(client.get("/", headers=headers).text)["user"]
        assert user["sign_out"] == "/oauth2/sign_out"
        login = boot_of(client.get("/_mw/login").text)["login"]
        assert login["proxied"] is True
        assert not any(n["type"] == "SignIn" for n in login["nodes"].values())
        # Logout still ends the person's sessions on this process.
        with client.websocket_connect("/_mw/ws", headers=headers) as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
            info = json.loads(ws.receive_text())["msg"]
            assert client.post("/_mw/auth/logout", headers=headers).json() == {"ok": True}
            ws.receive_text()  # the mount
            ended = json.loads(ws.receive_text())["msg"]
            assert ended["type"] == "error" and ended["message"] == "Signed out."
        assert info["id"] not in app.sessions
    app = auth_app(tmp_path, auth.Headers(user="X-Auth-Request-User"), proxied=True)
    with TestClient(app.asgi) as client:
        assert boot_of(client.get("/", headers=headers).text)["user"]["sign_out"] is None
    creds = {"username": "a@example.com", "password": "b"}
    own = auth.Auth([auth.Password(lambda u, p: True)])
    with TestClient(make_app(tmp_path, secret="s" * 32, auth=own).asgi) as client:
        assert client.post("/_mw/auth/login", json=creds).status_code == 200
        boot = boot_of(client.get("/").text)
        assert boot["user"]["id"] == "a@example.com" and "sign_out" not in boot["user"]
    # A cookie user next to a Headers provider keeps millwork's own sign-out.
    mixed = auth.Auth([auth.Headers(**PROVIDER), auth.Password(lambda u, p: True)])
    with TestClient(make_app(tmp_path, secret="s" * 32, auth=mixed).asgi) as client:
        assert client.post("/_mw/auth/login", json=creds).status_code == 200
        assert "sign_out" not in boot_of(client.get("/").text)["user"]


def test_the_cli_hands_the_switch_to_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    from millwork.cli import asgi_factory, load_app, main

    (tmp_path / "demo.py").write_text("import millwork as mw\napp = mw.App('demo', public=None)\n")
    load_app(str(tmp_path / "demo.py"))
    assert sys.modules["demo"].app.proxied is False
    load_app(str(tmp_path / "demo.py"), proxied=True)
    assert sys.modules["demo"].app.proxied is True
    configs: list[uvicorn.Config] = []
    record = lambda self, sockets=None: configs.append(self.config)  # noqa: E731
    monkeypatch.setattr(uvicorn.Server, "run", record)
    assert main(["run", str(tmp_path / "demo.py")]) == 0
    assert configs[0].proxy_headers is False and sys.modules["demo"].app.proxied is False
    assert main(["run", str(tmp_path / "demo.py"), "--proxied"]) == 0
    assert sys.modules["demo"].app.proxied is True
    # Reload mode goes through the environment and the factory.
    for key in ("MILLWORK_TARGET", "MILLWORK_DEBUG", "MILLWORK_PROXIED"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("MILLWORK_TARGET", str(tmp_path / "demo.py"))
    monkeypatch.setenv("MILLWORK_PROXIED", "1")
    asgi_factory()
    assert sys.modules["demo"].app.proxied is True
