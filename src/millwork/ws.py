"""The websocket endpoint: one socket per tab, speaking the protocol.

It finds the session a tab is asking for, or admits a new one, and then is
the life of one connection to it. Nothing the tab sends may take the loop
down: a bad frame is logged and skipped, a handler's failure is the
session's business, and only the connection a session currently has
detaches it.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from millwork.connection import Connection
from millwork.protocol import (
    PROTOCOL_VERSION,
    Command,
    Hello,
    ServerError,
    pack,
    unpack_client,
)
from millwork.session import Session
from millwork.shell import root_of
from millwork.visitors import Visitor

log = logging.getLogger("millwork.ws")


def origin_allowed(ws: WebSocket, origins: list[str]) -> bool:
    """Same origin by default; an explicit allow-list otherwise.

    A browser always sends ``Origin`` on a websocket. A client without one
    (a test, curl) is not a browser and has no cross-site protection to
    bypass, so it is allowed.
    """
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    if origins:
        return origin in origins
    host = ws.headers.get("host")
    return host is not None and urlsplit(origin).netloc.lower() == host.lower()


async def websocket_endpoint(ws: WebSocket) -> None:
    app = ws.app.state.millwork
    if not origin_allowed(ws, app.origins):
        await ws.close(code=4403)
        return
    await ws.accept()

    async def refuse(key: str, code: int, **vars: Any) -> None:
        await ws.send_text(pack(0, ServerError(message=app.theme.text(key, **vars), fatal=True)))
        await ws.close(code=code)

    try:
        _, first = unpack_client(await ws.receive_text())
    except (ValidationError, WebSocketDisconnect, KeyError):
        await ws.close(code=4400)
        return
    if not isinstance(first, Hello):
        await ws.send_text(pack(0, ServerError(message="expected hello", fatal=True)))
        await ws.close(code=4400)
        return
    serving = app.shell.build
    if first.protocol != PROTOCOL_VERSION or (
        first.bundle is not None and serving is not None and first.bundle != serving
    ):
        # The tab runs a bundle this server does not serve: it outlived a
        # deploy, or its page came out of a cache. It would draw the page
        # with components and files it may not have, so it loads the page
        # again and gets the bundle there is. It is told which one that is,
        # and loads the page once for it. While there is no bundle to serve,
        # as in the middle of a build, a tab is left with the one it has.
        await ws.send_text(pack(0, Command(name="reload", args={"bundle": serving})))
        await ws.close(code=4426)
        return

    try:
        user = await app.user_for(ws)
    except Exception:
        # Said once per attempt; the tab is told to stop, so a broken hook does
        # not turn every open tab into a reconnect loop.
        log.exception("identity lookup failed")
        await refuse("something_went_wrong", 4500)
        return
    session: Session[Any] | None = None
    seen = 0
    if first.session and first.resume:
        candidate = app.sessions.get(first.session)
        if candidate is not None and candidate.owns_resume(first.resume) and not candidate.over:
            same_person = (candidate.user is None and user is None) or (
                candidate.user is not None and user is not None and candidate.user.id == user.id
            )
            if not same_person:
                log.warning("resume refused: another user")
            elif candidate.user != user or not app.may(user, candidate.page, candidate.params).ok:
                # The same person, changed since the session began, in role or
                # in anything. What the session holds was gathered for who they
                # were, so it ends with it, and the tab gets a new one.
                # A tab still on it, a duplicate of this one, is sent to load
                # its page again rather than left with clicks that go nowhere.
                candidate.dismiss(
                    app.theme.text("sign_in_hint"),
                    to=candidate.leaving_for(candidate.path.split("#", 1)[0]),
                )
            else:
                session, seen = candidate, first.seq

    if session is None:
        page, params = app.locate(first.path) or app.fallback("not_found", first.path)
        if app.auth is not None and not page.public and user is None:
            await refuse("sign_in_hint", 4401)
            return
        session = Session(app, page, params, first.path)
        session.user = user
        if app.visitors is not None:
            # The browser's id when it brought one. Without it the session
            # keeps the id it was made with, which no other session has.
            known = app.visitors.of(ws, user)
            if known is not None:
                session.visitor = Visitor(known)
        session.base = root_of(ws.scope)
        session.client = (
            f"user:{user.id}"
            if user is not None
            else f"addr:{ws.client.host if ws.client else '?'}"
        )
        if (
            user is None
            and ws.scope.get("millwork.proxied")
            and "x-forwarded-for" not in ws.headers
            and not app._warned_no_address
        ):
            # Every anonymous visitor then shares the proxy's address and one cap.
            app._warned_no_address = True
            log.warning(
                "the proxy sends no X-Forwarded-For, so every anonymous visitor "
                "counts as one client for the session cap"
            )
        if app.stopping:
            # The server is going down. The tab tries again, and finds the
            # one that comes up.
            await ws.close(code=1012)
            return
        # Admitted, its life begins: the page's connect hook runs as the
        # session's own, and the tab hears of the page when it is there.
        if not app.admit(session):
            log.warning("session refused for %s: too many sessions", session.client)
            await refuse("too_many_sessions", 4429)
            return

    conn = Connection(ws, session.id[:6])
    try:
        session.attached(conn, seen)
        # A new session and a resumed one alike: the tab may come back on a
        # newer sign-in than the one the session was opened on.
        session.watch_sign_in(ws.scope.get("millwork.sign_in"))
        session.watch_user(ws.scope.get("millwork.identified"))
        # The person's standing may have changed since the session was last
        # used. A sign-in that ended meanwhile takes this session with it
        # here, and its tab is told on this connection.
        await session.stay_current()
        await conn.run()
    finally:
        session.detached(conn)
        conn.close()
        with contextlib.suppress(Exception):
            # A tab that is not reading keeps the close from going out until
            # it reads again or the server's own keepalive drops the socket.
            # Nothing of the session waits for that.
            await ws.close(code=conn.code)
