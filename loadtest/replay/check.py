"""Open sockets at the app on Fly, each naming the machine it wants, and
count where they end up.

    python check.py <app> [sockets per machine]
"""

from __future__ import annotations

import asyncio
import collections
import json
import sys
import time
import urllib.request

import websockets

APP = sys.argv[1]
EACH = int(sys.argv[2]) if len(sys.argv) > 2 else 40
HOST = f"{APP}.fly.dev"


def get(path: str, machine: str | None = None) -> str:
    request = urllib.request.Request(f"https://{HOST}{path}")
    if machine:
        request.add_header("fly-force-instance-id", machine)
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode()


async def one(want: str | None) -> tuple[str, float]:
    """Where a socket that asks for ``want`` ends up, and how long the
    handshake and the first message took."""
    url = f"wss://{HOST}/ws" + (f"?m={want}" if want else "")
    began = time.monotonic()
    try:
        async with websockets.connect(url, open_timeout=15, close_timeout=1) as ws:
            got = await asyncio.wait_for(ws.recv(), 10)
            await ws.send("hello")
            echoed = await asyncio.wait_for(ws.recv(), 10)
            assert echoed == f"{got}: hello", echoed
            return str(got), time.monotonic() - began
    except websockets.InvalidStatus as exc:
        headers = dict(exc.response.headers)
        return f"refused {exc.response.status_code} {headers.get('fly-replay', '')}".strip(), 0.0
    except Exception as exc:
        return f"failed {type(exc).__name__}: {exc}"[:80], 0.0


async def many(want: str | None, count: int) -> tuple[collections.Counter[str], list[float]]:
    found = await asyncio.gather(*(one(want) for _ in range(count)))
    took = sorted(t for _, t in found if t)
    return collections.Counter(where for where, _ in found), took


def middle(took: list[float]) -> str:
    return f"{took[len(took) // 2] * 1e3:.0f} ms" if took else "no time"


async def main() -> None:
    machines = sorted({get("/who") for _ in range(30)})
    print(f"machines that answer: {machines}")
    plain, took = await many(None, EACH)
    print(f"{EACH} sockets that name no machine end on: {dict(plain)} (median {middle(took)})")
    for machine in machines:
        ended, took = await many(machine, EACH)
        print(f"{EACH} sockets that name {machine} end on: {dict(ended)} (median {middle(took)})")
    ended, _ = await many("0000000000000000", 5)
    print(f"5 sockets that name a machine that does not exist: {dict(ended)}")
    for machine in machines:
        print("  ", json.loads(get("/stats", machine)))


if __name__ == "__main__":
    asyncio.run(main())
