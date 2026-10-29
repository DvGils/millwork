"""The application: pages on paths, the Starlette app that serves them.

Everything millwork owns lives under ``/_mw``. An app adds its own routes,
mounts and middleware through the Starlette object in ``app.asgi``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from starlette.routing import Mount, Route, WebSocketRoute, compile_path
from starlette.staticfiles import StaticFiles

from millwork import __version__
from millwork.auth import Auth
from millwork.files import Files
from millwork.nodes import Component
from millwork.protocol import Command
from millwork.shell import Shell
from millwork.theme import Theme, find_theme

# The policy for every HTML page; ``{scripts}`` becomes the page's script sources
# (the bundle and the nonce of its two inline lines). Styles stay inline because
# the theme and Tailwind's runtime inject them; images, media and frames may come
# from anywhere over https since an app shows external files and pages.
DEFAULT_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src {scripts}",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https:",
        "media-src 'self' blob: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-src 'self' blob: https:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
)


class _Assets(StaticFiles):
    """The bundle: hashed file names are cached for a year, the few unhashed ones
    (the manifest, the icons) are revalidated."""

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        path = str(args[0]) if args else str(kwargs.get("full_path", ""))
        hashed = _HASHED.search(Path(path).name) is not None
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if hashed else "no-cache"
        )
        return response


_HASHED = re.compile(r"-[A-Za-z0-9_-]{8}\.[a-z0-9]+$")


class _SecurityHeaders:
    """Headers every response carries: no sniffing, no framing elsewhere, no referrer leaks."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "SAMEORIGIN")
                headers.setdefault("Referrer-Policy", "same-origin")
            await send(message)

        await self.app(scope, receive, send_with_headers)


if TYPE_CHECKING:
    from millwork.session import Session

log = logging.getLogger("millwork.app")

PREFIX = "/_mw"
BUNDLE_DIR = Path(__file__).parent / "_bundle" / "dist"


