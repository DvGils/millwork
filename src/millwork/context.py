"""The current session, reachable from anywhere on the loop or in a task thread.

Handlers receive the session explicitly. Code deeper down (a progress report
from inside a workflow, a library that wants to toast) uses ``session()``.
The variable is set per handler and per task; ``asyncio.to_thread`` copies
the context, so it is visible from a sync task's thread too.
"""

from __future__ import annotations

from contextvars import Context, ContextVar, copy_context
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


# The visit of a page that the running work began on: a handler's, and that
# of the tasks it started. None for work that belongs to no one visit, and
# for a handler that has asked for another page itself.
_visit: ContextVar[int | None] = ContextVar("millwork_visit", default=None)


def visit() -> int | None:
    return _visit.get()


def on_visit(number: int | None) -> object:
    """Say which visit the work that runs from here on began on; returns
    the token for ``off_visit``."""
    return _visit.set(number)


def off_visit(token: object) -> None:
    _visit.reset(token)  # type: ignore[arg-type]


# The variables that say whose the running work is: a session's, a visit's,
# a task's.
_whose: list[ContextVar[Any]] = [_session, _auth, _visit]


def says_whose[V: ContextVar[Any]](var: V) -> V:
    """Count a variable among the ones that say whose the running work is.
    It has a default, which is what it says of work that is nobody's."""
    _whose.append(var)
    return var


def of_nobody() -> Context:
    """The current context for work that is nobody's: a copy in which no
    session, visit or task is the current one. Work started in a handler
    for the app would otherwise run as that handler's session for as long
    as it runs, and keep the session from being let go when it has ended."""
    apart = copy_context()
    for var in _whose:
        apart.run(var.set, Context().run(var.get))
    return apart


def bind(s: Session[Any] | None) -> object:
    """Set the current session; returns the token for ``unbind``."""
    return _session.set(s)


def unbind(token: object) -> None:
    _session.reset(token)  # type: ignore[arg-type]
