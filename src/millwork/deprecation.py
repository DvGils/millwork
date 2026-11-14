"""How a spelling is retired: it keeps working for one minor release and says
so, then it is gone.

A ``Deprecation`` is declared once, at module level, and warns where the old
spelling is used. It says so twice, for two readers. Python's own warning is
for tools: pytest lists it, and a filter turns it into an error. A log line
is for whoever runs the app, once for each place, when the program asked for
that with ``show()``. Both name the line of the app that used the spelling.

Every declaration names the release that started warning and the release
that drops the spelling, and a test holds them to it: once the version
reaches the second, the old spelling has to be gone from the code.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import re
import sys
import types
import warnings
from collections.abc import Callable
from types import FrameType
from typing import Any

import pydantic

__all__ = [
    "DECLARED",
    "Deprecation",
    "MillworkDeprecationWarning",
    "Renamed",
    "adopt_old_names",
    "move_old_names",
    "overdue",
    "show",
]

log = logging.getLogger("millwork.deprecation")


class MillworkDeprecationWarning(DeprecationWarning):
    """A spelling that still works and stops working in a later release."""


# Frames in these folders are not the app's: the warning names the first
# frame outside them. Pydantic is here because a model's validators run
# under its ``__init__``.
_NOT_THE_APP = tuple(
    os.path.normcase(os.path.dirname(os.path.abspath(file)) + os.sep)
    for file in (__file__, pydantic.__file__)
)
_MINOR = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)")

DECLARED: list[Deprecation] = []
# Whether deprecations are logged as well, and the places already logged.
# The set is for a reader, so it stops taking places long before it could
# weigh anything, in an app that makes its messages or its classes as it runs.
_shown = False
_logged: set[tuple[str, int, str]] = set()
_PLACES = 1000


def show() -> None:
    """Log each deprecation, once for each place that causes it. For a
    program's entry point. Python hides a deprecation in code that is not
    the main script, and an app that is served never is."""
    global _shown
    _shown = True


def _minor(version: str) -> tuple[int, int]:
    """The minor release a version belongs to: 1.2 for 1.2.3 and for 1.2.0rc1."""
    found = _MINOR.match(version)
    if found is None:
        raise ValueError(f"{version!r} is not a version")
    return int(found[1]), int(found[2])


def overdue(version: str) -> list[Deprecation]:
    """What should be gone from the code in this version and is still declared."""
    return [d for d in DECLARED if _minor(d.removed) <= _minor(version)]


def _the_apps_frame() -> FrameType:
    """The nearest frame that is not millwork's, pydantic's or the import
    system's. When the app is not on the stack at all, the outermost frame."""
    frame = sys._getframe(1)
    while True:
        file = os.path.normcase(frame.f_code.co_filename)
        if not file.startswith(_NOT_THE_APP) and not ("importlib" in file and "_bootstrap" in file):
            return frame
        if frame.f_back is None:
            return frame
        frame = frame.f_back


def _code_of(about: Any) -> tuple[types.CodeType, dict[str, Any]] | None:
    """The code and the globals of a function, of what a partial or a bound
    method wraps, or of an instance's ``__call__``. None for the rest."""
    for _ in range(8):
        if isinstance(about, functools.partial):
            about = about.func
        elif inspect.ismethod(about):
            about = about.__func__
        elif hasattr(about, "__wrapped__"):
            about = about.__wrapped__
        elif inspect.isfunction(about) or inspect.isclass(about) or not callable(about):
            break
        else:
            about = type(about).__call__
            if not inspect.isfunction(about):
                break
    return (about.__code__, about.__globals__) if inspect.isfunction(about) else None


def _say(message: str, at: Any = None) -> None:
    """Log the message when the program asked for that, and raise Python's
    warning, both naming one place. The log line comes first: a filter may
    turn the warning into an error."""
    about = _code_of(at) if at is not None else None
    if about is None:
        frame = _the_apps_frame()
        file, line, scope = frame.f_code.co_filename, frame.f_lineno, frame.f_globals
    else:
        code, scope = about
        file, line = code.co_filename, code.co_firstlineno
    place = (file, line, message)
    if _shown and place not in _logged and len(_logged) < _PLACES:
        _logged.add(place)
        log.warning("%s:%d: %s", file, line, message)
    warnings.warn_explicit(
        message,
        MillworkDeprecationWarning,
        file,
        line,
        # Code run by ``exec`` may have no name, and a warning without a
        # module is dropped.
        module=scope.get("__name__") or "<string>",
        registry=scope.setdefault("__warningregistry__", {}),
        module_globals=scope,
    )


