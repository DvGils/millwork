"""The Table: rows as data, columns as a spec, tones instead of styles.

Phase 1: every row is in the browser;
sort, filter and pagination are the table's business; selection is the
server's.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import to_jsonable_python

from millwork.icons import check_icon
from millwork.nodes import Component, Wired

Format = Literal[
    "text",
    "number",
    "integer",
    "percent",
    "currency",
    "date",
    "datetime",
    "bool",
    "badge",
    "link",
    "code",
]
Tone = Literal["default", "muted", "primary", "accent", "success", "warning", "destructive"]
Row = Mapping[str, Any]


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    header: str | None = None
    width: int | str | None = None
    align: Literal["left", "center", "right"] = "left"
    format: Format = "text"
    sortable: bool = True
    filterable: bool = True
    hidden: bool = False
    wrap: bool = False


class MenuItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    icon: str | None = None
    disabled: bool = False
    # The look of the item; whether the action asks first is ``confirm``.
    destructive: bool = False
    # Asked before the handler runs; a cancelled question drops the choice.
    confirm: str | None = None
    separator_after: bool = False

    @field_validator("icon")
    @classmethod
    def _known_icon(cls, name: str | None) -> str | None:
        return check_icon(name)


def _wire_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Every row as a JSON-ready dict of its own. A model is its own dump. The
    rest, dicts for the most part, go through the serializer in one call for
    the lot, since a render pays this for each table on the page, changed or
    not."""
    models = 0
    ready: list[Any] = []
    for raw in rows:
        if type(raw) is dict:
            ready.append(raw)
        elif isinstance(raw, BaseModel):
            ready.append(raw.model_dump(mode="json"))
            models += 1
        elif isinstance(raw, Mapping):
            ready.append(dict(raw))
        elif dataclasses.is_dataclass(raw) and not isinstance(raw, type):
            ready.append(raw)
        else:
            raise TypeError(
                f"a table row is a mapping, a model or a dataclass, not {type(raw).__name__}"
            )
    # A dump is JSON-ready already, and a table of models is nothing else.
    out: list[dict[str, Any]] = ready if models == len(ready) else to_jsonable_python(ready)
    return out


# Whole numbers up to here are held exactly by a number in a browser. Past
# it two ids can arrive as one.
_EXACT = 2**53


