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
import datetime as dt
import hashlib
import hmac
import inspect
import json
import logging
import os
import secrets
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
import jwt as pyjwt
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

log = logging.getLogger("millwork.auth")

CLAIMS_LIMIT = 2048
STATE_LIFETIME = 180
AUTH_COOKIE = "mw_auth"
STATE_COOKIE = "mw_oauth_state"


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


class Forbidden(Exception):
    """Raised from ``connect`` when the user may not open this page."""

    def __init__(self, message: str = "You may not open this page.") -> None:
        self.message = message
        super().__init__(message)


class NotFound(Exception):
    def __init__(self, message: str = "Not found.") -> None:
        self.message = message
        super().__init__(message)


def email_of(raw: dict[str, Any]) -> str | None:
    """The address that identifies the signed-in user, from whichever claim carries an ``@``."""
    for key in ("mail", "email", "userPrincipalName", "preferred_username", "upn"):
        value = raw.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    return None


# ------------------------------------------------------------------ providers


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
        self.icon = icon
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


class Header(Provider):
    """An identity header set by a trusted reverse proxy (Container Apps auth, oauth2-proxy)."""

    kind: Literal["oauth", "password", "header", "dev"] = "header"

    def __init__(self, name: str, *, trusted_proxies: list[str], label: str = "Proxy") -> None:
        self.id = "header"
        self.label = label
        self.header = name.lower()
        self.trusted_proxies = set(trusted_proxies)


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


