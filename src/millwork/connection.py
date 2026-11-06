"""A connection: one socket, for as long as it lasts.

It reads the session's outbox from wherever its tab is and writes to the
socket, and it hands what the tab sends to the session's steps. A session
never holds a socket, so nothing but a connection's own writer ever waits on
one: a tab that reads slowly holds up itself and nobody else.

A connection has a scope of its own for its reader and its writer. Once it
is closed it carries nothing but a goodbye, which is one of the gates that
hold after a session has ended.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from millwork.files import Reject
from millwork.outbox import GAP, Outbox
from millwork.protocol import (
    Answer,
    Cancel,
    Command,
    Event,
    Navigate,
    Request,
    ServerError,
    pack,
    unpack_client,
    unpack_frame,
)
from millwork.scope import Scope

log = logging.getLogger("millwork.connection")

# How long a tab is given to take the word that its session ended.
END_NOTICE_SECONDS = 2.0
# File frames that may wait for the socket before the request sending them
# waits too, and upload frames that may wait for the disk before the socket
# is held back.
LANE_FRAMES = 4
PIPE_FRAMES = 16
# The socket was taken over by a newer one for the same session.
REPLACED = 4409


class Socket(Protocol):
    """What a connection needs of a websocket. Starlette's has it."""

    async def send_text(self, data: str) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def receive(self) -> MutableMapping[str, Any]: ...
    async def close(self, code: int = 1000) -> None: ...


class Listener(Protocol):
    """A session, as its connection sees it: an outbox to read, two things
    to say to a tab on the session's behalf, and the steps a tab can ask
    for."""

    id: str
    outbox: Outbox

    def hello(self) -> str: ...
    def mounted(self) -> str | None: ...
    def event(self, msg: Event) -> None: ...
    def answer(self, msg: Answer) -> None: ...
    def navigate(self, path: str) -> None: ...
    def request(self, conn: Connection, msg: Request, pipe: Pipe | None) -> None: ...
    def cancel(self, request: str) -> None: ...


@dataclass
class End:
    """Why a session ended, for its tab. ``to`` is where the tab should go.
    While that is still being asked, ``asking`` is a future that gets the
    answer and never raises, and ``to`` is what holds when it has none."""

    reason: str
    to: str | None = None
    asking: asyncio.Future[str | None] | None = None
    code: int = REPLACED


class Pipe:
    """The bytes of one upload on their way from the socket to the disk.

    Bounded, so a slow disk holds the socket back instead of a whole file
    sitting in memory. Failing it wakes both ends: a reader that waits to
    put, and the upload, which sees the failure.
    """

    def __init__(self, size: int) -> None:
        self.size = size
        self.received = 0
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=PIPE_FRAMES)
        self.failed: str | None = None
        if size == 0:
            self._queue.put_nowait(None)

    async def put(self, data: bytes) -> None:
        if self.failed is not None:
            return
        self.received += len(data)
        if self.received > self.size:
            self.fail("more bytes than announced")
            return
        await self._queue.put(data)
        if self.failed is not None:
            return
        if self.received == self.size:
            await self._queue.put(None)

    async def get(self) -> bytes | None:
        """The next chunk, or None at the end. Raises ``Reject`` once failed."""
        if self.failed is not None:
            raise Reject(f"the upload was interrupted: {self.failed}", key="file_interrupted")
        item = await self._queue.get()
        if self.failed is not None:
            raise Reject(f"the upload was interrupted: {self.failed}", key="file_interrupted")
        return item

    def fail(self, why: str) -> None:
        if self.failed is not None:
            return
        self.failed = why
        # What is queued is dropped. That wakes a putter waiting on a full
        # queue, and makes room for the end marker that wakes a getter.
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)


