"""A way for an app to say "this changed" to every session that shows it.

What several sessions see together is kept outside them, in an object of
the app's or in a database, and each page function reads it there. A
``Signal`` stands next to that data. A session follows it while it is on a
page that shows the data, and the code that changes the data fires it. Each
follower's page is then drawn again, from the data as it is.

A signal carries nothing and keeps nothing. It reaches the sessions of its
own process. An app with several processes has a place where its data
lives, listens there in each of them, and fires the signal for the
sessions of that process.
"""

from __future__ import annotations

import threading
import weakref
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from millwork.session import Session

__all__ = ["Signal"]


class Signal:
    """Fired when something changed, and followed by the sessions that show
    it. Made by the app, as many as it has things that change."""

    def __init__(self) -> None:
        # Held weakly: a session takes itself out where it leaves a page and
        # where it ends, and this is for one that could not.
        self._followers: weakref.WeakSet[Session[Any]] = weakref.WeakSet()
        # A signal is fired and followed from handlers and from threads.
        self._lock = threading.Lock()

    def fire(self) -> None:
        """Ask every session that follows this for a drawing. From a
        handler, a task or a thread. The drawings go through the time that
        makes changes close together one patch, so firing often costs each
        follower one drawing."""
        with self._lock:
            followers = list(self._followers)
        for session in followers:
            session._nudge()

    def _add(self, session: Session[Any]) -> None:
        with self._lock:
            self._followers.add(session)

    def _drop(self, session: Session[Any]) -> None:
        with self._lock:
            self._followers.discard(session)