class Auth:
    def __init__(
        self,
        providers: list[Provider],
        *,
        on_login: OnLogin | None = None,
        session: dt.timedelta = dt.timedelta(days=7),
        log_identity: Literal["plain", "hashed"] = "plain",
        intents: dict[str, str] | None = None,
    ) -> None:
        self.providers = {p.id: p for p in providers}
        self.on_login = on_login
        self.session = session
        self.log_identity = log_identity
        self.intents = intents or {}
        self.secret = ""
        self.debug = False

    def bind(self, secret: str, debug: bool, origins: list[str] | None = None) -> None:
        self.secret = secret
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
            "iat": now,
            "exp": now + self.session,
            "jti": secrets.token_urlsafe(8),
        }
        return pyjwt.encode(payload, self.secret, algorithm="HS256")

    def read(self, token: str | None) -> User | None:
        if not token:
            return None
        try:
            data = pyjwt.decode(token, self.secret, algorithms=["HS256"])
        except pyjwt.PyJWTError:
            return None
        data = {k: v for k, v in data.items() if k in User.model_fields}
        try:
            return User(**data)
        except Exception:
            return None

    def user_from(self, request: Request) -> User | None:
        """The signed-in user of an HTTP request (or a websocket's handshake)."""
        return self.read(request.cookies.get(AUTH_COOKIE))

    def set_cookie(self, request: Request, response: Response, user: User) -> None:
        response.set_cookie(
            AUTH_COOKIE,
            self.issue(user),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=int(self.session.total_seconds()),
            path=request.scope.get("root_path") or "/",
        )

    def clear_cookie(self, request: Request, response: Response) -> None:
        response.delete_cookie(AUTH_COOKIE, path=request.scope.get("root_path") or "/")

    # ------------------------------------------------------------- login

    def describe(self, next_path: str, error: str | None = None) -> dict[str, Any]:
        """What the login page needs, and nothing a browser should not see."""
        return {
            "providers": [
                p.public() for p in self.providers.values() if p.kind in ("oauth", "password")
            ],
            "intents": [{"id": k, "label": v} for k, v in self.intents.items()],
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
            result = self.on_login(identity)
            user = await result if inspect.isawaitable(result) else result
        who = self._log_id(identity.email or identity.subject)
        if user is None:
            log.warning("login denied: %s via %s", who, identity.provider)
            return None
        if len(json.dumps(user.claims)) > CLAIMS_LIMIT:
            log.error("login denied: claims for %s exceed 2 KB", who)
            return None
        log.info("login: %s via %s", who, identity.provider)
        return user

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
        cookie itself stays valid until it expires: it is signed, not stored."""
        response = JSONResponse({"ok": True})
        self.clear_cookie(request, response)
        user = await self.identify(request)
        app = getattr(request.app.state, "millwork", None)
        if user is not None and app is not None:
            for session in list(app.sessions.values()):
                if session.user is not None and session.user.id == user.id:
                    await session.end("Signed out.")
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
        signed = pyjwt.encode(payload, self.secret, algorithm="HS256")
        response = RedirectResponse(
            provider.authorize(self._callback_url(request, provider), state), status_code=302
        )
        response.set_cookie(
            STATE_COOKIE,
            signed,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=STATE_LIFETIME,
        )
        return response

    async def route_oauth_callback(self, request: Request) -> Response:
        provider = self.providers.get(request.path_params["provider"])
        if not isinstance(provider, OAuth):
            return JSONResponse({"reason": "no such provider"}, status_code=404)
        q = request.query_params
        try:
            state_data = pyjwt.decode(
                request.cookies.get(STATE_COOKIE, ""), self.secret, algorithms=["HS256"]
            )
        except pyjwt.PyJWTError:
            return self._login_redirect(request, "/", "Sign-in expired, try again.")
        next_path = _safe_next(state_data.get("next"))
        if q.get("error") or not q.get("code") or not q.get("state"):
            log.warning("oauth %s returned %s", provider.id, q.get("error") or "no code")
            return self._login_redirect(request, next_path, "Sign-in was cancelled.")
        if not hmac.compare_digest(str(state_data.get("state")), q["state"]):
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
        response = RedirectResponse(next_path, status_code=302)
        self.set_cookie(request, response, user)
        response.delete_cookie(STATE_COOKIE)
        return response

    def _callback_url(self, request: Request, provider: OAuth) -> str:
        base = str(request.base_url).rstrip("/")
        root = request.scope.get("root_path") or ""
        return f"{base}{root}/_mw/auth/oauth/{provider.id}/callback"

    def _login_redirect(self, request: Request, next_path: str, error: str) -> Response:
        root = request.scope.get("root_path") or ""
        return RedirectResponse(
            f"{root}/_mw/login?{urlencode({'next': next_path, 'error': error})}", status_code=302
        )

    # ------------------------------------------------------------- request-time identity

    async def identify(self, request_or_scope: Any) -> User | None:
        """The user behind a request or websocket: the cookie, a trusted header, or Dev.

        A proxy header goes through ``on_login`` like any other provider, on
        every request: the hook still decides access and shapes the user.
        """
        headers = request_or_scope.headers
        cookies = (
            request_or_scope.cookies if hasattr(request_or_scope, "cookies") else _cookies(headers)
        )
        user = self.read(cookies.get(AUTH_COOKIE))
        if user is not None:
            return user
        for provider in self.providers.values():
            if isinstance(provider, Dev):
                return provider.user
            if isinstance(provider, Header):
                client = getattr(request_or_scope, "client", None)
                peer = client.host if client else None
                value = headers.get(provider.header)
                if value and peer in provider.trusted_proxies:
                    return await self.login(
                        Identity(
                            provider="header",
                            subject=value,
                            email=value if "@" in value else None,
                            name=value,
                        )
                    )
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


def _cookies(headers: Any) -> dict[str, str]:
    raw = headers.get("cookie", "")
    out: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            k, _, v = part.strip().partition("=")
            out[k] = v
    return out


def _safe_next(value: str | None) -> str:
    """Only a same-origin path: never an absolute URL or a scheme-relative one.

    A backslash is refused outright: browsers read a slash-backslash prefix as
    a scheme-relative URL.
    """
    if (
        value
        and value.startswith("/")
        and not value.startswith("//")
        and not value.startswith("/_mw/")
        and "\\" not in value
        and value.isprintable()
    ):
        return value
    return "/"


__all__ = [
    "Auth",
    "AzureAD",
    "Dev",
    "Forbidden",
    "Google",
    "Header",
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
