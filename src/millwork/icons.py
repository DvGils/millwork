"""Icon names: the set the bundle draws, and the check a component runs on its
``icon`` prop, so a name the tab could not draw fails in Python."""

from __future__ import annotations

import difflib
import re

from millwork._icons import PASCAL


def _kebab(name: str) -> str:
    return re.sub(
        r"([a-z])([0-9])",
        r"\1-\2",
        re.sub(r"([A-Z])([A-Z][a-z])", r"\1-\2", re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)),
    ).lower()


ICONS: tuple[str, ...] = tuple(sorted(_kebab(name) for name in PASCAL))
"""Every icon the bundle ships, by its lucide name: ``"file-text"``, ``"trash-2"``."""

# The spellings the tab resolves: the kebab name, the same with its digit
# attached ("trash2"), and the PascalCase export.
_ACCEPTED: frozenset[str] = frozenset(
    {*ICONS, *(re.sub(r"-([0-9])", r"\1", name) for name in ICONS), *PASCAL}
)


def check_icon(name: str | None) -> str | None:
    """The name back when the bundle draws it; ``ValueError`` with the closest
    names otherwise."""
    if not name or name in _ACCEPTED:
        return name
    close = difflib.get_close_matches(name.lower(), ICONS, n=3, cutoff=0.5)
    hint = f"; the closest are {', '.join(close)}" if close else ""
    raise ValueError(f"no icon named {name!r} in the bundle{hint}; see millwork.ICONS")
