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


# An icon of the app's own: a file under ``public/``, by the path it is served
# at. The folder is spelled as it is served, and every segment after it
# starts with a letter, a digit, ``_`` or ``-``, so none is ``..`` or hidden.
# The name ends in a kind of image the tab can draw, in either case. Only
# letters and digits of ASCII count, the same ones the tab accepts. Nothing
# in a path of this shape can lead out of ``/public/`` or to another site.
_FILE = re.compile(
    r"/public(?:/[A-Za-z0-9_-][A-Za-z0-9._-]*)+\.(?i:svg|png|webp|jpg|jpeg)", re.ASCII
)
_FILE_LIMIT = 200
# No icon's name comes near this. What is longer is refused as it stands,
# without being weighed against every name there is.
_NAME_LIMIT = 64


def is_icon_file(name: str) -> bool:
    """Whether ``name`` is the path of an icon file under ``public/``."""
    return len(name) <= _FILE_LIMIT and _FILE.fullmatch(name) is not None


def _shown(name: str) -> str:
    """A value as an error quotes it: whole when it is short."""
    return repr(name) if len(name) <= _NAME_LIMIT else repr(name[:_NAME_LIMIT]) + "…"


def check_icon(name: str | None) -> str | None:
    """``name`` if the tab can draw it: an icon of the bundle by its name, or
    a file under ``public/`` by its path, such as ``/public/icons/rocket.svg``.
    The file is the browser's to fetch and is never opened here. Anything
    else is a ValueError, with the closest names for a name."""
    if not name or name in _ACCEPTED:
        return name
    if name.startswith("/"):
        if is_icon_file(name):
            return name
        raise ValueError(
            f"an icon file is a path under /public/ that ends in .svg, .png, .webp or .jpg, "
            f"such as /public/icons/rocket.svg, got {_shown(name)}"
        )
    close = (
        difflib.get_close_matches(name.lower(), ICONS, n=3, cutoff=0.5)
        if len(name) <= _NAME_LIMIT
        else []
    )
    hint = f"; the closest are {', '.join(close)}" if close else ""
    raise ValueError(
        f"no icon named {_shown(name)} in the bundle{hint}; see millwork.ICONS, "
        "or give the path of a file under /public/"
    )
