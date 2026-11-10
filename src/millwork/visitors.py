"""Visitors: a name for the browser behind a session.

With ``App(identify_visitors=True)`` a browser gets an id in a signed cookie
on its first page load, and every session opened from it carries the id as
``s.visitor.id``. The id names the browser and nothing more. The framework
keeps nothing under it: what an app stores for a visitor, and for how long,
is the app's.

The cookie also remembers who was signed in when it was issued, and an id is
good only for them. A browser therefore gets a new id when someone signs in,
and again when they sign out or their sign-in ends. Every session that holds
an id issued to a signed-in person is a session of that person, and ends
with their sign-in, so nothing pinned to the id is left within reach of
whoever uses the browser next.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import dataclass
from typing import Any

from starlette.requests import HTTPConnection, Request
from starlette.responses import Response

from millwork.auth import _cookie_path, _mac, cookie_name, sign, verify

VISITOR_COOKIE = "mw_visitor"
# The cookie has no lifetime of its own, so the browser drops it when it
# closes. This bounds a copy of it that was kept somewhere else.
TOKEN_LIFE = dt.timedelta(days=365)


def new_id() -> str:
    return secrets.token_urlsafe(16)


@dataclass(frozen=True, slots=True)
class Visitor:
    """What ``s.visitor`` holds: the browser a session was opened from."""

    id: str


class Visitors:
    """The visitor cookie of one app: what it holds, and when it is replaced."""

    def __init__(self, secret: str, app: str) -> None:
        self.secret = secret
        # Signed for this app by name, as a sign-in is, so apps that share a
        # secret each hand out ids of their own. What remembers the user is
        # keyed apart from the cookie, under a purpose no app's name can
        # turn into the cookie's, so neither is ever read as the other.
        self.purpose = f"visitor:{app}"
        self._user_purpose = f"visitor-user:{app}"

    def _mark(self, visitor_id: str, user: Any) -> str | None:
        """Who is signed in, as the cookie remembers them: a keyed hash of
        the user with the id. It tells nobody who used the browser last, and
        the cookies of one person's two browsers have nothing in common."""
        if user is None:
            return None
        return _mac(self.secret, self._user_purpose, json.dumps([visitor_id, str(user.id)]))

    def issue(self, visitor_id: str, user: Any) -> str:
        expires = dt.datetime.now(dt.UTC) + TOKEN_LIFE
        payload = {
            "id": visitor_id,
            "user": self._mark(visitor_id, user),
            "exp": int(expires.timestamp()),
        }
        return sign(self.secret, self.purpose, payload)

    def read(self, token: str | None, user: Any) -> str | None:
        """The id a cookie holds, when it was issued to whoever is asking
        now: the same person signed in, or nobody then and nobody now."""
        data = verify(self.secret, self.purpose, token)
        if data is None:
            return None
        visitor_id = data.get("id")
        if not isinstance(visitor_id, str) or not visitor_id:
            return None
        return visitor_id if data.get("user") == self._mark(visitor_id, user) else None

    def of(self, conn: HTTPConnection, user: Any) -> str | None:
        """The id the browser behind a request or a socket brought, if it
        brought one that is this person's to use."""
        return self.read(conn.cookies.get(cookie_name(conn.scope, VISITOR_COOKIE)), user)

    def greet(self, request: Request, response: Response, user: Any) -> Response:
        """A page load, the login page included: a browser that brought no id
        of this person's leaves with a new one."""
        if self.of(request, user) is None:
            self._set(request, response, new_id(), user)
        return response

    def renew(self, request: Request, response: Response) -> None:
        """A sign-out: the browser has a new id, issued to nobody, before
        anything else is asked of the app."""
        self._set(request, response, new_id(), None)

    def _set(self, request: Request, response: Response, visitor_id: str, user: Any) -> None:
        response.set_cookie(
            cookie_name(request.scope, VISITOR_COOKIE),
            self.issue(visitor_id, user),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path=_cookie_path(request),
        )
        # The answer names one browser, so no cache may hand it to another.
        response.headers.setdefault("Cache-Control", "private")


__all__ = ["VISITOR_COOKIE", "Visitor", "Visitors", "new_id"]
