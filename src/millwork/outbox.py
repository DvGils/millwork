"""The outbox: what a session has to say to its tab, numbered and kept for
replay.

The session only appends to it, which never waits. A connection reads from
wherever its tab is and writes to the socket. Once sealed it takes nothing
more, which is one of the gates that hold after a session has ended.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

from millwork.protocol import pack

# The replay window: what a tab that drops and comes back is caught up with.
# Bounded in messages and in bytes, since one message can carry a whole chat.
# A tab that fell behind the window is mounted afresh instead.
OUTBOX_KEEP = 500
OUTBOX_KEEP_BYTES = 4 * 1024 * 1024

GAP: Any = object()
"""What ``after`` answers when a tab can no longer be caught up."""


class Outbox:
    def __init__(self, keep: int = OUTBOX_KEEP, keep_bytes: int = OUTBOX_KEEP_BYTES) -> None:
        self.keep, self.keep_bytes = keep, keep_bytes
        self.seq = 0
        self.sealed = False
        self.posted = 0
        """How many messages were ever taken, for the development warnings."""
        self._items: deque[tuple[int, str]] = deque()
        self._bytes = 0
        self.poke: Callable[[], None] | None = None
        """Called when there is something new: by the connection that follows."""

    def post(self, msg: Any) -> bool:
        """Number a message and keep it for whoever follows. False, and the
        message dropped, once the outbox is sealed."""
        if self.sealed:
            return False
        self.seq += 1
        self.posted += 1
        text = pack(self.seq, msg)
        self._items.append((self.seq, text))
        self._bytes += len(text)
        while len(self._items) > self.keep or (
            self._bytes > self.keep_bytes and len(self._items) > 1
        ):
            self._bytes -= len(self._items.popleft()[1])
        if self.poke is not None:
            self.poke()
        return True

    def seal(self) -> None:
        """Nothing more is taken, and what no socket has had yet is dropped."""
        self.sealed = True
        self._items.clear()
        self._bytes = 0
        if self.poke is not None:
            self.poke()

    def after(self, seq: int) -> Any:
        """What follows ``seq``, oldest first, or ``GAP`` when it can no
        longer be told: the tab is too far behind, or claims to be ahead."""
        if seq == self.seq:
            return []
        if seq > self.seq or not self._items or self._items[0][0] > seq + 1:
            return GAP
        # A tab is nearly always close behind, so look from the end.
        found = []
        for item in reversed(self._items):
            if item[0] <= seq:
                break
            found.append(item)
        found.reverse()
        return found
