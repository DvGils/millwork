"""The reverse proxy: forwarded and identity headers believed from named peers only."""

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
from millwork.proxy import TrustedProxies, _host_port


def test_trusted_proxies_parse_addresses_networks_literals_and_star() -> None:
    local = TrustedProxies(None)
    assert "127.0.0.1" in local and "::1" in local and "10.0.0.5" not in local
    assert "" not in local
    named = TrustedProxies("10.0.0.5, 10.1.0.0/16,testclient")
    assert "10.0.0.5" in named and "10.1.200.3" in named and "testclient" in named
    assert "10.2.0.1" not in named and "127.0.0.1" not in named
    assert "anything" in TrustedProxies("*") and None in TrustedProxies(["*"])
    assert "127.0.0.1" not in TrustedProxies([])
    # A unix socket has no peer address: local by default, otherwise only "*".
    assert None in local and None not in named and None not in TrustedProxies([])
    assert None in TrustedProxies("unix, 10.0.0.5") and "10.0.0.5" in TrustedProxies(
        "unix,10.0.0.5"
    )
    for bad in ("10.0.0.0/33", "300.1.1.1", "10.0.0", "1.2.3.4.5", "10.0.0.0/x"):
        with pytest.raises(ValueError):
            TrustedProxies([bad])
    assert "10.1.2.3" in TrustedProxies(["10.1.2.3/16"])


def test_the_visitor_is_the_last_hop_that_is_not_a_proxy() -> None:
    proxies = TrustedProxies(["10.0.0.5", "10.0.0.6"])
    assert proxies.visitor("1.2.3.4, 10.0.0.6, 10.0.0.5") == ("1.2.3.4", 0)
    assert proxies.visitor("9.9.9.9, 1.2.3.4:5000, 10.0.0.5") == ("1.2.3.4", 5000)
    assert proxies.visitor("10.0.0.6, 10.0.0.5") == ("10.0.0.6", 0)
    assert proxies.visitor("[2001:db8::1]:443, 10.0.0.5") == ("2001:db8::1", 443)
    assert TrustedProxies("*").visitor("1.1.1.1, 2.2.2.2") == ("1.1.1.1", 0)
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


FORWARDED = {"x-forwarded-for": "1.2.3.4", "x-forwarded-proto": "https"}


def test_a_trusted_proxy_is_seen_through_and_an_unknown_peer_is_not(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path, proxies=["testclient"]).asgi) as client:
        assert client.get("/who").json() == {
            "peer": "testclient",
            "scheme": "http",
            "proxied": True,
        }
        seen = client.get("/who", headers=FORWARDED).json()
        assert seen == {"peer": "1.2.3.4", "scheme": "https", "proxied": True}
        # The connecting address is what the session caps count.
        with client.websocket_connect("/_mw/ws", headers=FORWARDED) as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
            info = json.loads(ws.receive_text())["msg"]
            session = client.app.app.state.millwork.sessions[info["id"]]
            assert session.client == "addr:1.2.3.4"
    with TestClient(make_app(tmp_path, proxies=["10.0.0.5"]).asgi) as client:
        seen = client.get("/who", headers=FORWARDED).json()
        assert seen == {"peer": "testclient", "scheme": "http", "proxied": False}
    with TestClient(make_app(tmp_path).asgi) as client:
        assert client.get("/who", headers=FORWARDED).json()["proxied"] is False
    with TestClient(make_app(tmp_path, proxies="*").asgi) as client:
        assert client.get("/who", headers=FORWARDED).json()["peer"] == "1.2.3.4"
    # The list is read per connection, so it can change after the app is built.
    app = make_app(tmp_path, proxies=["10.0.0.5"])
    with TestClient(app.asgi) as client:
        assert client.get("/who", headers=FORWARDED).json()["proxied"] is False
        app.proxies = ["testclient"]
        assert client.get("/who", headers=FORWARDED).json()["proxied"] is True
    with pytest.raises(ValueError):
        make_app(tmp_path, proxies="10.0.0.0/33")


def test_a_unix_socket_peer_is_local_by_default(tmp_path: Path) -> None:
    from starlette.testclient import _TestClientTransport

    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        transport = client._transport
        assert isinstance(transport, _TestClientTransport)
        transport.client = None  # type: ignore[assignment]
        assert client.get("/who").json() == {"peer": None, "scheme": "http", "proxied": True}
    app = make_app(tmp_path, proxies=["10.0.0.5"])
    with TestClient(app.asgi) as client:
        client._transport.client = None  # type: ignore[attr-defined]
        assert client.get("/who").json()["proxied"] is False


def test_a_bad_forwarded_proto_or_empty_for_changes_nothing(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path, proxies="*").asgi) as client:
        seen = client.get(
            "/who", headers={"x-forwarded-proto": "javascript", "x-forwarded-for": ""}
        )
        assert seen.json() == {"peer": "testclient", "scheme": "http", "proxied": True}


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