@dataclass
class PageDef:
    path: str
    render: Callable[[Any], Component]
    title: str | None = None
    public: bool = False
    state: Callable[[], Any] | type | None = None
    on_connect: Callable[..., Any] | None = None
    on_close: Callable[..., Any] | None = None
    _regex: Any = field(init=False, repr=False)
    _param_convertors: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._regex, _, self._param_convertors = compile_path(self.path)

    def match(self, path: str) -> dict[str, str] | None:
        m = self._regex.match(path)
        if m is None:
            return None
        return {k: self._param_convertors[k].convert(v) for k, v in m.groupdict().items()}

    def make_state(self) -> Any:
        if self.state is None:
            return None
        return self.state()

    def connect(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator: the page's connect hook, ``(session, **params)``."""
        self.on_connect = fn
        return fn

    def close(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self.on_close = fn
        return fn


class App:
    def __init__(
        self,
        name: str,
        *,
        state: Callable[[], Any] | type | None = None,
        public: str | Path | None = "public",
        origins: list[str] | None = None,
        session_grace: float = 300.0,
        debug: bool = False,
        bundle_dir: Path | None = None,
        secret: str | None = None,
        files: Files | None = None,
        components: str | Path | None = "components",
        auth: Auth | None = None,
        theme: Theme | str | Path | None = None,
        csp: str | None = DEFAULT_CSP,
        threads: int | None = None,
        keep_alive: bool = False,
    ) -> None:
        self.name = name
        # The secret signs file URLs (and cookies, with auth). Without auth, a random
        # per-process secret is used: fine for one replica, logged so it is not a
        # surprise. With auth, a cookie must outlive the process and resist guessing,
        # so the secret is required and must be long enough.
        if auth is not None and (secret is None or len(secret) < 32):
            raise ValueError(
                "auth needs a secret of at least 32 characters; `millwork secret` makes one"
            )
        if secret is None:
            secret = secrets.token_urlsafe(32)
            log.info("no secret configured; using a per-process secret")
        self.secret = secret
        self.csp = csp
        # The thread pool `s.thread`, uploads and file reads run on: the loop's
        # default executor, sized here. None keeps asyncio's default.
        self.threads = threads
        # Ping the health route from every open tab, not only busy ones, for hosts
        # that scale to zero on idle HTTP (the websocket does not count there).
        self.keep_alive = keep_alive
        self.ready = False
        self.files = files or Files()
        self.components_dir = Path(components) if components else None
        self.auth = auth
        if auth is not None:
            auth.bind(secret, debug, origins)
        self._startup: list[Callable[[], Any]] = []
        self._shutdown: list[Callable[[], Any]] = []
        self.default_state = state
        self.public_dir = Path(public) if public else None
        self._theme_path: Path | None = None
        if isinstance(theme, Theme):
            self.theme = theme
        elif theme is not None:
            self._theme_path = Path(theme)
            self.theme = Theme.load(self._theme_path)
        else:
            candidate = self.public_dir / "theme.json" if self.public_dir else None
            self._theme_path = candidate if candidate and candidate.is_file() else None
            self.theme = find_theme(self.public_dir)
        self._theme_mtime = self._theme_path.stat().st_mtime if self._theme_path else 0.0
        self._theme_watch: asyncio.Task[None] | None = None
        self._components_watch: asyncio.Task[None] | None = None
        self._component_mtimes: dict[str, float] = {}
        self.origins = origins or []
        self.session_grace = session_grace
        self.debug = debug
        self.bundle_dir = bundle_dir or BUNDLE_DIR
        self.pages: list[PageDef] = []
        self.sessions: dict[str, Session[Any]] = {}
        self.shell = Shell(self.bundle_dir, prefix=PREFIX)
        self._routes: list[Any] = []
        self._middleware: list[Middleware] = []
        self._asgi: Starlette | None = None

    # ------------------------------------------------------------- pages

    def page(
        self,
        path: str,
        *,
        title: str | None = None,
        public: bool = False,
        state: Callable[[], Any] | type | None = None,
    ) -> Callable[[Callable[[Any], Component]], PageDef]:
        def register(fn: Callable[[Any], Component]) -> PageDef:
            page = PageDef(
                path=path,
                render=fn,
                title=title or self.name,
                public=public,
                state=state or self.default_state,
            )
            self.pages.append(page)
            return page

        return register

    def resolve(self, path: str) -> tuple[PageDef, dict[str, str]] | None:
        for page in self.pages:
            params = page.match(path)
            if params is not None:
                return page, params
        return None

    # ------------------------------------------------------------- extension

    def route(
        self, path: str, endpoint: Callable[..., Any], methods: list[str] | None = None
    ) -> None:
        self._routes.append(Route(path, endpoint, methods=methods or ["GET"]))

    def mount(self, path: str, asgi_app: Any) -> None:
        self._routes.append(Mount(path, app=asgi_app))

    def middleware(self, cls: Any, **options: Any) -> None:
        self._middleware.append(Middleware(cls, **options))

    def on_startup(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self._startup.append(fn)
        return fn

    def on_shutdown(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self._shutdown.append(fn)
        return fn

    @contextlib.asynccontextmanager
    async def _lifespan(self, app: Starlette) -> AsyncIterator[None]:
        if self.threads is not None:
            asyncio.get_running_loop().set_default_executor(
                ThreadPoolExecutor(max_workers=self.threads, thread_name_prefix="millwork")
            )
        removed = self.files.sweep(older_than=max(self.session_grace * 4, 3600))
        if removed:
            log.info("swept %d stale file directories", removed)
        for fn in self._startup:
            await _maybe_await(fn())
        if self.debug and self._theme_path is not None:
            self._theme_watch = asyncio.create_task(self._watch_theme())
        if self.debug and self.components_dir is not None and self.components_dir.is_dir():
            self._components_watch = asyncio.create_task(self._watch_components())
        self.ready = True
        try:
            yield
        finally:
            self.ready = False
            if self._theme_watch is not None:
                self._theme_watch.cancel()
            if self._components_watch is not None:
                self._components_watch.cancel()
            for fn in self._shutdown:
                await _maybe_await(fn())
            for session in list(self.sessions.values()):
                await session.close()

    # ------------------------------------------------------------- asgi

    @property
    def asgi(self) -> Starlette:
        if self._asgi is None:
            self._asgi = self._build_asgi()
        return self._asgi

    def _build_asgi(self) -> Starlette:
        from millwork.ws import websocket_endpoint

        routes: list[Any] = [
            Route(f"{PREFIX}/health", self._health),
            Route(f"{PREFIX}/login", self._login_page),
            Route(f"{PREFIX}/components/{{name}}.jsx", self._component_source),
            WebSocketRoute(f"{PREFIX}/ws", websocket_endpoint),
            Route("/favicon.ico", self._favicon),
            Mount(f"{PREFIX}/assets", app=_Assets(directory=self.bundle_dir, check_dir=False)),
        ]
        if self.auth is not None:
            routes += [
                Route(f"{PREFIX}/auth/login", self.auth.route_login, methods=["POST"]),
                Route(f"{PREFIX}/auth/logout", self.auth.route_logout, methods=["POST"]),
                Route(f"{PREFIX}/auth/oauth/{{provider}}", self.auth.route_oauth_start),
                Route(f"{PREFIX}/auth/oauth/{{provider}}/callback", self.auth.route_oauth_callback),
            ]
        if self.public_dir is not None and self.public_dir.is_dir():
            routes.append(Mount("/public", app=StaticFiles(directory=self.public_dir)))
        routes.extend(self._routes)
        routes.append(Route("/{path:path}", self._serve_page))
        middleware = [Middleware(_SecurityHeaders), *self._middleware]
        app = Starlette(
            routes=routes, middleware=middleware, debug=self.debug, lifespan=self._lifespan
        )
        app.state.millwork = self
        return app

    async def _watch_theme(self) -> None:
        """Debug only: push a changed theme file to every open session."""
        assert self._theme_path is not None
        while True:
            await asyncio.sleep(1.0)
            try:
                mtime = self._theme_path.stat().st_mtime
            except OSError:
                continue
            if mtime == self._theme_mtime:
                continue
            self._theme_mtime = mtime
            await self.reload_theme()

    async def _watch_components(self) -> None:
        """Debug only: a changed custom component is re-fetched by every open tab."""
        self._component_mtimes = self._component_stamps()
        while True:
            await asyncio.sleep(1.0)
            await self.check_components()

    def _component_stamps(self) -> dict[str, float]:
        assert self.components_dir is not None
        try:
            return {p.stem: p.stat().st_mtime for p in self.components_dir.glob("*.jsx")}
        except OSError:
            return {}

    async def check_components(self) -> list[str]:
        """Push a ``reload_component`` for each component file changed since the last
        look; returns their names. The watcher calls this every second."""
        stamps = self._component_stamps()
        changed = [n for n, m in stamps.items() if self._component_mtimes.get(n) != m]
        self._component_mtimes = stamps
        for name in changed:
            log.info("custom component %s changed; reloading it in open tabs", name)
            for session in list(self.sessions.values()):
                if not session.closed:
                    await session._send_now(Command(name="reload_component", args={"name": name}))
        return changed

    async def reload_theme(self) -> bool:
        """Re-read the theme file and push it to open sessions; False when it is invalid."""
        if self._theme_path is None:
            return False
        try:
            self.theme = Theme.load(self._theme_path)
        except ValueError as exc:
            log.error("theme not reloaded: %s", exc)
            return False
        log.info("theme reloaded from %s", self._theme_path)
        args = {"css": self.theme.css(), "boot": self.theme.boot()}
        for session in list(self.sessions.values()):
            if not session.closed:
                await session._send_now(Command(name="theme", args=args))
        return True

    async def _favicon(self, request: Request) -> Any:
        if self.theme.favicon:
            return RedirectResponse(self.theme.favicon, status_code=302)
        icon = self.bundle_dir / "favicon.svg"
        if icon.is_file():
            return FileResponse(icon, media_type="image/svg+xml")
        return PlainTextResponse("", status_code=204)

    async def _component_source(self, request: Request) -> Any:
        """An app's custom component, as text for the tab to compile."""
        if self.components_dir is None:
            return PlainTextResponse("Not found", status_code=404)
        name = request.path_params["name"]
        base = self.components_dir.resolve()
        path = (base / f"{name}.jsx").resolve()
        if not path.is_relative_to(base) or not path.is_file():
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(
            path, media_type="text/javascript", headers={"Cache-Control": "no-cache"}
        )

    async def _health(self, request: Request) -> JSONResponse:
        """200 once the startup hooks are done, 503 before that and during shutdown, so
        an orchestrator does not route to a replica that is still warming up."""
        body = {"ok": self.ready, "version": __version__, "bundle": self.shell.available}
        return JSONResponse(body, status_code=200 if self.ready else 503)

    async def user_for(self, request_or_scope: Any) -> Any:
        """The signed-in user, or None; always None without auth configured."""
        return await self.auth.identify(request_or_scope) if self.auth is not None else None

    def _html(self, page: str, nonce: str) -> HTMLResponse:
        headers = {}
        if self.csp:
            scripts = f"'self' 'nonce-{nonce}'"
            if self.components_dir is not None and self.components_dir.is_dir():
                # Custom components are compiled in the tab (react-runner uses Function).
                scripts += " 'unsafe-eval'"
            headers["Content-Security-Policy"] = self.csp.format(scripts=scripts)
        return HTMLResponse(page, headers=headers)

    async def _login_page(self, request: Request) -> Any:
        if self.auth is None:
            return PlainTextResponse("Not found", status_code=404)
        if not self.shell.available:
            return PlainTextResponse("millwork: the bundle is not built.", status_code=503)
        from millwork.auth import _safe_next

        next_path = _safe_next(request.query_params.get("next"))
        boot = {
            **self.auth.describe(next_path, request.query_params.get("error")),
            "name": self.name,
            "image": self.theme.login_image,
        }
        nonce = secrets.token_urlsafe(16)
        return self._html(
            self.shell.render(
                title=self.name, path=f"{PREFIX}/login", login=boot, theme=self.theme, nonce=nonce
            ),
            nonce,
        )

    async def _serve_page(self, request: Request) -> Any:
        path = "/" + request.path_params.get("path", "")
        resolved = self.resolve(path)
        if resolved is None:
            return PlainTextResponse("Not found", status_code=404)
        page, _ = resolved
        if self.auth is not None and not page.public and await self.user_for(request) is None:
            from urllib.parse import urlencode

            return RedirectResponse(f"{PREFIX}/login?{urlencode({'next': path})}", status_code=302)
        if not self.shell.available:
            return PlainTextResponse(
                "millwork: the bundle is not built. Run `pnpm build` in bundle/.", status_code=503
            )
        user = await self.user_for(request)
        user_boot = (
            {"id": user.id, "name": user.name, "picture_url": user.picture_url} if user else None
        )
        nonce = secrets.token_urlsafe(16)
        return self._html(
            self.shell.render(
                title=page.title or self.name,
                path=path,
                theme=self.theme,
                user=user_boot,
                nonce=nonce,
                keep_alive=self.keep_alive,
            ),
            nonce,
        )

    def file_response(self, path: Path) -> FileResponse:
        return FileResponse(path)


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value
