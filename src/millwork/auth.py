"""Auth: who may open an app, and what a page may ask about them.

Providers are configured in Python on the ``App``; one
``on_login`` hook decides access and shapes the ``User``; the cookie is a
compact signed token; the websocket binds to it. The cookie and OAuth
mechanics are lifted from Chainlit's ``auth/`` and ``oauth_providers.py``,
without the chunked cookies, the stored refresh token or the photo bytes.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import datetime as dt
import hashlib
import hmac
import inspect
import json
import logging
import math
import os
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import unquote, urlencode, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from millwork import context
from millwork.access import Forbidden
from millwork.icons import check_icon
from millwork.nodes import Component, Tree, build
from millwork.scope import Scope
from millwork.shell import root_of
from millwork.theme import _check_path

log = logging.getLogger("millwork.auth")

CLAIMS_LIMIT = 2048
STATE_LIFETIME = 180
AUTH_COOKIE = "mw_auth"
STATE_COOKIE = "mw_oauth_state"
TOKEN_LIMIT = 8192


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key(secret: str, purpose: str) -> bytes:
    """A signing key for one purpose, so a token issued for one use never reads as another."""
    if not secret:
        raise ValueError("a signing secret is required")
    return hmac.new(secret.encode(), b"millwork:" + purpose.encode(), hashlib.sha256).digest()


def _mac(secret: str, purpose: str, body: str) -> str:
    return _b64(hmac.new(_key(secret, purpose), body.encode(), hashlib.sha256).digest())


def _expiry(payload: dict[str, Any]) -> float | None:
    """The payload's ``exp`` when it is a finite number, else None."""
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not math.isfinite(exp):
        return None
    return exp


def sign(secret: str, purpose: str, payload: dict[str, Any]) -> str:
    """A signed token: the JSON payload and an HMAC-SHA256 over it, both base64url.

    The payload must carry ``exp`` as a finite unix timestamp.
    """
    if _expiry(payload) is None:
        raise ValueError("a token needs a numeric exp")
    body = _b64(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
    return f"{body}.{_mac(secret, purpose, body)}"


def verify(secret: str, purpose: str, token: str | None) -> dict[str, Any] | None:
    """The payload of a token signed for ``purpose`` and not expired, else None.

    The signature is compared in constant time, as the exact text ``sign``
    produced, before the payload is decoded: nothing an attacker wrote is parsed.
    """
    if not token or len(token) > TOKEN_LIMIT or not token.isascii() or token.count(".") != 1:
        return None
    body, sig = token.split(".")
    if not hmac.compare_digest(sig.encode(), _mac(secret, purpose, body).encode()):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(payload, dict):
        return None
    exp = _expiry(payload)
    if exp is None or exp <= dt.datetime.now(dt.UTC).timestamp():
        return None
    return payload


class User(BaseModel):
    """What ``on_login`` returns and ``s.user`` holds."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    claims: dict[str, Any] = Field(default_factory=dict)
    picture_url: str | None = None


class Identity(BaseModel):
    """The normalised result of a provider, handed to ``on_login``."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    subject: str
    email: str | None = None
    name: str | None = None
    picture_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    intent: str | None = None


class NotFound(Exception):
    """Raised from ``connect`` when what the path names does not exist; the
    session lands on the app's not-found page."""

    def __init__(self, message: str | None = None) -> None:
        self.message = message
        super().__init__(message or "")


def email_of(raw: dict[str, Any]) -> str | None:
    """The address that identifies the signed-in user, from whichever claim carries an ``@``."""
    for key in ("mail", "email", "userPrincipalName", "preferred_username", "upn"):
        value = raw.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    return None


# ------------------------------------------------------------------ providers


BRANDS = ("microsoft", "google")
"""The provider marks the login page draws in the brand's own colors."""


def _provider_icon(icon: str | None) -> str | None:
    """What a sign-in button may show: a brand's mark, an image the app serves,
    or one of the bundle's icons by name."""
    if icon is None or icon in BRANDS:
        return icon
    if icon.startswith("/"):
        return _check_path(icon, "a provider's icon")
    return check_icon(icon)


class Provider:
    id: str
    label: str
    kind: Literal["oauth", "password", "header", "dev"]
    icon: str | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "kind": self.kind, "icon": self.icon}


