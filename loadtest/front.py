"""A router in front of the replicas, standing in for a platform's proxy.

Without ``--cookie`` it keeps nothing: every new connection goes to a
replica picked at random, and to another when that one does not answer.

With ``--cookie`` it pins a browser to a replica the way a load balancer's
cookie affinity does. A request that brings the cookie goes to the replica
the cookie names. One that brings none, or names a replica that does not
answer, goes to one picked at random, and the answer sets the cookie.

    python front.py 9100 9101 9102 9103
    python front.py --cookie 9100 9101 9102 9103
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import re
import sys

COOKIE = "lb_replica"


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(ConnectionError, asyncio.CancelledError):
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    with contextlib.suppress(Exception):
        writer.close()


async def head(reader: asyncio.StreamReader) -> bytes:
    """What a peer sends up to the end of its headers."""
    try:
        return await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
        return getattr(exc, "partial", b"")


async def main(port: int, backends: list[int], cookie: bool) -> None:
    async def reach(order: list[int]) -> tuple[int, asyncio.StreamReader, asyncio.StreamWriter] | None:
        for backend in order:
            try:
                return backend, *await asyncio.open_connection("127.0.0.1", backend)
            except OSError:
                continue
        return None

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        order = random.sample(backends, len(backends))
        asked, named = b"", None
        if cookie:
            asked = await head(reader)
            found = re.search(rb"(?im)^cookie:.*?\b%s=(\d+)" % COOKIE.encode(), asked)
            named = int(found[1]) if found else None
            if named in backends:
                order = [named, *(b for b in order if b != named)]
        reached = await reach(order)
        if reached is None:
            writer.close()
            return
        backend, up_reader, up_writer = reached
        up_writer.write(asked)
        if cookie and backend != named:
            # The first answer on this connection tells the browser where it
            # is from now on.
            answer = await head(up_reader)
            line, _, rest = answer.partition(b"\r\n")
            pin = b"Set-Cookie: %s=%d; Path=/; HttpOnly" % (COOKIE.encode(), backend)
            writer.write(line + b"\r\n" + pin + b"\r\n" + rest)
        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))

    server = await asyncio.start_server(serve, "127.0.0.1", port, backlog=4096)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    args = sys.argv[1:]
    pins = "--cookie" in args
    ports = [int(a) for a in args if a != "--cookie"]
    asyncio.run(main(ports[0], ports[1:], pins))
