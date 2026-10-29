"""The websocket endpoint: one socket per tab, speaking the protocol.

Nothing the tab sends may take the loop down: a bad frame is logged and
skipped, a handler's failure is the session's business, and only the
socket that currently owns the session detaches it.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from millwork.auth import Forbidden, NotFound
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
from millwork.session import Session

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

    user = await app.user_for(ws)
    session: Session[Any] | None = None
    if first.session and first.resume:
        candidate = app.sessions.get(first.session)
        if candidate is not None and candidate.owns_resume(first.resume) and not candidate.closed:
            same_user = (candidate.user is None and user is None) or (
                candidate.user is not None and user is not None and candidate.user.id == user.id
            )
            if same_user:
                session = candidate
            else:
                log.warning("resume refused: another user")

    if session is None:
        resolved = app.resolve(first.path)
        if resolved is None:
            await ws.send_text(pack(0, ServerError(message="no such page", fatal=True)))
            await ws.close(code=4404)
            return
        page, params = resolved
        if app.auth is not None and not page.public and user is None:
            await ws.send_text(pack(0, ServerError(message="Sign in to continue.", fatal=True)))
            await ws.close(code=4401)
            return
        session = Session(app, page, params, first.path)
        session.user = user
        app.sessions[session.id] = session
        try:
            await session.connect()
        except (Forbidden, NotFound) as exc:
            await ws.send_text(pack(0, ServerError(message=exc.message, fatal=True)))
            await session.close()
            await ws.close(code=4403 if isinstance(exc, Forbidden) else 4404)
            return
        except Exception:
            log.exception("connect failed for %s", first.path)
            await ws.send_text(
                pack(0, ServerError(message="The page failed to start.", fatal=True))
            )
            await session.close()
            await ws.close(code=4500)
            return

    send = ws.send_text

    async def close_this_socket() -> None:
        await ws.close(code=4409)

    try:
        await session.attach(send, first.seq, close=close_this_socket, send_bytes=ws.send_bytes)
    except Exception:
        log.exception("attach failed for session %s", session.id)
        await ws.send_text(pack(0, ServerError(message="The page failed to start.", fatal=True)))
        await ws.close(code=4500)
        session.detach(send)
        return

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
            # Each message is its own task: the receive loop never waits on a handler,
            # so an answer to an open ask (or a click during a long handler) still arrives.
            # The session's lock keeps handlers one at a time, in order.
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
