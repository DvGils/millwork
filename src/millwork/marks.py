"""Highlights: marks a session holds for the tab to draw over components.

A mark names a component, or a field of a form, and says how the border
around it looks. The session keeps the marks beside the page's tree, works
out after each drawing which components they stand for and which of them
show now, and sends that list when it changed. The tab draws them, takes a
mark off when the person gets to its component or its time runs out, and
says so.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

__all__ = ["KEPT", "PRESETS", "STYLES", "Mark", "bare", "checked", "now"]

# The colors that are the theme's, which hold in the light and in the dark.
PRESETS = ("ring", "primary", "red", "orange", "yellow", "green", "blue", "pink")
STYLES = ("solid", "pulse", "trace")
# How many marks a session holds. One more drops the oldest.
KEPT = 32
# The longest a mark's time can be, in seconds.
LONGEST = 86400.0
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


@dataclass
class Mark:
    # Its number in the session, which the tab says a mark by.
    n: int
    name: str
    color: str
    style: str
    step: int | None
    seconds: float | None
    label: str | None
    scroll: bool
    # The page it waits for, or None for the page the session is on.
    page: str | None


def checked(
    color: Any, style: Any, step: Any, seconds: Any, label: Any, page: Any
) -> tuple[str, str, int | None, float | None, str | None, str | None]:
    """What a mark was given, or a word on what is wrong with it."""
    if not isinstance(color, str) or not (color in PRESETS or _HEX.fullmatch(color)):
        raise ValueError(
            f"a highlight's color is one of {', '.join(PRESETS)} or a hex code as #0a7d5c, "
            f"not {color!r}"
        )
    if style not in STYLES:
        raise ValueError(f"a highlight's style is one of {', '.join(STYLES)}, not {style!r}")
    if step is not None and (isinstance(step, bool) or not isinstance(step, int) or step < 1):
        raise ValueError(f"a highlight's step is a number from 1, not {step!r}")
    if seconds is not None:
        number = isinstance(seconds, int | float) and not isinstance(seconds, bool)
        if not number or not math.isfinite(seconds) or not 0 < seconds <= LONGEST:
            raise ValueError(
                f"a highlight's seconds is a time above nothing, a day at most, not {seconds!r}"
            )
    if label is not None and not isinstance(label, str):
        raise TypeError(f"a highlight's label is a text, not {type(label).__name__}")
    if page is not None and not (isinstance(page, str) and page.startswith("/")):
        raise ValueError(f"a highlight's page is a path as /settings, not {page!r}")
    return (
        color.lower() if color.startswith("#") else color,
        style,
        step,
        float(seconds) if seconds is not None else None,
        label[:24] if label else None,
        bare(page) if page is not None else None,
    )


def bare(path: str) -> str:
    """A path without what follows it: the page a mark is for."""
    return path.split("?")[0].split("#")[0]


def now(marks: list[Mark], find: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The marks of the page the session is on as the tab is given them,
    and the names among them that stand for nothing on the page.

    ``find`` gives the place a name stands for: the id of a node, with the
    pointer of a form's field when it names one, or None. A mark with a
    step shows when no step before it is left, and waits until then. One
    that waits is given to the tab as well, which watches its component
    for a press."""
    here = [m for m in marks if m.page is None]
    first = min((m.step for m in here if m.step is not None), default=None)
    out: list[dict[str, Any]] = []
    nowhere: list[str] = []
    for mark in here:
        place = find(mark.name)
        if place is None:
            if mark.name not in nowhere:
                nowhere.append(mark.name)
            continue
        node, field = place
        said: dict[str, Any] = {"n": mark.n, "id": node, "color": mark.color, "style": mark.style}
        if field is not None:
            said["field"] = field
        if mark.step is not None:
            said["step"] = mark.step
            if mark.step != first:
                said["waits"] = True
        elif mark.label:
            said["label"] = mark.label
        if mark.seconds is not None:
            said["seconds"] = mark.seconds
        if mark.scroll:
            said["scroll"] = True
        out.append(said)
    return out, nowhere
