"""The application: pages on paths, the Starlette app that serves them.

Everything millwork owns lives under ``/_mw``. An app adds its own routes,
mounts and middleware through the Starlette object in ``app.asgi``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import logging
import re
import secrets
import time
from collections.abc import AsyncIterator, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urlencode

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import HTTPConnection, Request
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
from millwork.access import ALLOWED, REFUSED, Rule, Verdict, ask, rule_for
from millwork.auth import Auth, _same_origin
from millwork.files import Files
from millwork.nodes import Component
from millwork.protocol import Command
from millwork.proxy import ASGIApp, Proxied
from millwork.scope import Scope
from millwork.shell import Shell, plain, root_of
from millwork.theme import Theme, find_theme, under
from millwork.visitors import Visitor, Visitors
from millwork.work import live

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
# How long the app waits, when it stops, for its sessions to close their
# pages: longer than a close hook is given, so that one is cut by its own
# limit and not by this.
STOP_PATIENCE_SECONDS = 40.0
# How much of an exception's text the failure page shows in debug mode.
FAILURE_DETAIL_CHARS = 2000
BUNDLE_DIR = Path(__file__).parent / "_bundle" / "dist"


@dataclass
class PageDef:
    path: str
    render: Callable[[Any], Component]
    title: str | None = None
    public: bool = False
    # Who may open it, among the signed in: a function of the user. None lets
    # every signed-in user in.
    allow: Rule | None = None
    on_connect: Callable[..., Any] | None = None
    on_close: Callable[..., Any] | None = None
    _regex: Any = field(init=False, repr=False)
    _param_convertors: Any = field(init=False, repr=False)
    _rank: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._regex, _, self._param_convertors = compile_path(self.path)
        # How exact each segment is, from a literal down to a parameter that
        # takes the rest of the path. Of the pages a path matches, the one
        # that is exact soonest is the page meant. The end counts as the
        # least exact of all, so a page that goes on after ``{rest:path}``
        # comes before the one that stops there.
        self._rank = (*(_exactness(seg) for seg in self.path.split("/")), 4)

    @property
    def params(self) -> tuple[str, ...]:
        """The names of the parameters in the page's path."""
        return tuple(self._param_convertors)

    def match(self, path: str) -> dict[str, str] | None:
        m = self._regex.match(path)
        if m is None:
            return None
        return {k: self._param_convertors[k].convert(v) for k, v in m.groupdict().items()}

    def connect(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator: the page's connect hook, ``(session, **params)``."""
        self.on_connect = fn
        return fn

    def close(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator: runs with the session when it leaves the page, or ends on it."""
        self.on_close = fn
        return fn


def _address(scope: Any, decoded: str) -> str:
    """The app's path of a request as the client spelled it, percent signs
    and all, which is also what the tab reads from its address bar. A server
    hands the spelling over next to what it decoded it to. One that does not
    gets the decoded path encoded again."""
    raw = scope.get("raw_path")
    if isinstance(raw, bytes | bytearray):
        text = bytes(raw).decode("latin-1").split("?", 1)[0]
        root = str(scope.get("root_path") or "")
        if root and (text == root or text.startswith(root + "/")):
            text = text[len(root) :] or "/"
        if text.startswith("/"):
            return text
    return quote(decoded)


def _exactness(segment: str) -> int:
    """How much one segment of a page's path pins down: 0 for a literal, 1 for
    a parameter held in by a converter or by text around it (``{id:int}``,
    ``v{n}``), 2 for a bare ``{name}``, 3 for ``{rest:path}``."""
    if "{" not in segment:
        return 0
    if ":path}" in segment:
        return 3
    bare = segment.startswith("{") and segment.endswith("}") and segment.count("{") == 1
    return 2 if bare and ":" not in segment else 1


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
        identify_visitors: bool = False,
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
        # The secret signs file URLs (and cookies, with auth). Without auth, a random
        # per-process secret is used: fine for one replica, logged so it is not a
        # surprise. With auth, a cookie must outlive the process and resist guessing,
        # so the secret is required and must be long enough.
        if auth is not None and (secret is None or len(secret) < 32):
            raise ValueError(
                "auth needs a secret of at least 32 characters; `millwork secret` makes one"
            )
        if identify_visitors and secret is not None and len(secret) < 32:
            # It signs the cookie that names a visitor, and a short one can
            # be found from a single cookie.
            raise ValueError(
                "identify_visitors needs a secret of at least 32 characters, or none "
                "for one made at every start; `millwork secret` makes one"
            )
        if secret is None:
            secret = secrets.token_urlsafe(32)
            log.info("no secret configured; using a per-process secret")
            if identify_visitors:
                log.info(
                    "visitors get a new id every time the app starts; "
                    "App(secret=...) lets them keep it"
                )
        self.secret = secret
        # A name for each browser, in a cookie of its own. Off unless the app
        # asks, so no app sets a cookie it has no use for.
        self.visitors = Visitors(secret, name) if identify_visitors else None
        self.csp = csp
        # The thread pool `s.thread`, uploads and file reads run on: the loop's
        # default executor, sized here. None keeps asyncio's default.
        self.threads = threads
        # Ping the health route from every open tab, not only busy ones, for hosts
        # that scale to zero on idle HTTP (the websocket does not count there).
        self.keep_alive = keep_alive
        self.ready = False
        self.files = files or Files()
        # Folders are found next to the file that makes the App, wherever the
        # server is started from. A folder the app names that is not there is
        # said so at once, where the page it affects would only look bare.
        home = _home_of_caller()
        self.components_dir = _folder(
            home, components, "components", explicit=components != "components"
        )
        self.auth = auth
        if auth is not None:
            auth.bind(secret, debug, origins, app=name)
        self._startup: list[Callable[[], Any]] = []
        self._shutdown: list[Callable[[], Any]] = []
        self.state_model = state
        self.public_dir = _folder(home, public, "public", explicit=public != "public")
        self._theme_path: Path | None = None
        if isinstance(theme, Theme):
            self.theme = theme
        elif theme is not None:
            self._theme_path = _under_home(home, theme)
            self.theme = Theme.load(self._theme_path)
        else:
            candidate = self.public_dir / "theme.json" if self.public_dir else None
            self._theme_path = candidate if candidate and candidate.is_file() else None
            self.theme = find_theme(self.public_dir)
        self._theme_mtime = self._theme_path.stat().st_mtime if self._theme_path else 0.0
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
        # What the app waits for when it stops: the life of every session,
        # to the end of its page's close hook.
        self.lives = Scope("lives")
        # What runs for as long as the app does and is simply stopped with it.
        self.background = Scope("background")
        self.stopping = False
        # Where the tabs of a sign-in that is ending are to go, as ``on_logout``
        # says or is still being asked, and when it was asked: one answer for
        # all of a sign-in's tabs, and for a straggler a moment later.
        self._destinations: dict[str, tuple[asyncio.Future[str | None], float]] = {}
        self.shell = Shell(self.bundle_dir, prefix=PREFIX)
        self._routes: list[Any] = []
        self._extra: list[_Extra] = []
        self._middleware: list[Middleware] = []
        self._asgi: ASGIApp | None = None

    # ------------------------------------------------------------- pages

    def page(
        self,
        path: str,
        *,
        title: str | None = None,
        public: bool = False,
        allow: Callable[..., bool] | None = None,
    ) -> Callable[[Callable[[Any], Component]], PageDef]:
        """Decorator: a page at ``path``. With auth it asks for a sign-in unless
        ``public=True``. ``allow`` narrows it further: a function of the user,
        and of the path's parameters it names, that returns True for who may
        open the page."""
        self._check_access(f"the page {path}", public, allow)

        def register(fn: Callable[[Any], Component]) -> PageDef:
            page = PageDef(path=path, render=fn, title=title or self.name, public=public)
            if allow is not None:
                page.allow = rule_for(allow, page.params, f"the page {path}")
            self.pages.append(page)
            return page

        return register

    def _check_access(self, what: str, public: bool, allow: Any) -> None:
        if allow is None:
            return
        if public:
            raise ValueError(
                f"{what} is public and has a rule. A rule is about the signed-in user, "
                "and a public page has none to ask about"
            )
        if self.auth is None:
            raise ValueError(f"{what} has a rule, and the app has no auth to tell who is asking")

    def may(self, user: Any, page: PageDef, params: Mapping[str, Any]) -> Verdict:
        """Whether this user may open this page: the one place that question
        is answered, for a page load, a socket, a navigation and a link. It
        only answers. Acting on a refusal is the caller's."""
        if self.auth is None or page.public:
            return ALLOWED
        if user is None:
            return REFUSED
        return ask(page.allow, user, params, f"the page {page.path}")

    def make_state(self) -> Any:
        """A session's state: one instance of the app's model, kept for the session."""
        return None if self.state_model is None else self.state_model()

    def resolve(self, path: str) -> tuple[PageDef, dict[str, str]] | None:
        """The page at a path and its parameters. Where several pages match,
        the one whose path is exact soonest wins, read from the left: a
        literal segment over a parameter, so ``/orders/new`` is its own page
        next to ``/orders/{id}`` in whichever order they were added. Two
        pages equally exact go by that order."""
        best: tuple[PageDef, dict[str, str]] | None = None
        for page in self.pages:
            try:
                params = page.match(path)
            except ValueError:
                # A parameter the path's convertor cannot read: not this page.
                continue
            if params is not None and (best is None or page._rank < best[0]._rank):
                best = page, params
        return best

    def locate(self, url: str) -> tuple[PageDef, dict[str, str]] | None:
        """The page a path names when it is spelled as an address: what a tab
        sends, a link's ``href``, what a handler navigates to. What follows a
        ``?`` or a ``#`` is not part of the path, and the rest is decoded
        once, which is what the server has already done to the path of a page
        load. A page and its rule then see the same parameters whichever way
        the path came."""
        return self.resolve(unquote(url.split("?", 1)[0].split("#", 1)[0]))

    def fallback(
        self, kind: str, path: str, message: str | None = None
    ) -> tuple[PageDef, dict[str, str]]:
        """The error page for ``kind`` (``not_found`` or ``forbidden``) and its params:
        the path that was asked for and the message connect raised with, if any."""
        # Shown to a person, so as they would read it and not as an address
        # spells it.
        return self.error_pages[kind], {"path": unquote(path), "message": message or ""}

    def _error_page_def(
        self,
        kind: str,
        fn: Callable[[Any], Component],
        *,
        title: str | None = None,
        public: bool = False,
    ) -> PageDef:
        return PageDef(
            path=f"{PREFIX}/{kind.replace('_', '-')}",
            render=fn,
            title=title or self.theme.text(f"{kind}_title"),
            public=public,
        )

    def not_found(
        self,
        fn: Callable[[Any], Component] | None = None,
        *,
        title: str | None = None,
        public: bool = False,
    ) -> Any:
        """Decorator: the page shown when no page matches, or connect raises ``NotFound``.

        An ordinary page function; ``s.params["path"]`` is the path asked for and
        ``s.params["message"]`` the text ``NotFound`` was raised with, or empty.
        The HTTP response that serves it is a 404.
        """
        return self._set_error_page("not_found", fn, title=title, public=public)

    def forbidden(
        self,
        fn: Callable[[Any], Component] | None = None,
        *,
        title: str | None = None,
        public: bool = False,
    ) -> Any:
        """Decorator: the page shown when connect raises ``Forbidden``; see ``not_found``."""
        return self._set_error_page("forbidden", fn, title=title, public=public)

    def _set_error_page(self, kind: str, fn: Any, **options: Any) -> Any:
        def register(fn: Callable[[Any], Component]) -> PageDef:
            page = self._error_page_def(kind, fn, **options)
            self.error_pages[kind] = page
            return page

        return register(fn) if fn is not None else register

    # ------------------------------------------------------------- extension

    def route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        methods: list[str] | None = None,
        *,
        public: bool = False,
        allow: Callable[..., bool] | None = None,
    ) -> None:
        """A plain Starlette route next to the pages, for an API or a download.

        With auth it needs a sign-in like a page does, and ``allow`` narrows it
        like a page's. The endpoint finds the user in ``request.state.user``.
        ``public=True`` opens it to anyone, which is what a webhook or a
        health check needs. In an app that identifies visitors the endpoint
        finds the browser that asks in ``request.state.visitor``, or None
        there when the browser brought no id."""
        self._check_access(f"the route {path}", public, allow)
        route = Route(path, endpoint, methods=methods or ["GET"])
        rule = rule_for(allow, route.param_convertors, f"the route {path}") if allow else None
        self._extra.append(_Extra("route", path, public, rule))
        guarded = self.auth is not None and not public
        if self.visitors is not None:
            route.app = _Visited(self, route.app, guarded)
        if guarded:
            route.app = _Guarded(self, route.app, rule, f"the route {path}")
        self._routes.append(route)

    def mount(
        self,
        path: str,
        asgi_app: Any,
        *,
        public: bool = False,
        allow: Callable[..., bool] | None = None,
    ) -> None:
        """Serve another ASGI app under a path. With auth, everything under it
        needs a sign-in unless ``public=True``, and ``allow`` narrows it by the
        user alone. What is mounted finds the user and the visitor where a
        route does."""
        self._check_access(f"the mount {path}", public, allow)
        rule = rule_for(allow, (), f"the mount {path}") if allow else None
        self._extra.append(_Extra("mount", path, public, rule))
        guarded = self.auth is not None and not public
        if self.visitors is not None:
            asgi_app = _Visited(self, asgi_app, guarded)
        if guarded:
            asgi_app = _Guarded(self, asgi_app, rule, f"the mount {path}")
        self._routes.append(Mount(path, app=asgi_app))

    def access(self) -> list[tuple[str, str, str]]:
        """Every page, route and mount with who may reach it, for reading the
        app's access in one place: ``(kind, path, access)``."""

        def said(public: bool, rule: Rule | None) -> str:
            if self.auth is None:
                return "anyone (the app has no auth)"
            if public:
                return "anyone"
            return f"signed in and {rule.name}" if rule is not None else "signed in"

        rows = [("page", p.path, said(p.public, p.allow)) for p in self.pages]
        rows += [(e.kind, e.path, said(e.public, e.rule)) for e in self._extra]
        # What the app serves without asking anyone, so the list is whole.
        if self.public_dir is not None and self.public_dir.is_dir():
            rows.append(("files", "/public", said(True, None)))
        if self.components_dir is not None and self.components_dir.is_dir():
            rows.append(("files", f"{PREFIX}/components", said(True, None)))
        return rows

    def middleware(self, cls: Any, **options: Any) -> None:
        """Add a Starlette middleware class around the whole app."""
        self._middleware.append(Middleware(cls, **options))

    def on_startup(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        """Decorator: runs once when the server starts, before the first session."""
        self._startup.append(fn)
        return fn

    def on_shutdown(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        """Decorator: runs once when the server stops."""
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
        self._begin()
        removed = await asyncio.to_thread(self.files.sweep, max(self.session_grace * 4, 3600))
        if removed:
            log.info("swept %d stale file directories", removed)
        for fn in self._startup:
            await _maybe_await(fn())
        self.component_versions = self._component_hashes()
        if self.debug and (self._theme_path is not None or self._stylesheet_file()):
            self.background.start(self._watch_theme(), "theme watch")
        if self.debug and self.components_dir is not None and self.components_dir.is_dir():
            self.background.start(self._watch_components(), "components watch")
        self.ready = True
        try:
            yield
        finally:
            self.ready = False
            await self._stop()
            for fn in self._shutdown:
                await _maybe_await(fn())

    def _begin(self) -> None:
        """A fresh start: an app may be started again after it was stopped."""
        self.stopping = False
        if self.lives.cancelled:
            self.lives = Scope("lives")
        if self.background.cancelled:
            self.background = Scope("background")
        if self.auth is not None and self.auth.scope.cancelled:
            self.auth.scope = Scope("auth")

    async def _stop(self) -> None:
        """End every session and see each one out, before the shutdown hooks
        run: a page's close hook still has what those take away, a database
        pool or a client. Nothing of a session is running when this returns."""
        self.stopping = True
        self.background.cancel()
        for session in list(self.sessions.values()):
            session.dismiss()
        if self.auth is not None:
            # What is still being asked of the app's hooks is for sessions
            # that are over now. Nobody needs the answers.
            self.auth.scope.cancel()
        await self.lives.wait(STOP_PATIENCE_SECONDS)
        self.lives.cancel()
        await self.lives.wait(1.0)
        if self.auth is not None:
            await self.auth.scope.wait(1.0)
        await self.background.wait(1.0)

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
                Route(f"{PREFIX}/auth/logout", self._logout, methods=["POST"]),
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

    def _stylesheet_file(self) -> Path | None:
        """The theme's stylesheet as a file, when it is one under ``public/``."""
        sheet = self.theme.stylesheet
        if sheet and sheet.startswith("/public/") and self.public_dir is not None:
            return self.public_dir / sheet.removeprefix("/public/")
        return None

    def _stylesheet_mtime(self) -> float:
        sheet = self._stylesheet_file()
        try:
            return sheet.stat().st_mtime if sheet is not None else 0.0
        except OSError:
            return 0.0

    async def _watch_theme(self) -> None:
        """Debug only: push a changed theme file, or a changed stylesheet of
        the theme's, to every open session."""
        styled = self._stylesheet_mtime()
        while True:
            await asyncio.sleep(1.0)
            if self._theme_path is not None:
                try:
                    mtime = self._theme_path.stat().st_mtime
                except OSError:
                    continue
                if mtime != self._theme_mtime:
                    self._theme_mtime = mtime
                    await self.reload_theme()
                    styled = self._stylesheet_mtime()
                    continue
            now = self._stylesheet_mtime()
            if now != styled:
                styled = now
                self._push_theme()

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
                session.post(Command(name="reload_component", args=args))
        return changed

    def admit(self, session: Session[Any]) -> bool:
        """Take the new session in and start its life, making room by ending
        the session longest without a tab when a cap is reached. False, and
        the session left out, when none can be ended, or when the app is
        stopping. All of it is one step, so two arriving together cannot both
        take the last place, and a session is among the app's sessions if and
        only if its life has been started."""
        if self.stopping:
            return False
        client = session.client

        def make_room(client: str | None) -> bool:
            idle = [
                s
                for s in self.sessions.values()
                if not s.has_tab and (client is None or s.client == client)
            ]
            if not idle:
                return False
            # Over as this returns, which is what makes the room. Its close
            # hook runs on without holding up whoever is waiting to get in.
            min(idle, key=lambda s: s.detached_at).dismiss(self.theme.text("made_room"))
            return True

        mine = sum(1 for s in self.sessions.values() if s.client == client)
        if mine >= self.max_sessions_per_client and not make_room(client):
            return False
        if len(self.sessions) >= self.max_sessions and not make_room(None):
            return False
        self.sessions[session.id] = session
        self.lives.start(
            live(session), f"life of {session.id[:6]}", done=lambda _: self._gone(session)
        )
        return session.id in self.sessions

    def _gone(self, session: Session[Any]) -> None:
        """A session's life is done, or never began: nothing of it is left."""
        session.dismiss()
        self.sessions.pop(session.id, None)
        self.files.discard(session.id)
        if not session.gone.done():
            session.gone.set_result(None)

    def end_sign_in(self, sign_in: str, user: Any) -> None:
        """A sign-in ran out: its sessions leave together. Each of them is
        over as this returns, before anything is asked, so nothing more runs
        on a sign-in that has ended while ``on_logout`` is being asked where
        its tabs should go. The hook is asked once for all of them, and a
        straggler of the same sign-in a moment later goes where they went."""
        theirs = [s for s in self.sessions.values() if s.sign_in == sign_in]
        if not theirs:
            return
        now = time.monotonic()
        self._destinations = {k: v for k, v in self._destinations.items() if now - v[1] < 60.0}
        kept = self._destinations.get(sign_in)
        if kept is None:
            asking: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()

            def answered(child: asyncio.Task[Any] | None) -> None:
                # Always an answer, never an exception: a hook that failed,
                # or was never asked, sends its tabs to the login page.
                found = child is not None and not child.cancelled() and child.exception() is None
                if not asking.done():
                    asking.set_result(child.result() if found and child is not None else None)

            if self.auth is None:
                asking.set_result(None)
            else:
                self.auth.scope.start(self.auth.leave(user), "on_logout", done=answered)
            self._destinations[sign_in] = (asking, now)
        else:
            asking = kept[0]
        said = self.theme.text("sign_in_hint")
        for session in theirs:
            session.dismiss(said, to=session.leaving_for(None), asking=asking)

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
        self._push_theme()
        return True

    def _push_theme(self) -> None:
        """Send the theme to every open tab, which also fetches its stylesheet anew."""
        for session in list(self.sessions.values()):
            session.command("theme", css=self.theme.css(session.base), boot=self.theme.boot())

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
        user = await self.user_for(request)
        if user is not None:
            # Already signed in, by a cookie or by the proxy: nothing to show.
            return self._greeted(request, RedirectResponse(f"{base}{next_path}", 302), user)
        error = request.query_params.get("error")
        revoked = bool(request.scope.get("millwork.revoked"))
        if error is None and revoked:
            # Signed in until the app's recheck said otherwise: the page says
            # so, where a first visit gets no reason at all.
            error = "Access denied."
        if error is None and self.auth.proxy_identity(request):
            error = self.theme.text("proxy_denied")
        boot = {
            **self.auth.describe(next_path, error, self.theme.text("or")),
            "name": self.name,
            "image": self.theme.login_image,
        }
        nonce = secrets.token_urlsafe(16)
        response = self._html(
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
        if revoked:
            self.auth.clear_cookie(request, response)
        return self._greeted(request, response, None)

    def _greeted(self, request: Request, response: Any, user: Any) -> Any:
        """A page's answer, naming the browser when the app identifies visitors."""
        return response if self.visitors is None else self.visitors.greet(request, response, user)

    async def _logout(self, request: Request) -> Any:
        assert self.auth is not None
        response = await self.auth.route_logout(request)
        if self.visitors is not None and response.status_code == 200:
            # Whoever uses the browser next is not the visitor who just left.
            self.visitors.renew(request, response)
        return response

    async def _serve_page(self, request: Request) -> Any:
        user = await self.user_for(request)
        return self._greeted(request, self._page_response(request, user), user)

    def _page_response(self, request: Request, user: Any) -> Any:
        path = "/" + request.path_params.get("path", "")
        self._check_stripped(request.scope, path)
        # The path as the browser spelled it. The tab says hello with it, and
        # the page is found by it here, so the load and the session that
        # follows read one spelling the same way.
        address = _address(request.scope, path)
        resolved = self.locate(address)
        status = 200
        if resolved is None:
            # The not-found page, served as a 404 so monitors and crawlers see one.
            resolved = self.fallback("not_found", path)
            status = 404
        page, params = resolved
        base = root_of(request.scope)
        if self.auth is not None and not page.public and user is None:
            if request.scope.get("millwork.revoked"):
                # Signed in, and no longer welcome: the cookie goes, and the
                # login page says why instead of looking like a first visit.
                response = self.auth._login_redirect(request, address, "Access denied.")
                self.auth.clear_cookie(request, response)
                return response
            login = f"{base}{PREFIX}/login?{urlencode({'next': address})}"
            return RedirectResponse(login, status_code=302)
        if status == 200 and not self.may(user, page, params).ok:
            # The page the session lands on says so. The status is for whatever
            # reads statuses, and the shell is the forbidden page's, so not
            # even the title of the page that refused is in it.
            status = 403
            page = self.error_pages["forbidden"]
        if not self.shell.available:
            if status == 404:
                text = self.theme.text
                title, body = text("not_found_title"), text("not_found_text", path=path)
                return self._plain(request, 404, title, body)
            if status == 403:
                text = self.theme.text
                return self._plain(request, 403, text("forbidden_title"), text("forbidden_text"))
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
                path=address,
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


@dataclass
class _Extra:
    """A route or a mount of the app's own, as the access listing shows it."""

    kind: str
    path: str
    public: bool
    rule: Rule | None


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class _Guarded:
    """An app's own route or mount behind the sign-in, like a page.

    The visitor is identified the way a page load identifies them, a request
    that changes something has to come from the app's own origin since the
    cookie alone would also ride along on another site's form, and the rule
    is asked. What passes finds the user in ``request.state.user``."""

    def __init__(self, app: App, inner: Any, rule: Rule | None, where: str) -> None:
        self.app, self.inner, self.rule, self.where = app, inner, rule, where

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.inner(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        user = await self.app.user_for(conn)
        text = self.app.theme.text
        refused: tuple[int, str] | None = None
        if user is None:
            refused = (401, text("sign_in_hint"))
        elif (
            scope["type"] == "websocket" or scope["method"] not in _SAFE_METHODS
        ) and not _same_origin(conn, self.app.origins):  # type: ignore[arg-type]
            # A socket, or a request that changes something, from another
            # site's page: the cookie would ride along, so the origin decides.
            refused = (403, text("forbidden_text"))
        else:
            verdict = ask(self.rule, user, scope.get("path_params") or {}, self.where)
            if not verdict.ok:
                refused = (403, verdict.message or text("forbidden_text"))
        if refused is None:
            scope.setdefault("state", {})["user"] = user
            await self.inner(scope, receive, send)
            return
        status, reason = refused
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
            return
        response: Any = JSONResponse({"reason": reason}, status_code=status)
        wants_page = scope["method"] == "GET" and "text/html" in conn.headers.get("accept", "")
        if status == 401 and wants_page:
            # A link someone followed in a browser: sign in, then come back.
            base = root_of(scope)
            path = scope["path"]
            if base and (path == base or path.startswith(base + "/")):
                path = path[len(base) :] or "/"
            login = f"{base}{PREFIX}/login?{urlencode({'next': path})}"
            response = RedirectResponse(login, status_code=302)
        await response(scope, receive, send)


class _Visited:
    """An app's own route or mount, told which browser is asking.

    ``request.state.visitor`` is the visitor a session opened from that
    browser would have, or None when the browser brought no id that is this
    person's to use. Nothing is issued here: a browser gets its id from a
    page. A socket, or a request that changes something, from another
    site's page has no visitor either, since the cookie rides along on it.
    ``guarded`` says the sign-in was asked for on the way in, and the user
    it found is the one the id is checked against."""

    def __init__(self, app: App, inner: Any, guarded: bool) -> None:
        self.app, self.inner, self.guarded = app, inner, guarded

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            state = scope.setdefault("state", {})
            state["visitor"] = await self._asking(scope, state)
        await self.inner(scope, receive, send)

    async def _asking(self, scope: Any, state: dict[str, Any]) -> Visitor | None:
        visitors = self.app.visitors
        conn = HTTPConnection(scope)
        if visitors is None or not visitors.named(conn):
            # Most of what calls a public route, a webhook say, brings no
            # cookie, and nobody needs identifying to say so.
            return None
        changes = scope["type"] == "websocket" or scope["method"] not in _SAFE_METHODS
        if changes and not _same_origin(conn, self.app.origins):  # type: ignore[arg-type]
            return None
        user: Any = None
        if self.guarded:
            user = state.get("user")
        elif self.app.auth is not None:
            try:
                user = await self.app.user_for(conn)
            except Exception:
                # A route open to anyone answers whether or not the app can
                # say who is signed in. Without that the id is nobody's.
                log.exception("identity lookup failed; the request has no visitor")
                return None
        known = visitors.of(conn, user)
        return Visitor(known) if known is not None else None


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
        ui.Logo(cls="h-9 self-start"),
        ui.Text(s.text(f"{kind}_title"), variant="title"),
        ui.Text(message, variant="muted"),
        ui.Row(home),
        gap=3,
        cls="w-full max-w-sm",
    )
    return ui.Stack(card, align="center", justify="center", cls="min-h-dvh p-6")


def _not_found_view(s: Any) -> Component:
    return _error_view(s, "not_found")


def _said(error: BaseException) -> str:
    """An exception as text for a page: its type and what it says, cut to a
    length and made of characters that can go over the wire, whatever the
    exception holds and even when it cannot say anything."""
    try:
        text = f"{type(error).__name__}: {error}"
    except Exception:
        text = type(error).__name__
    return text.encode("utf-8", "backslashreplace").decode("utf-8")[:FAILURE_DETAIL_CHARS]


def _failed_view(s: Any, error: BaseException) -> Component:
    """What a session sees where a page would be, when its page function raised
    before there was anything to show: the frame of the error pages, a button
    that draws the page again, and a way home from anywhere else. In debug
    mode the exception is on the page as well, for whoever is writing it."""
    from millwork import ui

    again = ui.Button(
        label=s.text("retry"),
        variant="outline",
        icon="refresh-cw",
        key="retry",
        on_click=lambda s, _: s.refresh(),
    )
    home = ui.Button(
        label=s.text("home"),
        variant="ghost",
        icon="home",
        key="home",
        on_click=lambda s, _: s.navigate("/"),
    )
    detail = ui.Code(_said(error), language="text", wrap=True) if s.app.debug else None
    card = ui.Stack(
        ui.Logo(cls="h-9 self-start"),
        ui.Text(s.text("failed_title"), variant="title"),
        ui.Text(s.text("failed_text"), variant="muted"),
        detail,
        ui.Row(again, home if s.path != "/" else None, gap=2),
        gap=3,
        cls="w-full max-w-xl" if detail else "w-full max-w-sm",
    )
    return ui.Stack(card, align="center", justify="center", cls="min-h-dvh p-6")


def _forbidden_view(s: Any) -> Component:
    return _error_view(s, "forbidden")


def _home_of_caller() -> Path:
    """The folder of the file that is making the App: the first frame outside
    this package. Code with no file, a notebook cell or the REPL, works from
    the working directory."""
    here = Path(__file__).resolve().parent
    frame = inspect.currentframe()
    while frame is not None:
        file = frame.f_globals.get("__file__")
        if not isinstance(file, str):
            return Path.cwd()
        where = Path(file).resolve()
        if not where.is_relative_to(here):
            return where.parent
        frame = frame.f_back
    return Path.cwd()


def _under_home(home: Path, path: str | Path) -> Path:
    given = Path(path)
    return given if given.is_absolute() else home / given


def _folder(home: Path, path: str | Path | None, what: str, *, explicit: bool) -> Path | None:
    """A folder the app names, next to its own file. One named by the app
    that does not exist is logged; the default being absent is nothing."""
    if not path:
        return None
    folder = _under_home(home, path)
    if explicit and not folder.is_dir():
        log.warning("the %s folder %s does not exist", what, folder)
    return folder


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value