class OAuth(Provider):
    """One OAuth2 authorization-code provider; any OIDC issuer fits."""

    kind: Literal["oauth", "password", "header", "dev"] = "oauth"

    def __init__(
        self,
        id: str,
        *,
        label: str,
        authorize_url: str,
        token_url: str,
        userinfo_url: str,
        client_id: str,
        client_secret: str,
        scopes: str,
        extra_params: dict[str, str] | None = None,
        icon: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.id = id
        self.label = label
        self.icon = _provider_icon(icon)
        self.authorize_url = authorize_url
        self.token_url = token_url
        self.userinfo_url = userinfo_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self.extra_params = extra_params or {}
        self._http = http

    def authorize(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": self.scopes,
            **self.extra_params,
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange(self, code: str, redirect_uri: str) -> dict[str, Any]:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        async with self._client() as client:
            r = await client.post(self.token_url, data=payload)
            r.raise_for_status()
            data: dict[str, Any] = r.json()
        if not data.get("access_token"):
            raise RuntimeError("the provider returned no access token")
        return data

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        async with self._client() as client:
            r = await client.get(
                self.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return data

    def identity(self, raw: dict[str, Any]) -> Identity:
        return Identity(
            provider=self.id,
            subject=str(raw.get("sub") or raw.get("id") or raw.get("oid") or email_of(raw) or ""),
            email=email_of(raw),
            name=raw.get("name") or raw.get("displayName"),
            picture_url=raw.get("picture") if isinstance(raw.get("picture"), str) else None,
            raw=raw,
        )

    def _client(self) -> AbstractAsyncContextManager[httpx.AsyncClient]:
        if self._http is not None:
            return _NonClosing(self._http)
        return httpx.AsyncClient(timeout=15)


class _NonClosing:
    """Use an injected client inside ``async with`` without closing it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *exc: object) -> None:
        return None


def AzureAD(
    *,
    tenant: str,
    client_id: str,
    client_secret: str,
    single_tenant: bool = True,
    scopes: str = "openid profile email User.Read",
    http: httpx.AsyncClient | None = None,
) -> OAuth:
    """Microsoft Entra ID (Azure AD). ``single_tenant`` keeps other tenants out at the issuer."""
    realm = tenant if single_tenant else "common"
    return OAuth(
        "azure-ad",
        label="Microsoft",
        authorize_url=f"https://login.microsoftonline.com/{realm}/oauth2/v2.0/authorize",
        token_url=f"https://login.microsoftonline.com/{realm}/oauth2/v2.0/token",
        userinfo_url="https://graph.microsoft.com/v1.0/me",
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        extra_params={"response_mode": "query"},
        icon="microsoft",
        http=http,
    )


def Google(*, client_id: str, client_secret: str, http: httpx.AsyncClient | None = None) -> OAuth:
    return OAuth(
        "google",
        label="Google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/userinfo/v2/me",
        client_id=client_id,
        client_secret=client_secret,
        scopes="openid email profile",
        icon="google",
        http=http,
    )


class Password(Provider):
    """A username and password checked by the app's callable."""

    kind: Literal["oauth", "password", "header", "dev"] = "password"

    def __init__(
        self, verify: Callable[[str, str], bool | Awaitable[bool]], label: str = "Password"
    ) -> None:
        self.id = "password"
        self.label = label
        self.verify = verify


class Headers(Provider):
    """The visitor as an authenticating reverse proxy names them in request headers.

    The proxy (oauth2-proxy, a platform's built-in sign-in, an access gateway)
    does the signing in and passes who it saw: a header with the user name
    or id, one with the e-mail, and perhaps the display name, the groups and a
    picture. Name the headers the proxy uses; ``user`` or ``email`` is required.
    The headers are read when the app is behind a proxy (``App(proxied=True)``,
    ``millwork run --proxied``) and go through ``on_login`` on every page load
    and socket connect, so keep that hook cheap.
    ``sign_out`` is the proxy's own sign-out URL, where the user menu sends the
    person; without one the menu has no sign-out, since the app has nothing to
    clear.
    """

    kind: Literal["oauth", "password", "header", "dev"] = "header"
    VALUE_LIMIT = 1024
    GROUPS_LIMIT = 8192

    def __init__(
        self,
        *,
        user: str | None = None,
        email: str | None = None,
        name: str | None = None,
        groups: str | None = None,
        picture: str | None = None,
        sign_out: str | None = None,
        label: str = "Proxy",
    ) -> None:
        if not (user or email):
            raise ValueError("Headers needs the name of the user header, the e-mail header or both")
        if sign_out is not None and not _sign_out_ok(sign_out):
            raise ValueError("sign_out is a path on this host or an http(s) URL")
        self.id = "header"
        self.label = label
        self.headers = {
            role: value.lower()
            for role, value in (
                ("user", user),
                ("email", email),
                ("name", name),
                ("groups", groups),
                ("picture", picture),
            )
            if value
        }
        self.sign_out = sign_out
        self._dropped: set[str] = set()

    def present(self, headers: Any) -> bool:
        return any(headers.get(h) for h in self.headers.values())

    def identity(self, headers: Any) -> Identity | None:
        """What the proxy says, or None when it names nobody. A value that is
        not plain text of a sane length is treated as absent, and so is a header
        that arrives more than once: a proxy that appends rather than replaces
        would otherwise let the visitor's own value through first."""
        raw: dict[str, Any] = {}
        for role, header in self.headers.items():
            given = _single(headers, header)
            limit = self.GROUPS_LIMIT if role == "groups" else self.VALUE_LIMIT
            value = _header_text(given, limit)
            if value is None:
                if given and role not in self._dropped:
                    self._dropped.add(role)
                    log.warning(
                        "the %s header (%s) was ignored: empty, over %d characters, "
                        "not printable, or sent more than once",
                        role,
                        header,
                        limit,
                    )
                continue
            raw[role] = (
                [g.strip() for g in value.split(",") if g.strip()] if role == "groups" else value
            )
        user, email = raw.get("user"), raw.get("email")
        if email is not None:
            email = email.lower()
        elif user is not None and "@" in user:
            email = user.lower()
        subject = user or email
        if subject is None:
            return None
        return Identity(
            provider=self.id,
            subject=subject,
            email=email,
            name=raw.get("name"),
            picture_url=raw.get("picture"),
            raw=raw,
        )


def _single(headers: Any, name: str) -> str | None:
    values = headers.getlist(name) if hasattr(headers, "getlist") else [headers.get(name)]
    return values[0] if len(values) == 1 else None


def _sign_out_ok(url: str) -> bool:
    """A path on this host (no scheme-relative or backslash spelling) or an http(s) URL."""
    if not url.isprintable() or " " in url or "\\" in url:
        return False
    if url.startswith("/"):
        return not url.startswith("//")
    return url.startswith(("https://", "http://")) and len(url) > 8


def _destination_ok(to: str) -> bool:
    """What ``on_logout`` may answer: an http(s) URL, or a path the tab will
    follow, which leaves out one with a dot segment in any spelling."""
    if not _sign_out_ok(to):
        return False
    if not to.startswith("/"):
        return True
    path = to.split("?", 1)[0].split("#", 1)[0]
    return not any(unquote(seg) in (".", "..") for seg in path.split("/"))


def _header_text(value: str | None, limit: int) -> str | None:
    """A header value as text: UTF-8 when the proxy sent it that way, trimmed,
    refused when empty, over the limit or not printable."""
    if not value:
        return None
    try:
        value = value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    value = value.strip()
    if not value or len(value) > limit or not value.isprintable():
        return None
    return value


class Dev(Provider):
    """Every visitor is this user. Refused outside debug mode."""

    kind: Literal["oauth", "password", "header", "dev"] = "dev"

    def __init__(self, user: User) -> None:
        self.id = "dev"
        self.label = "Development"
        self.user = user


# ------------------------------------------------------------------ passwords


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )
    return hmac.compare_digest(digest, expected)


# ------------------------------------------------------------------ the configuration


OnLogin = Callable[[Identity], User | None | Awaitable[User | None]]
OnLogout = Callable[[User], str | None | Awaitable[str | None]]
Recheck = Callable[[User], User | None | Awaitable[User | None]]

# How long ``on_logout`` may take. A sign-in that has run out ends its sessions
# whatever the hook does, so the hook cannot hold them open.
LOGOUT_HOOK_TIMEOUT = 10.0
# How long ``recheck`` may take before the question counts as unanswered.
RECHECK_HOOK_TIMEOUT = 10.0
# The loop calls a timer as soon as it is due within one step of its clock,
# which is 16 ms early at most on Windows before Python 3.13. Whoever waits
# an answer out with a timer has to find it run out when the timer calls.
TICK = time.get_clock_info("monotonic").resolution


def _left(span: float, since: float, now: float) -> float:
    """How much of ``span`` seconds is left ``now``, counted from ``since``,
    and nothing once less than a step of the clock is left. So a timer set
    for what is left finds none of it when it calls, early or not. A span
    counts for two steps at the least: a shorter one would never be found
    to have anything left, and whoever waits it out would never wait."""
    left = max(span, 2 * TICK) - (now - since)
    return left if left > TICK else 0.0


class Unanswered(Exception):
    """``Auth(recheck=)`` could not say who a user is now. Nothing is known,
    which is neither a yes nor a no."""


@dataclass
class _Answer:
    """What ``recheck`` said about an identified user: who they are now, and
    when it said so."""

    user: User | None
    at: float


class Auth:
    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        on_login: OnLogin | None = None,
        on_logout: OnLogout | None = None,
        recheck: Recheck | None = None,
        recheck_every: dt.timedelta = dt.timedelta(minutes=5),
        session: dt.timedelta = dt.timedelta(days=7),
        log_identity: Literal["plain", "hashed"] = "plain",
        intents: dict[str, str] | None = None,
        login: Component | None = None,
    ) -> None:
        self.providers = {p.id: p for p in providers}
        self.on_login = on_login
        self.on_logout = on_logout
        # Who the signed-in person is now: asked with the user the cookie
        # holds, it returns the user as they are today, or None when they are
        # no longer welcome. Without it a sign-in is what it was when it was
        # made, until it expires.
        self.recheck = recheck
        if recheck_every.total_seconds() <= 0:
            raise ValueError("recheck_every is a length of time above zero")
        self.recheck_every = recheck_every.total_seconds()
        # The last answer per sign-in, so a person is asked about once per
        # interval however many requests they make, the question in flight for
        # each, and when the hook last failed for it.
        self._answers: dict[str, _Answer] = {}
        self._asking: dict[str, asyncio.Task[User | None | Unanswered]] = {}
        # The questions out to ``recheck`` and ``on_logout``. The app stops
        # them when it stops.
        self.scope = Scope("auth")
        self._failed: dict[str, float] = {}
        self._retry_after = min(self.recheck_every, 5.0)
        # Who each person without a cookie was last identified as, and when.
        self._seen: dict[str, tuple[User, float]] = {}
        self._tidied = 0.0
        # How many times running a hook changed its answer about a person.
        self._changes: dict[str, int] = {}
        self._warned_restless = False
        self.session = session
        self.log_identity = log_identity
        self.intents = intents or {}
        # The login page under its heading, laid out by the app: any components
        # that need no session, with a ``ui.SignIn`` where each way in goes.
        if login is not None and not isinstance(login, Component):
            raise TypeError(
                "Auth(login=) takes one component, a ui.Stack of them for several, "
                f"not {type(login).__name__}"
            )
        self.login_page = login
        self.secret = ""
        self.debug = False
        self._warned_unproxied = False
        if login is not None:
            self._check_layout()

    def bind(
        self, secret: str, debug: bool, origins: list[str] | None = None, app: str = ""
    ) -> None:
        # Tokens are signed for this app by name, so apps that share a secret
        # still keep their sign-ins apart.
        self.secret = secret
        self.app = app
        self.debug = debug
        self.origins = list(origins or [])
        if any(isinstance(p, Dev) for p in self.providers.values()) and not debug:
            raise RuntimeError("the Dev auth provider is only allowed with App(debug=True)")

    # ------------------------------------------------------------- tokens

    def issue(self, user: User) -> str:
        if len(json.dumps(user.claims)) > CLAIMS_LIMIT:
            raise ValueError("user claims exceed 2 KB; keep the record small")
        now = dt.datetime.now(dt.UTC)
        payload = {
            **user.model_dump(mode="json"),
            "iat": int(now.timestamp()),
            "exp": int((now + self.session).timestamp()),
            "jti": secrets.token_urlsafe(8),
        }
        return sign(self.secret, f"auth:{self.app}", payload)

    def read(self, token: str | None) -> User | None:
        signed_in = self._read(token)
        return signed_in[0] if signed_in is not None else None

    def _read(self, token: str | None) -> tuple[User, str, float] | None:
        """The user a token holds, the id of that one sign-in, and when it
        expires in seconds since the epoch."""
        data = verify(self.secret, f"auth:{self.app}", token)
        if data is None:
            return None
        fields = {k: v for k, v in data.items() if k in User.model_fields}
        try:
            return User(**fields), str(data["jti"]), float(data["exp"])
        except Exception:
            return None

    def user_from(self, request: Request) -> User | None:
        """The signed-in user of an HTTP request (or a websocket's handshake)."""
        return self.read(request.cookies.get(cookie_name(request.scope, AUTH_COOKIE)))

    def set_cookie(self, request: Request, response: Response, user: User) -> None:
        response.set_cookie(
            cookie_name(request.scope, AUTH_COOKIE),
            self.issue(user),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=int(self.session.total_seconds()),
            path=_cookie_path(request),
        )

    def clear_cookie(self, request: Request, response: Response) -> None:
        response.delete_cookie(cookie_name(request.scope, AUTH_COOKIE), path=_cookie_path(request))

    # ------------------------------------------------------------- login

    def layout(self, either: str = "or") -> Component:
        """What the login page shows under its heading: the app's own layout, or
        every OAuth provider's button, a button per intent, and the password
        form, with ``either`` on the line between buttons and form."""
        from millwork import ui

        if self.login_page is not None:
            return self.login_page
        oauth = [p for p in self.providers.values() if p.kind == "oauth"]
        buttons: list[Component] = [ui.SignIn(p.id) for p in oauth]
        if oauth:
            buttons += [ui.SignIn(oauth[0].id, intent=intent) for intent in self.intents]
        parts: list[Component] = [ui.Stack(*buttons, gap=2)] if buttons else []
        form = next((p for p in self.providers.values() if p.kind == "password"), None)
        if form is not None:
            if buttons:
                parts.append(ui.Separator(label=either))
            parts.append(ui.SignIn(form.id))
        return ui.Stack(*parts, gap=6)

    def _tree(self, either: str = "or") -> Tree:
        """The login page's layout as nodes, built with this Auth in scope so a
        ``ui.SignIn`` finds its provider without a session."""
        token = context._auth.set(self)
        try:
            return build(self.layout(either), "login")
        finally:
            context._auth.reset(token)

    def _check_layout(self) -> None:
        """Refuse a layout the login page cannot draw, when the app starts and
        not when the first visitor arrives."""
        tree = self._tree()
        # No session exists before sign-in, so nothing there can call Python.
        for node_id, name in [*tree.handlers, *tree.callables]:
            raise ValueError(
                f"the login page has no session, so {tree.nodes[node_id].type}'s "
                f"{name} cannot run there"
            )
        for node_id in tree.session_bound:
            raise ValueError(
                f"the login page has no session, and a {tree.nodes[node_id].type} "
                "does nothing without one"
            )
        placed = {n.props["provider"] for n in tree.nodes.values() if n.type == "SignIn"}
        for p in self.providers.values():
            if p.kind in ("oauth", "password") and p.id not in placed:
                # Leaving it off the page hides it and no more: its sign-in
                # still answers until it leaves the list of providers.
                log.warning(
                    "the login page has no ui.SignIn(%r): that provider is not shown there", p.id
                )

    def describe(
        self, next_path: str, error: str | None = None, either: str = "or"
    ) -> dict[str, Any]:
        """What the login page needs, and nothing a browser should not see."""
        tree = self._tree(either)
        return {
            "root": tree.root,
            "nodes": {
                node_id: node.model_dump(mode="json") for node_id, node in tree.nodes.items()
            },
            "proxied": any(isinstance(p, Headers) for p in self.providers.values()),
            "next": next_path,
            "error": error,
        }

    async def login(self, identity: Identity) -> User | None:
        """Run the hook, log the outcome, enforce the record size."""
        if self.on_login is None:
            if identity.email is None:
                log.warning(
                    "login denied: provider %s gave no e-mail and there is no on_login",
                    identity.provider,
                )
                return None
            user: User | None = User(
                id=identity.email,
                name=identity.name or identity.email,
                picture_url=identity.picture_url,
            )
        else:
            # A sync hook runs off the loop: with a proxy identity it runs on
            # every page load, and a slow one would stall every session.
            if inspect.iscoroutinefunction(self.on_login):
                user = await self.on_login(identity)
            else:
                result = await asyncio.to_thread(self.on_login, identity)
                user = await result if inspect.isawaitable(result) else result
        who = self._log_id(identity.email or identity.subject)
        if user is None:
            log.warning("login denied: %s via %s", who, identity.provider)
            return None
        if len(json.dumps(user.claims)) > CLAIMS_LIMIT:
            log.error("login denied: claims for %s exceed 2 KB", who)
            return None
        # A proxy identity is re-read on every page load, so it is not news.
        log.log(
            logging.DEBUG if identity.provider == "header" else logging.INFO,
            "login: %s via %s",
            who,
            identity.provider,
        )
        return user

    async def leave(self, user: User) -> str | None:
        """Where a person goes when a sign-in of theirs ends, as ``on_logout``
        says: a path on the app or an http(s) URL, or None for the login page.
        A hook that fails, takes too long, or answers with anything else is
        logged and counts as None, since the person leaves either way."""
        if self.on_logout is None:
            return None
        who = self._log_id(user.id)
        try:
            async with asyncio.timeout(LOGOUT_HOOK_TIMEOUT):
                if inspect.iscoroutinefunction(self.on_logout):
                    to = await self.on_logout(user)
                else:
                    result = await asyncio.to_thread(self.on_logout, user)
                    to = await result if inspect.isawaitable(result) else result
        except TimeoutError:
            log.error("on_logout took over %g seconds for %s", LOGOUT_HOOK_TIMEOUT, who)
            return None
        except asyncio.CancelledError:
            # The hook's own cancellation, say of a task it awaited, is one more
            # way for it to fail. Only a cancellation of this call passes on.
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            log.error("on_logout was cancelled for %s", who)
            return None
        except Exception:
            log.exception("on_logout failed for %s", who)
            return None
        if to is None:
            return None
        if not isinstance(to, str) or not _destination_ok(to):
            log.error("on_logout returns a path on the app, an http(s) URL or None, not %r", to)
            return None
        return to

    async def current(self, key: str, user: User) -> User | None:
        """The user as they are now, or None when they are no longer welcome.

        ``key`` names the sign-in, and ``user`` is the user as identified,
        before any recheck. The answer is kept for ``recheck_every`` on this
        process alone, so each replica asks for itself and none needs a store
        to share. Everyone asking about one identified user at once waits for
        the same answer, so nothing goes ahead on an old one while a new one
        is on its way. A hook that fails or takes too long raises
        ``Unanswered``: nothing is known then, which is not a refusal, and the
        hook is left alone for a moment before it is asked again."""
        if self.recheck is None:
            return user
        slot = self._slot(key, user)
        now = time.monotonic()
        kept = self._answers.get(slot)
        if kept is not None and _left(self.recheck_every, kept.at, now) > 0:
            return kept.user
        failed = self._failed.get(slot)
        if failed is not None and _left(self._retry_after, failed, now) > 0:
            raise Unanswered("recheck gave no answer a moment ago")
        asking = self._asking.get(slot)
        if asking is None:
            asking = self.scope.start(
                self._ask_quietly(slot, user), "recheck", done=lambda _: self._asked(slot)
            )
            if asking is None:
                raise Unanswered("the app is stopping")
            self._asking[slot] = asking
        try:
            answer = await asyncio.shield(asking)
        except asyncio.CancelledError:
            # The question was stopped, with the app. Whoever asked is told
            # there is no answer, unless they are being stopped themselves.
            me = asyncio.current_task()
            if me is not None and me.cancelling():
                raise
            raise Unanswered("the app is stopping") from None
        if isinstance(answer, Unanswered):
            raise answer
        return answer

    @staticmethod
    def _slot(key: str, user: User) -> str:
        """Where the answer about one identified user is kept. A cookie names
        one user for good. A proxy or Dev names a person, who may be
        identified differently from one request to the next, and an answer
        about one of those users is no answer about another."""
        if not key.startswith("user:"):
            return key
        return f"{key}|{hashlib.sha256(user.model_dump_json().encode()).hexdigest()[:16]}"

    def _asked(self, slot: str) -> None:
        self._asking.pop(slot, None)

    async def _ask_quietly(self, slot: str, user: User) -> User | None | Unanswered:
        """The answer, or that there was none, as a value: several may be
        waiting on one question, and one nobody waits on is nobody's error."""
        try:
            return await self._ask(slot, user)
        except Unanswered as none:
            return none

    async def _ask(self, slot: str, user: User) -> User | None:
        assert self.recheck is not None
        who = self._log_id(user.id)
        try:
            async with asyncio.timeout(RECHECK_HOOK_TIMEOUT):
                if inspect.iscoroutinefunction(self.recheck):
                    fresh = await self.recheck(user)
                else:
                    result = await asyncio.to_thread(self.recheck, user)
                    fresh = await result if inspect.isawaitable(result) else result
            if fresh is not None and not isinstance(fresh, User):
                raise TypeError(f"recheck returns a User or None, not {type(fresh).__name__}")
            if fresh is not None and fresh.id != user.id:
                raise ValueError("recheck returned another person: the user's id may not change")
        except Exception as exc:
            self._failed[slot] = time.monotonic()
            self._tidy()
            log.exception("recheck gave no answer for %s", who)
            raise Unanswered(f"recheck failed: {exc}") from exc
        if fresh is None:
            log.warning("sign-in ended by recheck: %s", who)
        self._failed.pop(slot, None)
        before = self._answers.get(slot)
        if before is not None and before.user is not None and fresh is not None:
            self._restless(slot, before.user != fresh, "recheck")
        answer: User | None = fresh
        self._answers[slot] = _Answer(user=answer, at=time.monotonic())
        self._tidy()
        return answer

    def _restless(self, key: str, changed: bool, hook: str) -> None:
        """Say so, once, when a hook gives a different user for the same
        person time after time. A session ends when its user changes, so a
        field that is new on every call, a time say, reloads their tabs for
        as long as it goes on."""
        if not changed:
            self._changes.pop(key, None)
            return
        times = self._changes.get(key, 0) + 1
        self._changes[key] = times
        if times == 3 and not self._warned_restless:
            self._warned_restless = True
            log.warning(
                "%s returned a different user three times running for the same person. "
                "A session ends when its user changes, so their tabs keep reloading. "
                "Return the same user while nothing about them has changed",
                hook,
            )

    def _tidy(self) -> None:
        """Drop what is of no use to anyone any more, once there is a lot of
        it and at most once per interval: answers past twice their interval,
        failures past their retry, and who a person was last identified as
        once nothing has asked about them for that long."""
        now = time.monotonic()
        many = len(self._answers) + len(self._failed) + len(self._seen) > 4096
        if not many or now - self._tidied < self.recheck_every:
            return
        self._tidied = now
        limit = 2 * self.recheck_every
        self._answers = {k: v for k, v in self._answers.items() if now - v.at < limit}
        self._failed = {k: at for k, at in self._failed.items() if now - at < self._retry_after}
        self._changes = {}
        self._seen = {k: v for k, v in self._seen.items() if now - v[1] < max(limit, 3600.0)}

    def identified_as(self, key: str, user: User) -> User:
        """The user a person was last identified as. For a cookie that is the
        one it holds. A proxy's word about a person can change, and a session
        opened on the old word has to find out."""
        seen = self._seen.get(key)
        return user if seen is None else seen[0]

    def answer_age(self, key: str, user: User) -> float | None:
        """How old the last answer about an identified user is, in seconds,
        or None when there is none."""
        kept = self._answers.get(self._slot(key, user))
        return None if kept is None else time.monotonic() - kept.at

    def ask_again_in(self, key: str, user: User) -> float:
        """How long until an identified user is next worth asking about: when
        the answer runs out, or when a hook that failed may be tried again."""
        slot = self._slot(key, user)
        now = time.monotonic()
        failed = self._failed.get(slot)
        wait = 0.0 if failed is None else _left(self._retry_after, failed, now)
        if wait > 0:
            return wait
        kept = self._answers.get(slot)
        return 0.0 if kept is None else _left(self.recheck_every, kept.at, now)

    def _log_id(self, value: str) -> str:
        if self.log_identity == "hashed":
            return hashlib.sha256(value.encode()).hexdigest()[:12]
        return value

    # ------------------------------------------------------------- the routes

    async def route_login(self, request: Request) -> Response:
        """``POST /_mw/auth/login`` with a username and password."""
        provider = next((p for p in self.providers.values() if isinstance(p, Password)), None)
        if provider is None:
            return JSONResponse({"reason": "password sign-in is not configured"}, status_code=404)
        # Only the app's own page can post here: a JSON body (a cross-site form
        # cannot send one without a preflight) from the same origin.
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "application/json" or not _same_origin(request, self.origins):
            return JSONResponse({"reason": "bad request"}, status_code=400)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"reason": "bad request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"reason": "bad request"}, status_code=400)
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not username or not password:
            return JSONResponse({"reason": "username and password are required"}, status_code=400)
        # A password check is slow by design (scrypt): off the loop, so a burst of
        # wrong passwords stalls nothing else.
        if inspect.iscoroutinefunction(provider.verify):
            ok = await provider.verify(username, password)
        else:
            ok = await asyncio.to_thread(provider.verify, username, password)
            if inspect.isawaitable(ok):
                ok = await ok
        if not ok:
            log.warning("login denied: %s via password", self._log_id(username))
            return JSONResponse({"reason": "wrong username or password"}, status_code=401)
        user = await self.login(
            Identity(
                provider="password",
                subject=username,
                email=username if "@" in username else None,
                name=username,
            )
        )
        if user is None:
            return JSONResponse({"reason": "access denied"}, status_code=403)
        response = JSONResponse({"ok": True, "user": user.model_dump(mode="json")})
        self.set_cookie(request, response, user)
        return response

    async def route_logout(self, request: Request) -> Response:
        """Clear the cookie, and end the user's live sessions on this process. The
        cookie itself stays valid until it expires: it is signed, not stored.
        The answer carries where ``on_logout`` sends the tab, None for the
        login page. Only the app's own pages can ask, since this runs the
        app's hook and ends its sessions."""
        if not _same_origin(request, self.origins):
            return JSONResponse({"reason": "bad request"}, status_code=400)
        # Who is leaving, as identified: signing out works when ``recheck``
        # cannot answer, and for someone it would turn away.
        user = await self.identify(request, recheck=False)
        to = await self.leave(user) if user is not None else None
        response = JSONResponse({"ok": True, "next": to})
        self.clear_cookie(request, response)
        app = getattr(request.app.state, "millwork", None)
        if user is not None and app is not None:
            theirs = [
                s for s in app.sessions.values() if s.user is not None and s.user.id == user.id
            ]
            # All of them are over at once, and each tab is then told on its
            # own, so one that is slow to listen keeps none of the others.
            said = app.theme.text("signed_out")
            for session in theirs:
                session.dismiss(said)
        return response

    async def route_oauth_start(self, request: Request) -> Response:
        provider = self.providers.get(request.path_params["provider"])
        if not isinstance(provider, OAuth):
            return JSONResponse({"reason": "no such provider"}, status_code=404)
        state = secrets.token_urlsafe(24)
        next_path = _safe_next(request.query_params.get("next"))
        intent = request.query_params.get("intent")
        if intent and intent not in self.intents:
            intent = None
        payload = {
            "state": state,
            "next": next_path,
            "intent": intent,
            "exp": int(dt.datetime.now(dt.UTC).timestamp()) + STATE_LIFETIME,
        }
        signed = sign(self.secret, f"oauth-state:{self.app}", payload)
        response = RedirectResponse(
            provider.authorize(self._callback_url(request, provider), state), status_code=302
        )
        response.set_cookie(
            cookie_name(request.scope, STATE_COOKIE),
            signed,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=STATE_LIFETIME,
            path=_cookie_path(request),
        )
        return response

    async def route_oauth_callback(self, request: Request) -> Response:
        provider = self.providers.get(request.path_params["provider"])
        if not isinstance(provider, OAuth):
            return JSONResponse({"reason": "no such provider"}, status_code=404)
        q = request.query_params
        state = request.cookies.get(cookie_name(request.scope, STATE_COOKIE))
        state_data = verify(self.secret, f"oauth-state:{self.app}", state)
        if state_data is None:
            return self._login_redirect(request, "/", "Sign-in expired, try again.")
        next_path = _safe_next(state_data.get("next"))
        if q.get("error") or not q.get("code") or not q.get("state"):
            log.warning("oauth %s returned %s", provider.id, q.get("error") or "no code")
            return self._login_redirect(request, next_path, "Sign-in was cancelled.")
        if not hmac.compare_digest(str(state_data.get("state")).encode(), q["state"].encode()):
            return self._login_redirect(request, next_path, "Sign-in state did not match.")
        try:
            tokens = await provider.exchange(q["code"], self._callback_url(request, provider))
            raw = await provider.userinfo(tokens["access_token"])
        except Exception:
            log.exception("oauth %s exchange failed", provider.id)
            return self._login_redirect(request, next_path, "Sign-in failed at the provider.")
        identity = provider.identity(raw)
        identity.intent = state_data.get("intent")
        user = await self.login(identity)
        if user is None:
            return self._login_redirect(request, next_path, "Access denied.")
        response = RedirectResponse(f"{root_of(request.scope)}{next_path}", status_code=302)
        self.set_cookie(request, response, user)
        response.delete_cookie(cookie_name(request.scope, STATE_COOKIE), path=_cookie_path(request))
        return response

    def _callback_url(self, request: Request, provider: OAuth) -> str:
        # The scheme and host as the proxy forwarded them, then the prefix from
        # the scope: base_url would take the outer app's root under a mount.
        url = request.url
        return f"{url.scheme}://{url.netloc}{root_of(request.scope)}/_mw/auth/oauth/{provider.id}/callback"

    def _login_redirect(self, request: Request, next_path: str, error: str) -> Response:
        root = root_of(request.scope)
        return RedirectResponse(
            f"{root}/_mw/login?{urlencode({'next': next_path, 'error': error})}", status_code=302
        )

    # ------------------------------------------------------------- request-time identity

    async def identify(self, request_or_scope: Any, recheck: bool = True) -> User | None:
        """The user behind a request or websocket: the cookie, the proxy's headers, or Dev.

        The proxy's headers go through ``on_login`` like any other provider, on
        every request: the hook still decides access and shapes the user. They
        are read when the app is behind a proxy. Whoever is identified is then
        put to the app's ``recheck``, which has the last word on who they are
        now. ``recheck=False`` leaves that out, for knowing who is signing out.
        """
        headers = request_or_scope.headers
        scope = request_or_scope.scope

        async def now(key: str, user: User, by: str) -> User | None:
            """What ``recheck`` makes of the user identified. The key and the
            user as identified travel with the request, for a session that
            goes on asking."""
            if key.startswith("user:"):
                seen = self._seen.get(key)
                if seen is not None and by == "header":
                    self._restless(f"seen:{key}", seen[0] != user, "on_login")
                self._seen[key] = (user, time.monotonic())
                self._tidy()
            fresh = await self.current(key, user) if recheck else user
            if fresh is None:
                # Identified, and no longer welcome.
                scope["millwork.revoked"] = True
                return None
            scope["millwork.identified_by"] = by
            scope["millwork.identified"] = (key, user)
            return fresh

        signed_in = self._read(request_or_scope.cookies.get(cookie_name(scope, AUTH_COOKIE)))
        if signed_in is not None:
            user = await now(signed_in[1], signed_in[0], "cookie")
            if user is not None:
                # A session opened on this sign-in ends with it, so which one
                # it is and when it expires travel with the request.
                scope["millwork.sign_in"] = signed_in[1:]
            return user
        for provider in self.providers.values():
            if isinstance(provider, Dev):
                return await now(f"user:{provider.user.id}", provider.user, "dev")
            if isinstance(provider, Headers):
                if not scope.get("millwork.proxied"):
                    if provider.present(headers) and not self._warned_unproxied:
                        self._warned_unproxied = True
                        log.warning(
                            "identity headers arrived and were ignored: the app is not "
                            "marked as behind a proxy (App(proxied=True), millwork run --proxied)"
                        )
                    continue
                identity = provider.identity(headers)
                if identity is not None:
                    user = await self.login(identity)
                    return None if user is None else await now(f"user:{user.id}", user, "header")
        return None

    def proxy_identity(self, request: Request) -> bool:
        """Whether the proxy named a visitor on this request, whatever the hook
        then said."""
        if not request.scope.get("millwork.proxied"):
            return False
        return any(
            isinstance(p, Headers) and p.present(request.headers) for p in self.providers.values()
        )

    @property
    def sign_out(self) -> str | None | bool:
        """Where sign-out goes: the proxy's URL with a Headers provider, False
        when that provider has none, None when millwork's own login is in charge."""
        for provider in self.providers.values():
            if isinstance(provider, Headers):
                return provider.sign_out or False
        return None


def _same_origin(request: Request, origins: list[str]) -> bool:
    """No Origin header (not a browser), the request's own host, or an allowed origin."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    if origins:
        return origin in origins
    host = request.headers.get("host")
    return host is not None and urlsplit(origin).netloc.lower() == host.lower()


def _safe_next(value: str | None) -> str:
    """Only a path inside the app: never an absolute URL, a scheme-relative one,
    a dot segment that could climb out of the app's prefix, or a framework route.

    A backslash is refused outright: browsers read a slash-backslash prefix as
    a scheme-relative URL. Dot segments are matched after percent-decoding,
    since a browser decodes ``%2e`` before it resolves the path.
    """
    if not (value and value.startswith("/") and not value.startswith("//")):
        return "/"
    if "\\" in value or not value.isprintable():
        return "/"
    path = value.split("?", 1)[0].split("#", 1)[0]
    segments = [unquote(seg).lower() for seg in path.split("/")]
    if any(seg in (".", "..") for seg in segments):
        return "/"
    if len(segments) > 1 and segments[1] == "_mw":
        return "/"
    return value


def cookie_name(scope: Mapping[str, Any], base: str) -> str:
    """The cookie's name carries the app's prefix: ``mw_auth`` at the root,
    ``mw_auth_sales`` under ``/sales``. Apps side by side on one host then each
    read their own cookie, whatever the browser sends along. Two prefixes can
    share a name (``/a/b`` and ``/a_b``), which is harmless: their paths never
    overlap, so a browser never sends both cookies to one app."""
    return base + root_of(scope).replace("/", "_")


def _cookie_path(request: Request) -> str:
    """The cookie's path is the app's prefix, so the browser sends it there only."""
    return root_of(request.scope) or "/"


__all__ = [
    "Auth",
    "AzureAD",
    "Dev",
    "Forbidden",
    "Google",
    "Headers",
    "Identity",
    "NotFound",
    "OAuth",
    "Password",
    "User",
    "check_password",
    "email_of",
    "hash_password",
]

_ = os  # the module reads no environment variables of its own; the name is kept for grep
