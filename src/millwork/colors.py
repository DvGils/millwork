"""Colors as the framework holds them: hex codes, ``#rrggbb`` in lower case."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_HEX_CODE = re.compile(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})")


def as_color(value: Any) -> Any:
    """A color as a tab holds it. Three digits stand for six, and capitals
    are the same color. What is no text is left for the field to refuse."""
    if not isinstance(value, str):
        return value
    code = value.strip().lower()
    if not _HEX_CODE.fullmatch(code):
        raise ValueError(f"{value!r} is not a color, which is a hex code such as '#3b82f6'")
    return code if len(code) == 7 else "#" + "".join(digit * 2 for digit in code[1:])


def as_colors(values: Any) -> Any:
    """Colors to pick from, each once and in the order given."""
    if isinstance(values, str) or not isinstance(values, Iterable):
        return values
    return list(dict.fromkeys(as_color(value) for value in values))
