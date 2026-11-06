"""The websocket endpoint: one socket per tab, speaking the protocol.

Nothing the tab sends may take the loop down: a bad frame is logged and
skipped, a handler's failure is the session's business, and only the
socket that currently owns the session detaches it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from millwork.protocol import (
    PROTOCOL_VERSION,
    Answer,
    Cancel,
    Command,
    Event,
    Hello,
    Navigate,
    Request,
    ServerError,
    pack,
    unpack_client,
    unpack_frame,
)
from millwork.session import END_NOTICE_SECONDS, MAX_INFLIGHT, Session
from millwork.shell import root_of

log = logging.getLogger("millwork.ws")


async def _say_it_ended(ws: WebSocket, session: Session[Any], app: Any) -> None:
    """Tell a tab that its session is over, where to go if it was sent
    somewhere, and close the socket, within a moment."""
    with contextlib.suppress(Exception):
        async with asyncio.timeout(END_NOTICE_SECONDS):
            if session.end_to is not None:
                gone = Command(name="leave", args={"to": session.end_to})
                await ws.send_text(pack(0, gone))
            why = session.end_reason or app.theme.text("session_ended")
            await ws.send_text(pack(0, ServerError(message=why, fatal=True)))
            await ws.close(code=4409)


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
    if first.protocol != PROTOCOL_VERSION:
        await ws.send_text(pack(0, Command(name="reload")))
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
    if first.session and first.resume:
        candidate = app.sessions.get(first.session)
        if candidate is not None and candidate.owns_resume(first.resume) and not candidate.closed:
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
                await candidate.leave(candidate.path.split("#", 1)[0])
            else:
                session = candidate

    if session is None:
        page, params = app.locate(first.path) or app.fallback("not_found", first.path)
        if app.auth is not None and not page.public and user is None:
            await refuse("sign_in_hint", 4401)
            return
        session = Session(app, page, params, first.path)
        session.user = user
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
        session.connecting = True
        if not await app.admit(session):
            log.warning("session refused for %s: too many sessions", session.client)
            await refuse("too_many_sessions", 4429)
            return
        try:
            await session.connect_or_fall_back()
        except Exception:
            log.exception("connect failed for %s", first.path)
            await ws.send_text(
                pack(0, ServerError(message=app.theme.text("page_failed"), fatal=True))
            )
            await session._close()
            await ws.close(code=4500)
            return

    # A new session and a resumed one alike: the tab may come back on a newer
    # sign-in than the one the session was opened on.
    session.watch_sign_in(ws.scope.get("millwork.sign_in"))
    session.watch_user(ws.scope.get("millwork.identified"))
    # Connecting took time, and the person's standing may have changed in it:
    # a sign-in that ended meanwhile takes this session with it here, before
    # anything of the page is sent.
    await session.stay_current()
    send = ws.send_text

    async def close_this_socket() -> None:
        await ws.close(code=4409)

    try:
        await session.attach(send, first.seq, close=close_this_socket, send_bytes=ws.send_bytes)
    except Exception:
        log.exception("attach failed for session %s", session.id)
        await ws.send_text(pack(0, ServerError(message=app.theme.text("page_failed"), fatal=True)))
        await ws.close(code=4500)
        session.detach(send)
        return
    finally:
        session.connecting = False
    if session.closed:
        # Ended while it was being connected (signed out elsewhere), so the
        # socket was never attached and nothing could reach the tab.
        if session._finishing is not None and session._send is not send:
            await _say_it_ended(ws, session, app)
            return
        # Over, and not yet told anything: where its tab is to go is still
        # being asked. It is given the socket to hear it on, and waits below.
        session._send, session._close_socket = send, close_this_socket

    overflowed = False
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            text = message.get("text")
            if text is None:
                data = message.get("bytes")
                if not data:
                    continue
                try:
                    request_id, chunk = unpack_frame(data)
                except ValueError:
                    log.warning("bad binary frame from session %s", session.id)
                    continue
                # Fed inline: a bounded stream holds this loop back when the disk is
                # slower than the socket, which is the backpressure.
                await session.feed(request_id, chunk)
                continue
            try:
                _, msg = unpack_client(text)
            except ValidationError:
                log.warning("bad message from session %s", session.id)
                continue
            if session.closed:
                if session._finishing is None:
                    # Over, and the word for its tab is still being worked
                    # out: where a sign-in's tabs go is being asked. What the
                    # tab sends meanwhile is dropped, and it hears on this
                    # socket as soon as there is something to say.
                    continue
                # The session ended and its tab may not have heard: it was not
                # reading then. It is told now that it speaks, and let go.
                await _say_it_ended(ws, session, app)
                break
            # Each message is its own task: the receive loop never waits on a handler,
            # so an answer to an open ask (or a click during a long handler) still arrives.
            # The session's lock keeps handlers one at a time, in order.
            # An answer to an open ask resolves a waiting handler and starts no new
            # work, so it passes the bound: the backlog cannot clear without it.
            if (
                isinstance(msg, Event | Answer | Navigate)
                and session.inflight >= MAX_INFLIGHT
                and not (isinstance(msg, Event) and "/@ask:" in msg.node)
            ):
                if not overflowed:
                    overflowed = True
                    log.warning(
                        "session %s: %d messages pending, dropping", session.id, MAX_INFLIGHT
                    )
                    await session._send_now(
                        ServerError(message=app.theme.text("too_many_actions"), fatal=False)
                    )
                continue
            overflowed = False
            if isinstance(msg, Event):
                session.spawn(session.dispatch(msg), f"event {msg.name} on {msg.node}")
            elif isinstance(msg, Answer):
                session.spawn(session.answer(msg), "answer")
            elif isinstance(msg, Navigate):
                session.spawn(session.navigate_to(msg.path), f"navigate {msg.path}")
            elif isinstance(msg, Request):
                session.start_request(msg)
            elif isinstance(msg, Cancel):
                session.cancel_request(msg.request)
    except WebSocketDisconnect:
        pass
    finally:
        session.detach(send)
