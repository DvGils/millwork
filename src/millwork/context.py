"""The current session, reachable from anywhere on the loop or in a task thread.

Handlers receive the session explicitly. Code deeper down (a progress report
from inside a workflow, a library that wants to toast) uses ``session()``.
The variable is set per handler and per task; ``asyncio.to_thread`` copies
the context, so it is visible from a sync task's thread too.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from millwork.session import Session

_session: ContextVar[Session[Any] | None] = ContextVar("millwork_session", default=None)


class NoSession(RuntimeError):
    pass


def session() -> Session[Any]:
    """The session the current handler or task belongs to."""
    s = _session.get()
    if s is None:
        raise NoSession("no millwork session in this context")
    return s


def current() -> Session[Any] | None:
    return _session.get()


def bind(s: Session[Any] | None) -> object:
    """Set the current session; returns the token for ``unbind``."""
    return _session.set(s)


def unbind(token: object) -> None:
    _session.reset(token)  # type: ignore[arg-type]