def test_identity_headers_are_read_only_from_a_trusted_proxy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    headers = {
        "x-auth-request-user": "ada",
        "x-auth-request-email": "Ada@Example.COM",
        "x-auth-request-preferred-username": b"Ada Lovelace".decode("latin-1"),
        "x-auth-request-groups": "staff, admins,,",
        "x-auth-request-picture": "https://pics.example/ada.png",
    }
    app = auth_app(tmp_path, auth.Headers(**PROVIDER), proxies=["testclient"])
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
        # The page boot carries the proxy's sign-out URL on the user.
        assert client.get("/", headers=headers, follow_redirects=False).status_code == 503
    with caplog.at_level(logging.WARNING, logger="millwork.auth"):
        app = auth_app(tmp_path, auth.Headers(**PROVIDER), proxies=["10.0.0.5"])
        with TestClient(app.asgi) as client:
            assert client.get("/me", headers=headers).json() is None
            assert client.get("/me", headers=headers).json() is None
            r = client.get("/", headers=headers, follow_redirects=False)
            assert r.status_code == 302 and "/_mw/login" in r.headers["location"]
    warnings = [r.message for r in caplog.records if "not a trusted proxy" in r.message]
    assert len(warnings) == 1 and "testclient" in warnings[0]


def test_header_values_are_normalised_and_odd_ones_ignored() -> None:
    provider = auth.Headers(user="Remote-User", email="Remote-Email", groups="Remote-Groups")
    ident = provider.identity({"remote-user": "  ada  ", "remote-groups": "a,b"})
    assert ident is not None and ident.subject == "ada" and ident.email is None
    assert ident.raw == {"user": "ada", "groups": ["a", "b"]}
    ident = provider.identity({"remote-user": "Ada@Example.com"})
    assert (
        ident is not None
        and ident.email == "ada@example.com"
        and ident.subject == "Ada@Example.com"
    )
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


def test_sign_out_goes_through_the_proxy(tmp_path: Path) -> None:
    (tmp_path / ".vite").mkdir()
    (tmp_path / ".vite" / "manifest.json").write_text(
        json.dumps({"index.html": {"file": "main.js", "isEntry": True, "css": ["main.css"]}})
    )
    headers = {"x-auth-request-user": "ada"}
    app = auth_app(tmp_path, auth.Headers(**PROVIDER), proxies=["testclient"])
    with TestClient(app.asgi) as client:
        html = client.get("/", headers=headers).text
        assert '"sign_out": "/oauth2/sign_out"' in html or '"sign_out":"/oauth2/sign_out"' in html
        login = client.get("/_mw/login").text
        assert '"proxied": true' in login or '"proxied":true' in login
        assert '"providers": []' in login or '"providers":[]' in login
        # Logout still ends the person's sessions on this process.
        with client.websocket_connect("/_mw/ws", headers=headers) as ws:
            ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
            info = json.loads(ws.receive_text())["msg"]
            assert client.post("/_mw/auth/logout", headers=headers).json() == {"ok": True}
            ws.receive_text()  # the mount
            ended = json.loads(ws.receive_text())["msg"]
            assert ended["type"] == "error" and ended["message"] == "Signed out."
        assert info["id"] not in app.sessions
    app = auth_app(tmp_path, auth.Headers(user="X-Auth-Request-User"), proxies=["testclient"])
    with TestClient(app.asgi) as client:
        html = client.get("/", headers=headers).text
        assert '"sign_out": null' in html or '"sign_out":null' in html
    with TestClient(
        make_app(tmp_path, secret="s" * 32, auth=auth.Auth([auth.Password(lambda u, p: True)])).asgi
    ) as client:
        creds = {"username": "a@example.com", "password": "b"}
        r = client.post("/_mw/auth/login", json=creds)
        assert r.status_code == 200
        html = client.get("/").text
        start = html.index("window.__mw = ") + len("window.__mw = ")
        boot = json.loads(html[start : html.index(";</script>", start)])
        assert boot["user"]["id"] == "a@example.com" and "sign_out" not in boot["user"]
    # A cookie user next to a Headers provider keeps millwork's own sign-out.
    mixed = auth.Auth([auth.Headers(**PROVIDER), auth.Password(lambda u, p: True)])
    with TestClient(make_app(tmp_path, secret="s" * 32, auth=mixed).asgi) as client:
        assert client.post("/_mw/auth/login", json=creds).status_code == 200
        html = client.get("/").text
        start = html.index("window.__mw = ") + len("window.__mw = ")
        boot = json.loads(html[start : html.index(";</script>", start)])
        assert "sign_out" not in boot["user"]


def test_the_cli_hands_the_proxies_to_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    from millwork.cli import load_app, main

    (tmp_path / "demo.py").write_text("import millwork as mw\napp = mw.App('demo', public=None)\n")
    load_app(str(tmp_path / "demo.py"), proxies="10.0.0.5")
    import demo  # type: ignore[import-not-found]

    assert demo.app.proxies == "10.0.0.5"
    configs: list[uvicorn.Config] = []
    monkeypatch.setattr(
        uvicorn.Server, "run", lambda self, sockets=None: configs.append(self.config)
    )
    assert main(["run", str(tmp_path / "demo.py"), "--proxy", "*"]) == 0
    assert configs[0].proxy_headers is False
    assert sys.modules["demo"].app.proxies == "*"
    # The reload path goes through the environment and the factory.
    monkeypatch.setenv("MILLWORK_TARGET", str(tmp_path / "demo.py"))
    monkeypatch.setenv("MILLWORK_PROXY", "10.0.0.5")
    from millwork.cli import asgi_factory

    asgi_factory()
    assert sys.modules["demo"].app.proxies == "10.0.0.5"
    assert main(["run", str(tmp_path / "demo.py"), "--proxy", "300.1.1.1"]) != 0