def _as_tab(value: Any) -> Any:
    """A JSON value as a tab holds it after the wire: every number a float,
    and one that is no number at all, a NaN say, nothing."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int | float):
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) else None
    if isinstance(value, Mapping):
        return {str(k): _as_tab(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_as_tab(v) for v in value]
    return str(value)


def _mark(key: Any) -> Any:
    """A row key as the tab will tell it from another, in a form a set can
    hold, or None for one the tab gets as nothing. True and 1 are two keys
    there, 1 and 1.0 are one, and so are two whole numbers too large for a
    browser to keep apart."""
    there = _as_tab(key)
    if there is None or isinstance(there, str | float):
        return there
    if isinstance(there, bool):
        return ("bool", there)
    return ("json", json.dumps(there))


def _clash(keys: list[Any]) -> tuple[int, ...] | None:
    """What keeps a table's row keys from telling its rows apart: the one
    row that has none, or the two that share one. None when they do."""
    marks = [
        k if type(k) is str or (type(k) is int and -_EXACT < k < _EXACT) else _mark(k) for k in keys
    ]
    if None not in marks and len(set(marks)) == len(marks):
        return None
    seen: dict[Any, int] = {}
    for index, mark in enumerate(marks):
        if mark is None:
            return (index,)
        first = seen.setdefault(mark, index)
        if first != index:
            return (first, index)
    return None


class Table(Component):
    """Rows as data. A row is a dict, a model or a dataclass, and ``row_key``
    names the field that tells rows apart. A column is headed by its key
    as it is written, since the data may not be the app's to rename, until
    ``header`` says otherwise.
    ``tones`` is one function ``(row) -> tone`` for a row's tone, or a mapping
    from column key to ``(row, value) -> tone`` for a cell's. ``row`` is the
    row as it is in ``rows``, a model still a model, and ``value`` is the
    cell as the table shows it. A tone is one of ``muted``, ``primary``,
    ``accent``, ``success``, ``warning`` and ``destructive``, or ``None``."""

    type: ClassVar[str] = "Table"
    payloads: ClassVar[dict[str, str]] = {
        "on_select": "the selected row keys",
        "on_row_click": "the row's key",
        "on_action": "[action_id, row_key]",
        "on_sort": "[[column, 'asc' | 'desc'], ...]",
        "on_filter": "{'columns': {column: value}, 'search': text}",
    }
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"tones", "rows"})

    rows: Sequence[Any] = []
    columns: list[Column] | None = None
    row_key: str = "id"
    height: int | str | None = None
    sticky_header: bool = True
    sortable: bool = True
    default_sort: list[tuple[str, Literal["asc", "desc"]]] = []
    filters: bool = False
    search: bool = False
    page_size: int | None = None
    selection: Literal["none", "row", "rows"] = "none"
    selected: list[Any] = []
    row_actions: list[MenuItem] = []
    tones: Callable[[Any], str | None] | Mapping[str, Callable[[Any, Any], str | None]] | None = (
        None
    )
    summary: bool | str = True
    empty: str = ""
    on_select: Any = None
    on_row_click: Any = None
    on_action: Any = None
    on_sort: Any = None
    on_filter: Any = None

    @field_validator("columns", mode="before")
    @classmethod
    def _columns(cls, value: Any) -> Any:
        if value is None:
            return None
        out = []
        for c in value:
            if isinstance(c, str):
                out.append(Column(key=c))
            elif isinstance(c, Column):
                out.append(c)
            elif isinstance(c, Mapping):
                out.append(Column(**c))
            else:
                raise TypeError(f"not a column: {c!r}")
        return out

    def wire_extra(self) -> dict[str, Any]:
        rows = _wire_rows(self.rows)
        columns = self.columns
        if columns is None:
            keys = list(rows[0].keys()) if rows else []
            columns = [Column(key=k) for k in keys]
        # Tones go as lists beside the rows, one place per row, so a row that
        # comes or goes moves its tone with it. A table without tones has none.
        tone_rows: list[str | None] = []
        tone_cells: list[dict[str, str] | None] = []
        if callable(self.tones):
            tone_rows = [self.tones(raw) or None for raw in self.rows]
        elif self.tones:
            for raw, row in zip(self.rows, rows, strict=True):
                cells = {}
                for col, fn in self.tones.items():
                    tone = fn(raw, row.get(col))
                    if tone:
                        cells[col] = tone
                tone_cells.append(cells or None)
        # Keys the browser uses for selection and clicks. They are the values
        # of the key column where those tell the rows apart, and the rows'
        # positions where they do not: no row has the column, one has
        # nothing in it, or two share a value. A table that only shows its
        # rows gets by on positions, as the rows of a query's result may have
        # no key at all. One that names rows by key, to select, open or act
        # on them, would take two rows for one or have no name for a row.
        row_key = self.row_key
        row_keys: list[Any] = list(range(len(rows)))
        if any(row_key in row for row in rows):
            named = [row.get(row_key) for row in rows]
            clash = _clash(named)
            if clash is None:
                row_keys = named
            elif self.selection != "none" or self.on_row_click or self.row_actions or self.selected:
                if len(clash) == 1:
                    said = f"row {clash[0]} has no {row_key!r}"
                else:
                    first, second = clash
                    said = f"rows {first} and {second} share the {row_key!r} {named[first]!r}"
                    if named[first] != named[second]:
                        said += f" and {named[second]!r}, which are one value in a browser"
                raise ValueError(
                    f"table {said}; a table that selects, opens or acts on a row needs "
                    "a row_key whose values tell its rows apart"
                )
        return {
            "rows": Wired(rows),
            "keys": Wired(row_keys),
            "columns": [c.model_dump(mode="json") for c in columns],
            "tone_rows": Wired(tone_rows),
            "tone_cells": Wired(tone_cells),
        }

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            rows: Sequence[Any] = ...,
            columns: Sequence[Column | str | Mapping[str, Any]] | None = None,
            row_key: str = "id",
            height: int | str | None = None,
            sticky_header: bool = True,
            sortable: bool = True,
            default_sort: list[tuple[str, Literal["asc", "desc"]]] = ...,
            filters: bool = False,
            search: bool = False,
            page_size: int | None = None,
            selection: Literal["none", "row", "rows"] = "none",
            selected: list[Any] = ...,
            row_actions: list[MenuItem] = ...,
            tones: Callable[[Any], str | None]
            | Mapping[str, Callable[[Any, Any], str | None]]
            | None = None,
            summary: bool | str = True,
            empty: str = "",
            on_select: Any = None,
            on_row_click: Any = None,
            on_action: Any = None,
            on_sort: Any = None,
            on_filter: Any = None,
        ) -> None: ...
