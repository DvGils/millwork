"""Error pages: the framework's own, an app's own, and the plain page before the bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

import millwork as mw
from millwork import auth, ui


def send(ws: Any, msg: dict[str, Any]) -> None:
    ws.send_text(json.dumps({"seq": 1, "msg": msg}))


def recv(ws: Any) -> dict[str, Any]:
    return json.loads(ws.receive_text())["msg"]


def texts(mount: dict[str, Any]) -> list[str]:
    return [n["props"]["content"] for n in mount["nodes"].values() if n["type"] == "Text"]


def test_unknown_paths_serve_the_shell_as_a_404() -> None:
    app = mw.App("e", public=None)  # the package's own bundle
    with TestClient(app.asgi) as client:
        r = client.get("/no/such/page")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")
        assert '"path": "/no/such/page"' in r.text


def test_an_app_sets_its_own_error_pages(tmp_path: Path) -> None:
    app = mw.App("e", public=None, bundle_dir=tmp_path)

    @app.page("/things/{id}")
    def thing(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.params["id"]))

    @thing.connect
    async def load(s: mw.Session, id: str) -> None:
        if id == "secret":
            raise auth.Forbidden()
        if id != "one":
            raise mw.NotFound(f"No thing called {id}.")

    @app.not_found
    def missing(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Text(f"Lost at {s.params['path']}: {s.params['message'] or 'nothing here'}")
        )

    @app.forbidden(title="Private")
    def private(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text(s.params["message"] or "Not for you."))

    assert app.error_pages["not_found"].title == "Page not found"
    assert app.error_pages["forbidden"].title == "Private"
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            send(ws, {"type": "hello", "path": "/elsewhere"})
            assert recv(ws)["type"] == "session"
            assert texts(recv(ws)) == ["Lost at /elsewhere: nothing here"]
            # The socket is live: the session navigates on from the error page.
            send(ws, {"type": "navigate", "path": "/things/two"})
            assert recv(ws)["args"]["title"] == "Page not found"
            assert texts(recv(ws)) == ["Lost at /things/two: No thing called two."]
            send(ws, {"type": "navigate", "path": "/things/secret"})
            assert recv(ws)["args"]["title"] == "Private"
            assert texts(recv(ws)) == ["Not for you."]
            send(ws, {"type": "navigate", "path": "/things/one"})
            recv(ws)
            assert texts(recv(ws)) == ["one"]


def test_the_default_forbidden_page_uses_the_theme_text(tmp_path: Path) -> None:
    app = mw.App("e", public=None, bundle_dir=tmp_path)

    @app.page("/vault")
    def vault(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("gold"))

    @vault.connect
    async def guard(s: mw.Session) -> None:
        raise auth.Forbidden()

    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            send(ws, {"type": "hello", "path": "/vault"})
            recv(ws)
            shown = texts(recv(ws))
            assert "No access" in shown and "You may not open this page." in shown


def test_unknown_paths_behind_auth_redirect_to_login_first(tmp_path: Path) -> None:
    def verify(username: str, password: str) -> bool:
        return False

    app = mw.App(
        "e",
        public=None,
        bundle_dir=tmp_path,
        secret="s" * 32,
        auth=auth.Auth([auth.Password(verify)]),
    )
    with TestClient(app.asgi) as client:
        r = client.get("/no/such/page", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].startswith("/_mw/login?")


def test_a_crash_in_an_app_route_is_a_themed_page(tmp_path: Path) -> None:
    app = mw.App("e", public=None, bundle_dir=tmp_path)

    async def boom(request: Request) -> PlainTextResponse:
        raise RuntimeError("no")

    app.route("/boom", boom)
    with TestClient(app.asgi, raise_server_exceptions=False) as client:
        r = client.get("/boom")
        assert r.status_code == 500
        assert "Something went wrong." in r.text and "RuntimeError" not in r.text
        assert "Content-Security-Policy" in r.headers
