"""Does Fly replay a websocket upgrade to the machine it is told to?

Each machine answers ``/who`` with its own id. A socket opened at
``/ws?m=<id>`` on a machine that is not ``<id>`` is not upgraded: the
machine answers the upgrade with a plain response that carries
``fly-replay: instance=<id>``, and Fly's proxy is to try again there. The
machine that is meant upgrades and says who it is. ``/stats`` counts what
each machine did. The process ends by itself after ``DEADLINE`` seconds, so
a machine that was forgotten stops.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

ME = os.environ.get("FLY_MACHINE_ID", "local")
DEADLINE = float(os.environ.get("DEADLINE", "1500"))
counts = {"upgraded": 0, "sent on": 0, "replayed to me": 0}


async def who(request: Request) -> PlainTextResponse:
    return PlainTextResponse(ME)


async def stats(request: Request) -> JSONResponse:
    return JSONResponse({"machine": ME, **counts})


async def socket(ws: WebSocket) -> None:
    want = ws.query_params.get("m")
    if want and want != ME:
        counts["sent on"] += 1
        await ws.send_denial_response(
            Response(status_code=409, headers={"fly-replay": f"instance={want}"})
        )
        return
    await ws.accept()
    counts["upgraded"] += 1
    if "fly-replay-src" in ws.headers:
        counts["replayed to me"] += 1
    await ws.send_text(ME)
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await ws.send_text(f"{ME}: {await ws.receive_text()}")


@contextlib.asynccontextmanager
async def life(app: Starlette):  # type: ignore[no-untyped-def]
    async def end() -> None:
        await asyncio.sleep(DEADLINE)
        os._exit(0)

    task = asyncio.get_running_loop().create_task(end())
    yield
    task.cancel()


app = Starlette(
    routes=[Route("/who", who), Route("/stats", stats), WebSocketRoute("/ws", socket)],
    lifespan=life,
)
