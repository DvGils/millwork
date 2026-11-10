"""The turn: who may change what a session's page shows, one at a time.

Handlers take turns. A handler that waits on the user or on a task lends its
turn for the length of the wait and takes it again before it goes on, so
nobody ever runs a line of a handler without holding the turn.

The turn is a plain object changed by steps. Giving it back is safe from
anywhere: it does nothing for someone who does not hold it, which is what
lets the scope give it back for a child that was cancelled, wherever the
child was at the time.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any


class Turn:
    def __init__(self) -> None:
        self.holder: Any = None
        self._line: deque[tuple[Any, asyncio.Future[None]]] = deque()
        self.on_free: Callable[[], None] | None = None
        """Called when the turn comes free, before the next in line gets it."""

    @property
    def free(self) -> bool:
        return self.holder is None

    @property
    def waiting(self) -> int:
        return sum(1 for _, future in self._line if not future.done())

    def ask(self, who: Any) -> asyncio.Future[None]:
        """Get in line. The future is done once ``who`` holds the turn."""
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        if self.holder is None and not self.waiting:
            self.holder = who
            future.set_result(None)
        else:
            self._line.append((who, future))
        return future

    async def take(self, who: Any) -> None:
        """Wait in line for the turn. Whoever holds it already has it."""
        if self.holder is who:
            return
        if self.holder is None and not self.waiting:
            self.holder = who
            return
        await self.ask(who)

    def give_back(self, who: Any) -> None:
        """``who`` is done with the turn, or with waiting for it. Nothing
        happens for someone who neither holds it nor waits."""
        for entry in [e for e in self._line if e[0] is who]:
            self._line.remove(entry)
            entry[1].cancel()
        if self.holder is not who:
            return
        self.holder = None
        try:
            if self.on_free is not None:
                self.on_free()
        finally:
            self._pass_on()

    def _pass_on(self) -> None:
        while self._line and self.holder is None:
            next_one, future = self._line.popleft()
            if future.done():
                # Cancelled while it waited.
                continue
            self.holder = next_one
            future.set_result(None)

    @contextlib.asynccontextmanager
    async def lent(self, who: Any, over: Callable[[], bool]) -> AsyncIterator[None]:
        """Give the turn back for the length of a wait and take it again
        after, unless ``over()`` says there is nothing left to take turns on.
        Does nothing for someone who does not hold the turn, and for
        nobody (``None``)."""
        held = who is not None and self.holder is who
        if held:
            self.give_back(who)
        try:
            yield
        finally:
            if held and not over():
                await self._take_back(who, over)

    async def _take_back(self, who: Any, over: Callable[[], bool]) -> None:
        """Wait for the turn that was lent, come what may.

        A cancellation that arrives during this wait, a timeout the handler
        set around its question, is held until the turn is back and raised
        then: the handler's own ``except`` runs with the turn held. Only
        ``over()`` lets the wait go.
        """
        again = self.ask(who)
        interrupted: asyncio.CancelledError | None = None
        while not again.done():
            try:
                await asyncio.shield(again)
            except asyncio.CancelledError as exc:
                if over():
                    self.give_back(who)
                    raise
                interrupted = exc
        if interrupted is not None:
            raise interrupted
