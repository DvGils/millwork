"""A scope: the owner of everything that waits on someone's behalf.

A session has one, the app has two, a connection has one. Tasks and timers
are started through a scope and end with it, so nothing outlives what it
was started for.

What must happen when a child is gone is done by the scope, in ``done``. A
child that is cancelled before it has run a line never reaches a ``finally``
of its own, so a child cannot be trusted to give back what the step that
started it handed out: a turn, a place among the requests, a chat that is
busy. The scope can.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

log = logging.getLogger("millwork.scope")


class Timer:
    """A step that is due later. Cancelled by whoever set it, or dropped by
    the scope when the scope is cancelled first."""

    __slots__ = ("_dropped", "_handle", "_scope")

    def __init__(self, scope: Scope, dropped: Callable[[], None] | None) -> None:
        self._scope = scope
        self._dropped = dropped
        self._handle: asyncio.TimerHandle | None = None

    @property
    def pending(self) -> bool:
        return self._handle is not None

    def cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None
            self._scope._timers.discard(self)


class Scope:
    def __init__(self, name: str) -> None:
        self.name = name
        self.cancelled = False
        self._children: set[asyncio.Task[Any]] = set()
        self._timers: set[Timer] = set()

    @property
    def children(self) -> list[asyncio.Task[Any]]:
        return list(self._children)

    def owns(self, task: asyncio.Task[Any] | None) -> bool:
        return task in self._children

    def start(
        self,
        coro: Coroutine[Any, Any, Any],
        name: str,
        done: Callable[[asyncio.Task[Any] | None], None] | None = None,
    ) -> asyncio.Task[Any] | None:
        """Run ``coro`` as a child of this scope.

        ``done`` is called once when the child is finished, cancelled, or was
        never started because the scope was cancelled already. It gets the
        task, or None for one that never started. It is a plain function and
        is where whatever the child was handed is given back.
        """
        if self.cancelled:
            coro.close()
            if done is not None:
                done(None)
            return None
        task = asyncio.get_running_loop().create_task(coro, name=f"{self.name}: {name}")
        self._children.add(task)

        def finished(t: asyncio.Task[Any]) -> None:
            self._children.discard(t)
            if not t.cancelled() and t.exception() is not None:
                # A child reports its own failures. One that gets out is ours.
                log.error("%s failed", t.get_name(), exc_info=t.exception())
            if done is not None:
                done(t)

        task.add_done_callback(finished)
        return task

    def later(
        self,
        delay: float,
        step: Callable[..., None],
        *args: Any,
        dropped: Callable[[], None] | None = None,
    ) -> Timer | None:
        """Call ``step`` after ``delay`` seconds. ``dropped`` is called in its
        place when the scope is cancelled before then."""
        if self.cancelled:
            if dropped is not None:
                dropped()
            return None
        timer = Timer(self, dropped)

        def fire() -> None:
            timer._handle = None
            self._timers.discard(timer)
            step(*args)

        timer._handle = asyncio.get_running_loop().call_later(delay, fire)
        self._timers.add(timer)
        return timer

    def cancel(self) -> None:
        """From now on the scope starts nothing, and every child and timer it
        has is cancelled. It does not wait: ``wait`` does."""
        if self.cancelled:
            return
        self.cancelled = True
        for timer in list(self._timers):
            dropped = timer._dropped
            timer.cancel()
            if dropped is not None:
                dropped()
        for child in list(self._children):
            child.cancel()

    async def wait(self, patience: float | None = None) -> list[str]:
        """Until every child is done. Children still running after
        ``patience`` seconds are named in the log, returned, and left."""
        if not self._children:
            return []
        _, pending = await asyncio.wait(set(self._children), timeout=patience)
        names = sorted(t.get_name() for t in pending)
        if names:
            log.error(
                "%s: still running after %g s: %s", self.name, patience or 0.0, ", ".join(names)
            )
        return names
