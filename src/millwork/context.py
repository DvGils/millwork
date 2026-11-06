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


# The Auth whose login page is being laid out. That page is built before any
# session exists, so what it needs of the app's sign-in comes through here.
_auth: ContextVar[Any] = ContextVar("millwork_auth", default=None)


def auth() -> Any:
    """The app's ``Auth`` as a component being built can see it: the current
    session's, or the one laying out its login page. ``None`` without either."""
    laying_out = _auth.get()
    if laying_out is not None:
        return laying_out
    s = _session.get()
    return s.app.auth if s is not None else None


def bind(s: Session[Any] | None) -> object:
    """Set the current session; returns the token for ``unbind``."""
    return _session.set(s)


def unbind(token: object) -> None:
    _session.reset(token)  # type: ignore[arg-type]
