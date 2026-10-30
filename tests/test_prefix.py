"""Running under a path prefix: every URL the server writes is under it, every
path inside the app is not, and the prefix comes from the ASGI scope alone."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

import millwork as mw
from millwork import auth, ui

THEME = {
    "fonts": [{"family": "Inter", "src": "/public/fonts/Inter.woff2", "weights": "100 900"}],
    "logo": {"light": "/public/logo.svg", "dark": "/public/logo-dark.svg"},
    "favicon": "/public/favicon.svg",
    "login_image": "/public/login.jpg",
}


def send(ws: Any, msg: dict[str, Any]) -> None:
    ws.send_text(json.dumps({"seq": 1, "msg": msg}))


def recv(ws: Any) -> dict[str, Any]:
    return json.loads(ws.receive_text())["msg"]


def boot_of(html: str) -> dict[str, Any]:
    start = html.index("window.__mw = ") + len("window.__mw = ")
    return json.loads(html[start : html.index(";</script>", start)])


def make_app(tmp_path: Path, **kw: Any) -> mw.App:
    (tmp_path / "theme.json").write_text(json.dumps(THEME))
    app = mw.App("p", public=None, theme=tmp_path / "theme.json", **kw)

    @app.page("/", title="Home")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Link(label="go", href="/other", key="go"))

    @app.page("/other", title="Other")
    def other(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("other", key="t"))

    return app


def test_the_shell_puts_every_url_under_the_prefix(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi, root_path="/sales") as client:
        # The TestClient scope carries root_path without touching the path, so the
        # page is reached with and without the prefix in the path. uvicorn itself
        # prepends the prefix, which is why the proxy strips it.
        for url in ("/sales/", "/"):
            r = client.get(url)
            assert r.status_code == 200, url
            html = r.text
            assert "/sales/_mw/assets/" in html
            assert '<link rel="icon" href="/sales/public/favicon.svg">' in html
            assert "url(/sales/public/fonts/Inter.woff2)" in html
            boot = boot_of(html)
            assert boot["base"] == "/sales" and boot["ws"] == "/sales/_mw/ws"
            assert boot["path"] == "/"  # the app's own path, never the browser's
            # Image paths stay the app's own: the bundle maps them as it renders.
            assert boot["theme"]["logo"] == {
                "light": "/public/logo.svg",
                "dark": "/public/logo-dark.svg",
            }
            assert boot["theme"]["login_image"] == "/public/login.jpg"
        # Nothing of the prefix leaks into the app's view of a path.
        r = client.get("/sales/nope")
        assert r.status_code == 404 and boot_of(r.text)["path"] == "/nope"
        assert client.get("/sales/favicon.ico", follow_redirects=False).headers["location"] == (
            "/sales/public/favicon.svg"
        )


def test_without_a_prefix_nothing_changes(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        boot = boot_of(client.get("/").text)
        assert boot["base"] == "" and boot["ws"] == "/_mw/ws"
        assert boot["theme"]["logo"]["light"] == "/public/logo.svg"


def test_the_prefix_comes_from_the_server_not_a_header(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client:
        headers = {"X-Forwarded-Prefix": "/evil", "X-Script-Name": "/evil"}
        html = client.get("/", headers=headers).text
        assert boot_of(html)["base"] == "" and "/evil" not in html


def test_the_session_speaks_app_paths_under_a_prefix(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi, root_path="/sales") as client:
        with client.websocket_connect("/sales/_mw/ws") as ws:
            send(ws, {"type": "hello", "path": "/"})
            info = recv(ws)
            assert info["type"] == "session"
            mount = recv(ws)
            assert mount["nodes"]["root/go"]["props"]["href"] == "/other"
            send(ws, {"type": "navigate", "path": "/other"})
            assert recv(ws)["args"] == {"path": "/other", "title": "Other"}
            session = app.sessions[info["id"]]
            assert session.path == "/other" and session.base == "/sales"


def test_auth_redirects_and_callbacks_are_under_the_prefix(tmp_path: Path) -> None:
    def on_login(identity: auth.Identity) -> auth.User:
        return auth.User(id=identity.subject, name=identity.subject)

    app = make_app(
        tmp_path,
        secret="s" * 32,
        auth=auth.Auth(
            [auth.Password(lambda u, p: u == "demian" and p == "pw")], on_login=on_login
        ),
    )
    with TestClient(app.asgi, root_path="/sales") as client:
        r = client.get("/sales/other", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/sales/_mw/login?next=%2Fother"
        login = client.get("/sales/_mw/login?next=/other")
        boot = boot_of(login.text)
        assert boot["base"] == "/sales" and boot["login"]["next"] == "/other"
        r = client.post("/sales/_mw/auth/login", json={"username": "demian", "password": "pw"})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"]
        assert "Path=/sales" in cookie
        r = client.post("/sales/_mw/auth/logout")
        assert "Path=/sales" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    # The OAuth callback URL carries the prefix once, through base_url.
    provider = auth.OAuth(
        id="fake",
        label="Fake",
        client_id="c",
        client_secret="s",
        authorize_url="https://idp.example/authorize",
        token_url="https://idp.example/token",
        userinfo_url="https://idp.example/me",
        scopes=["openid"],
    )
    a = auth.Auth([provider])
    a.bind("s" * 32, False)
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "server": ("apps.example", 443),
        "root_path": "/sales",
        "path": "/sales/_mw/auth/oauth/fake",
        "query_string": b"",
        "headers": [(b"host", b"apps.example")],
    }
    assert a._callback_url(Request(scope), provider) == (
        "https://apps.example/sales/_mw/auth/oauth/fake/callback"
    )
    # Under a Starlette Mount the outer app's root is "", and base_url would say
    # so; the callback follows the scope's own root_path.
    assert a._callback_url(Request({**scope, "app_root_path": ""}), provider) == (
        "https://apps.example/sales/_mw/auth/oauth/fake/callback"
    )
    assert a._login_redirect(Request(scope), "/x", "e").headers["location"] == (
        "/sales/_mw/login?next=%2Fx&error=e"
    )
    # The OAuth state cookie is scoped to the prefix like the auth cookie.
    with TestClient(
        mw.App("o", public=None, secret="s" * 32, auth=a).asgi, root_path="/sales"
    ) as c:
        r = c.get("/sales/_mw/auth/oauth/fake?next=/x", follow_redirects=False)
        assert r.status_code == 302 and "Path=/sales" in r.headers["set-cookie"]


def test_plain_pages_and_theme_reloads_know_the_prefix(tmp_path: Path) -> None:
    (tmp_path / "nobundle").mkdir()
    app = make_app(tmp_path, bundle_dir=tmp_path / "nobundle")
    with TestClient(app.asgi, root_path="/sales") as client:
        r = client.get("/sales/nope")
        assert r.status_code == 404 and 'href="/sales/"' in r.text
        assert "url(/sales/public/fonts/Inter.woff2)" in r.text
    assert app.theme.css("/sales").startswith("@font-face{font-family:'Inter';src:url(/sales/")
    assert app.theme.boot()["login_image"] == "/public/login.jpg"


def test_next_cannot_leave_the_prefix_or_reach_a_framework_route() -> None:
    from millwork.auth import _safe_next

    for bad in (
        "/../evil",
        "/a/../evil",
        "/%2e%2e/evil",
        "/%2E%2E/evil",
        "/..//evil.example",
        "/./_mw/auth/oauth/x",
        "/_mw/login",
        "/_mw",
        "//evil.example",
        "/\\evil.example",
        "",
        None,
        "https://evil.example/",
    ):
        assert _safe_next(bad) == "/", bad
    for good in ("/", "/other", "/a.b/c..d/.hidden", "/a?x=/../y#z", "/_mwx", "/publication"):
        assert _safe_next(good) == good, good


def test_the_prefix_itself_is_validated() -> None:
    from millwork.cli import main
    from millwork.shell import check_prefix, root_of

    assert check_prefix("") == "" and check_prefix("/sales") == "/sales"
    assert check_prefix("/sales/") == "/sales" and check_prefix("/a/b.c") == "/a/b.c"
    for bad in ('/sa"les', "/sales<b>", "/x/../y", "/./x", "sales", "/sa les", "/x)", "//x"):
        with pytest.raises(ValueError):
            check_prefix(bad)
    assert root_of({"root_path": "/sales/"}) == "/sales" and root_of({}) == ""
    with pytest.raises(ValueError):
        root_of({"root_path": '/sa"les'})
    assert main(["run", "app.py", "--root-path", '/sa"les']) == 2