class Deprecation:
    """One retired spelling. ``what`` is the spelling as an app writes it,
    ``since`` the minor release that started warning, ``removed`` the one
    that drops it, and ``instead`` what to write now."""

    def __init__(self, what: str, *, since: str, removed: str, instead: str | None = None) -> None:
        for version in (since, removed):
            if not _MINOR.fullmatch(version):
                raise ValueError(f"{version!r} is not a minor release, such as 1.2")
        if _minor(removed) <= _minor(since):
            raise ValueError(f"{what} would be removed in {removed}, no later than {since}")
        self.what = what
        self.since = since
        self.removed = removed
        self.instead = instead
        DECLARED.append(self)

    def message(self, what: str | None = None) -> str:
        text = (
            f"{what or self.what} is deprecated since millwork {self.since}"
            f" and stops working in {self.removed}."
        )
        return f"{text} Use {self.instead} instead." if self.instead else text

    def warn(self, what: str | None = None, *, at: Callable[..., Any] | None = None) -> None:
        """Say that the old spelling was used. The place is the line of the
        app that is running. What is noticed while no code of the app runs,
        at a render or when an event is dispatched, passes what it is about
        as ``at``, a handler for one, and the place is where that is
        defined."""
        _say(self.message(what), at)


class Renamed(Deprecation):
    """A component's keyword that goes by a new name. The component lists it
    in ``old_names`` under the old name, and a call that still uses that
    name works and warns. That is the keyword in a call and nothing else:
    not the attribute on an instance, and not a field of that name that a
    subclass declares, which is told so when the class is made."""

    def __init__(self, new: str, *, since: str, removed: str) -> None:
        super().__init__(f"the old name of {new}=", since=since, removed=removed)
        self.new = new
        self.instead = f"{new}="


Renames = dict[str, tuple[str, Renamed]]


def old_names_of(cls: type) -> dict[str, Renamed]:
    """The old names of a class and of its bases, the class's own winning."""
    found: dict[str, Renamed] = {}
    for klass in reversed(cls.__mro__):
        found.update(vars(klass).get("old_names", {}))
    return found


def move_old_names(cls: type, renames: Renames, props: dict[str, Any]) -> None:
    """Move what a call passed under an old name to the name it has now, in
    place, and warn. Both names in one call is a mistake: they are one
    keyword."""
    for old in renames.keys() & props.keys():
        new, rule = renames[old]
        if new in props:
            raise TypeError(
                f"{cls.__name__} got {old}= and {new}=, which are one keyword:"
                f" {old}= is its old name"
            )
        rule.warn(f"{cls.__name__}({old}=)")
        props[new] = props.pop(old)


def adopt_old_names(cls: Any) -> None:
    """Work out what a class's old names mean for it. Called when the class
    is made, for every component class.

    A call's old names are moved to the names they have now at two doors.
    The base ``__init__`` every component ends in moves what reaches it,
    going by ``cls.renames``, which is set here. An ``__init__`` of the
    class's own that names the new keyword as a parameter was written to the
    new spelling and could not receive the old one, so it is wrapped to move
    that keyword first. An ``__init__`` written to the old spelling, as an
    app's subclass from before the rename is, is left alone and keeps
    working: what it passes on is moved further down."""
    own = vars(cls).get("old_names", {})
    for old, rule in own.items():
        rule.what = f"{cls.__name__}({old}=)"
    names = old_names_of(cls)
    if not names:
        return
    renames: Renames = {}
    for old, rule in names.items():
        new, seen = rule.new, {old}
        while new in names:
            if new in seen:
                raise TypeError(f"{cls.__name__}.old_names goes in a circle at {new!r}")
            seen.add(new)
            new = names[new].new
        if new not in cls.model_fields:
            raise TypeError(f"{cls.__name__}.old_names: {old!r} is now {new!r}, which is no field")
        renames[old] = (new, rule)
    cls.renames = renames

    for old in renames.keys() & cls.model_fields.keys():
        if any(old in getattr(base, "model_fields", {}) for base in cls.__mro__[1:]):
            continue  # said where the field was declared
        new, rule = renames[old]
        _say(
            f"{cls.__name__} declares a field {old}, which is {new} since millwork"
            f" {rule.since}. The two are separate fields now. Declare {new} instead."
        )

    if "__init__" not in vars(cls):
        return
    init = vars(cls)["__init__"]
    try:
        named = {
            name
            for name, p in inspect.signature(init).parameters.items()
            if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        }
    except (TypeError, ValueError):
        return
    mine = {old: to for old, to in renames.items() if to[0] in named and old not in named}
    if not mine:
        return

    @functools.wraps(init)
    def __init__(self: Any, *children: Any, **props: Any) -> None:
        move_old_names(type(self), mine, props)
        init(self, *children, **props)

    cls.__init__ = __init__
