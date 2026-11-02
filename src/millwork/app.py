"""The application: pages on paths, the Starlette app that serves them.

Everything millwork owns lives under ``/_mw``. An app adds its own routes,
mounts and middleware through the Starlette object in ``app.asgi``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
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
from millwork.proxy import ASGIApp, Proxied
from millwork.shell import Shell, plain, root_of
from millwork.theme import Theme, find_theme, under

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
        max_sessions: int = 1000,
        max_sessions_per_client: int = 20,
        proxied: bool = False,
    ) -> None:
        self.name = name
        # Behind a reverse proxy: its forwarded address and scheme, and the
        # identity headers an auth.Headers provider names, are believed.
        self.proxied = proxied
        # Caps on live sessions, including those waiting out the grace period.
        # A client is a signed-in user, or the connecting address without auth.
        # Over a cap, the client's oldest session without a tab makes room, and
        # only when every one still has a tab is the new one refused.
        self.max_sessions = max_sessions
        self.max_sessions_per_client = max_sessions_per_client
        self._warned_no_address = False
        self._warned_prefix = False
        self._admit_lock = asyncio.Lock()
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
            auth.bind(secret, debug, origins, app=name)
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
        # A content hash per custom component: in the source URL, so a tab caches
        # a version for good and fetches a changed one under a new URL.
        self.component_versions: dict[str, str] = {}
        self.origins = origins or []
        self.session_grace = session_grace
        self.debug = debug
        self.bundle_dir = bundle_dir or BUNDLE_DIR
        self.pages: list[PageDef] = []
        # Where a session lands when no page matches the path, or connect raises
        # NotFound or Forbidden: the framework's own pages until the app sets its
        # own with ``@app.not_found`` and ``@app.forbidden``.
        self.error_pages: dict[str, PageDef] = {
            "not_found": self._error_page_def("not_found", _not_found_view),
            "forbidden": self._error_page_def("forbidden", _forbidden_view),
        }
        self.sessions: dict[str, Session[Any]] = {}
        self.shell = Shell(self.bundle_dir, prefix=PREFIX)
        self._routes: list[Any] = []
        self._middleware: list[Middleware] = []
        self._asgi: ASGIApp | None = None

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

    def fallback(
        self, kind: str, path: str, message: str | None = None
    ) -> tuple[PageDef, dict[str, str]]:
        """The error page for ``kind`` (``not_found`` or ``forbidden``) and its params:
        the path that was asked for and the message connect raised with, if any."""
        return self.error_pages[kind], {"path": path, "message": message or ""}

    def _error_page_def(
        self,
        kind: str,
        fn: Callable[[Any], Component],
        *,
        title: str | None = None,
        public: bool = False,
        state: Callable[[], Any] | type | None = None,
    ) -> PageDef:
        return PageDef(
            path=f"{PREFIX}/{kind.replace('_', '-')}",
            render=fn,
            title=title or self.theme.text(f"{kind}_title"),
            public=public,
            state=state or self.default_state,
        )

    def not_found(
        self,
        fn: Callable[[Any], Component] | None = None,
        *,
        title: str | None = None,
        public: bool = False,
        state: Callable[[], Any] | type | None = None,
    ) -> Any:
        """Decorator: the page shown when no page matches, or connect raises ``NotFound``.

        An ordinary page function; ``s.params["path"]`` is the path asked for and
        ``s.params["message"]`` the text ``NotFound`` was raised with, or empty.
        The HTTP response that serves it is a 404.
        """
        return self._set_error_page("not_found", fn, title=title, public=public, state=state)

    def forbidden(
        self,
        fn: Callable[[Any], Component] | None = None,
        *,
        title: str | None = None,
        public: bool = False,
        state: Callable[[], Any] | type | None = None,
    ) -> Any:
        """Decorator: the page shown when connect raises ``Forbidden``; see ``not_found``."""
        return self._set_error_page("forbidden", fn, title=title, public=public, state=state)

    def _set_error_page(self, kind: str, fn: Any, **options: Any) -> Any:
        def register(fn: Callable[[Any], Component]) -> PageDef:
            page = self._error_page_def(kind, fn, **options)
            self.error_pages[kind] = page
            return page

        return register(fn) if fn is not None else register

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
        # On a thread: a root with many stale directories would otherwise hold
        # the loop before the first request.
        removed = await asyncio.to_thread(self.files.sweep, max(self.session_grace * 4, 3600))
        if removed:
            log.info("swept %d stale file directories", removed)
        for fn in self._startup:
            await _maybe_await(fn())
        self.component_versions = self._component_hashes()
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
    def asgi(self) -> ASGIApp:
        if self._asgi is None:
            self._asgi = Proxied(self._build_asgi(), lambda: self.proxied)
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
            routes=routes,
            middleware=middleware,
            debug=self.debug,
            lifespan=self._lifespan,
            exception_handlers={500: self._server_error},
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

    def _component_hashes(self) -> dict[str, str]:
        if self.components_dir is None or not self.components_dir.is_dir():
            return {}
        versions = {}
        for path in self.components_dir.glob("*.jsx"):
            try:
                versions[path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            except OSError:
                continue
        return versions

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
        gone = set(self._component_mtimes) - set(stamps)
        self._component_mtimes = stamps
        if changed or gone:
            self.component_versions = self._component_hashes()
        for name in changed:
            log.info("custom component %s changed; reloading it in open tabs", name)
            args = {"name": name, "version": self.component_versions.get(name)}
            for session in list(self.sessions.values()):
                if not session.closed:
                    await session._send_now(Command(name="reload_component", args=args))
        return changed

    async def admit(self, session: Session[Any]) -> bool:
        """Take the new session in, making room by ending the session longest without
        a tab when a cap is reached; False, and the session left out, when none can
        be ended. One at a time, so two arriving together cannot both take the last
        place."""
        client = session.client

        async def make_room(client: str | None) -> bool:
            idle = [
                s
                for s in self.sessions.values()
                if not s.closed and not s.has_tab and (client is None or s.client == client)
            ]
            if not idle:
                return False
            oldest = min(idle, key=lambda s: s.detached_at)
            await oldest.end(self.theme.text("made_room"))
            return True

        async with self._admit_lock:
            mine = sum(1 for s in self.sessions.values() if s.client == client and not s.closed)
            if mine >= self.max_sessions_per_client and not await make_room(client):
                return False
            if len(self.sessions) >= self.max_sessions and not await make_room(None):
                return False
            self.sessions[session.id] = session
            return True

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
        for session in list(self.sessions.values()):
            if not session.closed:
                args = {"css": self.theme.css(session.base), "boot": self.theme.boot()}
                await session._send_now(Command(name="theme", args=args))
        return True

    async def _favicon(self, request: Request) -> Any:
        if self.theme.favicon:
            href = under(root_of(request.scope), self.theme.favicon) or ""
            return RedirectResponse(href, status_code=302)
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
        # Asked for by its current version, the source may be kept for good; the
        # URL changes with the content. Any other request is revalidated each time.
        current = self.component_versions.get(name)
        version = request.query_params.get("v")
        cache = "public, max-age=31536000, immutable" if version == current else "no-cache"
        return FileResponse(path, media_type="text/javascript", headers={"Cache-Control": cache})

    async def _health(self, request: Request) -> JSONResponse:
        """200 once the startup hooks are done, 503 before that and during shutdown, so
        an orchestrator does not route to a replica that is still warming up."""
        body = {"ok": self.ready, "version": __version__, "bundle": self.shell.available}
        return JSONResponse(body, status_code=200 if self.ready else 503)

    async def user_for(self, request_or_scope: Any) -> Any:
        """The signed-in user, or None; always None without auth configured."""
        return await self.auth.identify(request_or_scope) if self.auth is not None else None

    def _html(self, page: str, nonce: str, status: int = 200) -> HTMLResponse:
        headers = {}
        if self.csp:
            scripts = f"'self' 'nonce-{nonce}'"
            if self.components_dir is not None and self.components_dir.is_dir():
                # Custom components are compiled in the tab (react-runner uses Function).
                scripts += " 'unsafe-eval'"
            headers["Content-Security-Policy"] = self.csp.format(scripts=scripts)
        return HTMLResponse(page, status_code=status, headers=headers)

    def _check_stripped(self, scope: Any, path: str) -> None:
        """A path that still starts with the prefix means the proxy passed it
        through whole: every route then misses, and only the log can say why."""
        base = root_of(scope)
        if base and (path == base or path.startswith(base + "/")) and not self._warned_prefix:
            self._warned_prefix = True
            log.warning(
                "the request path %s still carries the prefix %s: the proxy must strip it",
                path,
                base,
            )

    def _plain(self, request: Request, status: int, title: str, text: str) -> HTMLResponse:
        """A themed page for a failure before the bundle can run."""
        nonce = secrets.token_urlsafe(16)
        try:
            base = root_of(request.scope)
        except ValueError:
            base = ""
        page = plain(title=title, text=text, theme=self.theme, nonce=nonce, base=base)
        return self._html(page, nonce, status)

    async def _server_error(self, request: Request, exc: Exception) -> Any:
        """An unhandled exception in a route: a page in the app's colours, never the
        exception; the traceback is in the log. Debug mode shows Starlette's own page."""
        text = self.theme.text
        return self._plain(request, 500, text("something_went_wrong"), text("try_again"))

    async def _login_page(self, request: Request) -> Any:
        if self.auth is None:
            return PlainTextResponse("Not found", status_code=404)
        if not self.shell.available:
            return PlainTextResponse("millwork: the bundle is not built.", status_code=503)
        from millwork.auth import _safe_next

        next_path = _safe_next(request.query_params.get("next"))
        base = root_of(request.scope)
        if await self.user_for(request) is not None:
            # Already signed in, by a cookie or by the proxy: nothing to show.
            return RedirectResponse(f"{base}{next_path}", status_code=302)
        error = request.query_params.get("error")
        if error is None and self.auth.proxy_identity(request):
            error = self.theme.text("proxy_denied")
        boot = {
            **self.auth.describe(next_path, error),
            "name": self.name,
            "image": self.theme.login_image,
        }
        nonce = secrets.token_urlsafe(16)
        return self._html(
            self.shell.render(
                title=self.name,
                path=f"{PREFIX}/login",
                login=boot,
                theme=self.theme,
                nonce=nonce,
                base=base,
            ),
            nonce,
        )

    async def _serve_page(self, request: Request) -> Any:
        path = "/" + request.path_params.get("path", "")
        self._check_stripped(request.scope, path)
        resolved = self.resolve(path)
        status = 200
        if resolved is None:
            # The not-found page, served as a 404 so monitors and crawlers see one.
            resolved = self.fallback("not_found", path)
            status = 404
        page, _ = resolved
        base = root_of(request.scope)
        user = await self.user_for(request)
        if self.auth is not None and not page.public and user is None:
            from urllib.parse import urlencode

            login = f"{base}{PREFIX}/login?{urlencode({'next': path})}"
            return RedirectResponse(login, status_code=302)
        if not self.shell.available:
            if status == 404:
                text = self.theme.text
                title, body = text("not_found_title"), text("not_found_text", path=path)
                return self._plain(request, 404, title, body)
            hint = "The bundle is not built. Run `pnpm build` in bundle/."
            return self._plain(request, 503, "millwork", hint)
        user_boot = (
            {"id": user.id, "name": user.name, "picture_url": user.picture_url} if user else None
        )
        if user_boot is not None and request.scope.get("millwork.identified_by") == "header":
            # The proxy signed this person in, so sign-out is its URL, or nothing to offer.
            user_boot["sign_out"] = (self.auth.sign_out if self.auth else None) or None
        nonce = secrets.token_urlsafe(16)
        return self._html(
            self.shell.render(
                title=page.title or self.name,
                path=path,
                theme=self.theme,
                user=user_boot,
                nonce=nonce,
                keep_alive=self.keep_alive,
                components=self.component_versions,
                base=base,
            ),
            nonce,
            status,
        )

    def file_response(self, path: Path) -> FileResponse:
        return FileResponse(path)


def _error_view(s: Any, kind: str) -> Component:
    """The framework's own error page: the logo, a title, the reason, a way home.
    The same frame as the login page, in the theme's tokens, with no app chrome."""
    from millwork import ui

    message = s.params.get("message") or s.text(f"{kind}_text", path=s.params.get("path", ""))
    home = ui.Button(
        label=s.text("home"),
        variant="outline",
        icon="home",
        on_click=lambda s, _: s.navigate("/"),
    )
    card = ui.Stack(
        children=[
            ui.Logo(cls="h-9 self-start"),
            ui.Text(s.text(f"{kind}_title"), variant="title"),
            ui.Text(message, variant="muted"),
            ui.Row(children=[home]),
        ],
        gap=3,
        cls="w-full max-w-sm",
    )
    return ui.Stack(children=[card], align="center", justify="center", cls="min-h-dvh p-6")


def _not_found_view(s: Any) -> Component:
    return _error_view(s, "not_found")


def _forbidden_view(s: Any) -> Component:
    return _error_view(s, "forbidden")


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value