class Connection:
    def __init__(self, socket: Socket, name: str = "") -> None:
        self.socket = socket
        self.scope = Scope(f"connection {name}".strip())
        self.closed = False
        self.end: End | None = None
        self.code = 1000
        self.session: Listener | None = None
        self.cursor = -1
        """The last numbered message its tab has. Below zero: the tab has
        nothing that can be built on, and is sent the page as it stands."""
        # What goes to this tab alone and is never replayed: replies, and the
        # head and the bytes of a file, in the order they were given.
        self._lane: deque[str | bytes] = deque()
        self._pipes: dict[str, Pipe] = {}
        self._poke: asyncio.Future[None] | None = None
        self._room: asyncio.Future[None] | None = None
        self._stopped: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    # ------------------------------------------------------------- steps

    def bind(self, session: Listener, cursor: int) -> None:
        """The session this connection is for, and what its tab has seen."""
        self.session, self.cursor = session, cursor
        session.outbox.poke = self._wake

    def say(self, msg: Any) -> bool:
        """A message for this tab alone: a reply, the head of a file. It is
        small, so it is taken without waiting. Refused once closed."""
        if self.closed:
            return False
        self._lane.append(pack(0, msg))
        self._wake()
        return True

    def forget(self, request: str) -> None:
        """A request is done: the bytes still coming for it have nowhere to go."""
        pipe = self._pipes.pop(request, None)
        if pipe is not None:
            pipe.fail("done")

    def close(self, end: End | None = None, code: int = 1000) -> None:
        """From now on it carries nothing. What is left is to say goodbye,
        with ``end``, and to close the socket."""
        if self.closed:
            return
        self.closed = True
        self.end = end
        self.code = end.code if end is not None else code
        self._lane.clear()
        for pipe in self._pipes.values():
            pipe.fail("the connection closed")
        self._pipes.clear()
        session = self.session
        if session is not None and session.outbox.poke == self._wake:
            session.outbox.poke = None
        if self._room is not None and not self._room.done():
            self._room.set_result(None)
        self.scope.cancel()
        if not self._stopped.done():
            self._stopped.set_result(None)

    def _wake(self) -> None:
        if self._poke is not None and not self._poke.done():
            self._poke.set_result(None)

    def _part_done(self, task: asyncio.Task[Any] | None) -> None:
        # The tab went away or the socket failed. Either way it is over.
        self.close()

    # ---------------------------------------------------------- waiting

    async def frame(self, data: bytes) -> bool:
        """Bytes of a file for this tab. Waits while the tab is behind, which
        holds back the request that sends them and nothing else. False once
        the connection is closed."""
        while not self.closed and sum(1 for i in self._lane if isinstance(i, bytes)) >= LANE_FRAMES:
            self._room = asyncio.get_running_loop().create_future()
            await self._room
        if self.closed:
            return False
        self._lane.append(data)
        self._wake()
        return True

    async def run(self) -> None:
        """The connection's life: a reader and a writer until either stops or
        the connection is closed, and then the goodbye."""
        self.scope.start(self._read(), "reader", done=self._part_done)
        self.scope.start(self._write(), "writer", done=self._part_done)
        try:
            await self._stopped
        finally:
            self.close()
            await self.scope.wait(1.0)
        await self._goodbye()

    async def _goodbye(self) -> None:
        end = self.end
        if end is None:
            return
        to = end.to
        if end.asking is not None:
            to = (await end.asking) or end.to
        try:
            async with asyncio.timeout(END_NOTICE_SECONDS):
                if to is not None:
                    await self.socket.send_text(pack(0, Command(name="leave", args={"to": to})))
                await self.socket.send_text(pack(0, ServerError(message=end.reason, fatal=True)))
        except Exception:
            log.debug("a tab did not take the word that its session ended")

    async def _read(self) -> None:
        session = self.session
        assert session is not None
        while True:
            message = await self.socket.receive()
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            if text is None:
                data = message.get("bytes")
                if not data:
                    continue
                try:
                    request, chunk = unpack_frame(data)
                except ValueError:
                    log.warning("bad binary frame from session %s", session.id)
                    continue
                pipe = self._pipes.get(request)
                if pipe is None:
                    log.debug("frame for unknown request %s dropped", request)
                    continue
                # Put in line: a bounded pipe holds this loop back when the
                # disk is slower than the socket, which is the backpressure.
                await pipe.put(chunk)
                continue
            try:
                _, msg = unpack_client(text)
            except ValidationError:
                log.warning("bad message from session %s", session.id)
                continue
            if isinstance(msg, Event):
                session.event(msg)
            elif isinstance(msg, Answer):
                session.answer(msg)
            elif isinstance(msg, Navigate):
                session.navigate(msg.path)
            elif isinstance(msg, Request):
                pipe = None
                if msg.name == "upload" and msg.request not in self._pipes:
                    pipe = self._pipes[msg.request] = Pipe(msg.size or 0)
                session.request(self, msg, pipe)
            elif isinstance(msg, Cancel):
                session.cancel(msg.request)

    async def _write(self) -> None:
        try:
            await self._follow()
        except asyncio.CancelledError:
            raise
        except Exception:
            # The socket is dead. That ends the connection and nothing else.
            log.debug("a send failed; the connection is over")

    async def _follow(self) -> None:
        session, socket = self.session, self.socket
        assert session is not None
        outbox = session.outbox
        await socket.send_text(session.hello())
        while True:
            while self._lane:
                item = self._lane.popleft()
                if self._room is not None and not self._room.done():
                    self._room.set_result(None)
                if isinstance(item, bytes):
                    await socket.send_bytes(item)
                else:
                    await socket.send_text(item)
            items = GAP if self.cursor < 0 else outbox.after(self.cursor)
            if items is GAP:
                # The tab cannot be caught up from the outbox. It gets the
                # page as it was last drawn, which is what the next patch
                # builds on. No page function runs for it.
                self.cursor = outbox.seq
                mount = session.mounted()
                if mount is not None:
                    await socket.send_text(mount)
                continue
            if items:
                for seq, text in items:
                    await socket.send_text(text)
                    self.cursor = seq
                    if self._lane:
                        break
                continue
            self._poke = asyncio.get_running_loop().create_future()
            await self._poke
