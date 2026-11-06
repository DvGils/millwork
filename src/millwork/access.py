"""Who may open what: the rule an app gives a page or a route, and the one
place it is asked.

A rule is a plain function of the signed-in user, and of the path's
parameters when it names them: ``def is_admin(user)``, ``def member(user,
project_id)``. It returns True or False and reads nothing but what it is
handed, so the same question has the same answer wherever it is asked: on a
page load, when a socket connects, on navigation, for a route, for a link.
What the user is at this moment is the business of ``Auth(recheck=)``.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("millwork.access")


class Forbidden(Exception):
    """Raised from ``connect``, or from a rule, when the user may not open
    this page.

    The session lands on the app's forbidden page, which shows ``message``
    when one is given and the theme's standard text otherwise.
    """

    def __init__(self, message: str | None = None) -> None:
        self.message = message
        super().__init__(message or "")


@dataclass(frozen=True)
class Verdict:
    """The answer to "may this user open this", with the words a rule gave
    for a refusal."""

    ok: bool
    message: str | None = None


ALLOWED = Verdict(True)
REFUSED = Verdict(False)


@dataclass(frozen=True)
class Rule:
    """A rule as the app wrote it, and the path parameters it asks for."""

    fn: Callable[..., Any]
    wants: tuple[str, ...]
    takes_all: bool

    @property
    def name(self) -> str:
        return getattr(self.fn, "__qualname__", None) or repr(self.fn)


def rule_for(fn: Any, params: Iterable[str], where: str) -> Rule:
    """Check a rule when the page or route is declared, so one that could
    never be asked fails at start and not on the first visit."""
    if not callable(fn):
        raise TypeError(f"allow= of {where} takes a function of the user, not {fn!r}")
    call = fn if inspect.isfunction(fn) or inspect.ismethod(fn) else getattr(fn, "__call__", fn)  # noqa: B004
    if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(call):
        raise TypeError(
            f"the rule of {where} is async. A rule is a plain function of the user, so it "
            "can be asked anywhere; keep the user current with Auth(recheck=), and check "
            "what needs a lookup in the page's connect hook"
        )
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        raise TypeError(f"the rule of {where} has no signature to read") from None
    names = list(signature.parameters.values())
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if not names or names[0].kind not in (*positional, inspect.Parameter.VAR_POSITIONAL):
        raise TypeError(f"the rule of {where} takes the user as its first argument")
    known = set(params)
    wants: list[str] = []
    takes_all = False
    for p in names[1:] if names[0].kind in positional else names:
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            takes_all = True
        elif p.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        elif p.name in known:
            wants.append(p.name)
        elif p.default is inspect.Parameter.empty:
            raise TypeError(
                f"the rule of {where} asks for {p.name!r}, which is not a parameter of its "
                f"path; it has {', '.join(sorted(known)) or 'none'}"
            )
    return Rule(fn, tuple(wants), takes_all)


def ask(rule: Rule | None, user: Any, params: Mapping[str, Any], where: str) -> Verdict:
    """Ask a rule. Only True lets someone in: a rule that raises, or answers
    with anything but True or False, refuses and says so in the log."""
    if rule is None:
        return ALLOWED
    wanted = dict(params) if rule.takes_all else {k: params[k] for k in rule.wants if k in params}
    try:
        answer = rule.fn(user, **wanted)
    except Forbidden as exc:
        return Verdict(False, exc.message)
    except Exception:
        log.exception("the rule %s of %s failed; access refused", rule.name, where)
        return REFUSED
    if answer is True:
        return ALLOWED
    if answer is False:
        return REFUSED
    if inspect.isawaitable(answer):
        close = getattr(answer, "close", None)
        if close is not None:
            close()
    log.error(
        "the rule %s of %s answered %r; a rule answers True or False, so access is refused",
        rule.name,
        where,
        type(answer).__name__,
    )
    return REFUSED
