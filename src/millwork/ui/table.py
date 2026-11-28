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
from typing import TYPE_CHECKING, Any, ClassVar, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticSerializationError, to_jsonable_python

from millwork.icons import check_icon
from millwork.nodes import Component, Wired, shown_bytes

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
# The formats whose cells can be typed over: a text, a number, and a yes or no.
EDITABLE = frozenset({"text", "number", "integer", "percent", "currency", "bool"})
Row = Mapping[str, Any]
_TONES = frozenset(get_args(Tone))


def _tone(tone: Any, of: str) -> str | None:
    """What a ``tones`` function returned, when it is a tone or nothing. The
    tab draws any other value as no tone at all, which looks like a function
    that was never called."""
    if not tone:
        return None
    if not isinstance(tone, str) or tone not in _TONES:
        raise ValueError(
            f"the tone of {of} is one of {', '.join(sorted(_TONES))}, or None, and the "
            f"function in tones returned {tone!r}"
        )
    return tone


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    header: str | None = None
    group: str | None = None
    """A heading over this column and the columns shown next to it that
    name the same group, such as a year over its quarters. Columns that
    are not shown next to each other each get a heading of their own."""
    width: int | str | None = None
    align: Literal["left", "center", "right"] = "left"
    format: Format = "text"
    sortable: bool = True
    filterable: bool = True
    editable: bool = False
    """The cells of this column can be typed over, in a table that has
    ``on_edit``. For a column of text, of numbers, or of yes and no,
    whose cells are one line. In a table without ``on_edit`` the column
    is shown as any other, so a page that lets only some people type
    leaves the handler out for the rest."""
    hidden: bool = False
    wrap: bool = False
    lines: int | None = Field(default=None, ge=1)
    """At most this many lines of a cell show, and the rest is cut with
    three dots. The whole text shows under the pointer, and the table's
    search reads all of it. A column that has no ``width`` then takes the
    width the other columns leave."""

    @model_validator(mode="after")
    def _editable_is_typed(self) -> Column:
        if not self.editable:
            return self
        if self.format not in EDITABLE:
            raise ValueError(
                f"the column {self.key!r} is {self.format}, and a cell that is typed over "
                f"is one of {', '.join(sorted(EDITABLE))}"
            )
        if self.wrap or (self.lines or 1) > 1:
            raise ValueError(
                f"the column {self.key!r} is editable, and a cell that is typed over is "
                "one line, so it has no wrap and no more lines than one"
            )
        return self

    @field_validator("group")
    @classmethod
    def _a_group_has_a_name(cls, group: str | None) -> str | None:
        """A group that is empty or only spaces is no group, here as in
        the tab, which would draw a heading with nothing in it."""
        return (group.strip() or None) if group is not None else None


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


# The most rows a table has when they can be dragged, which is the most a
# table draws all of. A longer one draws the rows in view alone, and a row
# cannot be carried past rows that are not there.
MOVABLE = 200


class CellEdit(BaseModel):
    """A cell of a ``Table`` that was typed over, as ``on_edit`` gets it.
    ``key`` is the row's key and ``column`` the column's. ``value`` is what
    was typed, as the column's format has it: a ``str`` for text, a
    ``float`` for a number, a currency or a percent (the percent as the
    fraction it stands for, 0.25 for 25%), an ``int`` for an integer, a
    ``bool`` for a yes or no. A number that was emptied is ``None``."""

    model_config = ConfigDict(frozen=True)

    key: Any
    column: str
    value: Any


class RowMove(BaseModel):
    """A row of a ``Table`` that was dragged, as ``on_move`` gets it. ``key``
    is the row's key and ``to`` its new place among the rows, counted from 0
    with the row itself left out, so that ``rows.insert(move.to, row)``
    after taking the row out puts it there."""

    model_config = ConfigDict(frozen=True)

    key: Any
    to: int


def _wire_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Every row as a JSON-ready dict of its own. A model is its own dump. The
    rest, dicts for the most part, go through the serializer in one call for
    the lot, since a render pays this for each table on the page, changed or
    not."""
    models = 0
    ready: list[Any] = []
    try:
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
        if models == len(ready):
            return ready
        out: list[dict[str, Any]] = to_jsonable_python(ready)
    except (UnicodeDecodeError, PydanticSerializationError):
        # A cell of bytes that are no text, a blob from a database say, or
        # a view of some. The rows are gone over once more, by hand.
        out = to_jsonable_python([_without_blobs(row) for row in rows])
    return out


def _without_blobs(value: Any) -> Any:
    """A row with each run of bytes in it as a page can show it."""
    if isinstance(value, bytes | bytearray | memoryview):
        return shown_bytes(value)
    if isinstance(value, BaseModel):
        return _without_blobs(value.model_dump())
    if isinstance(value, Mapping):
        return {k: _without_blobs(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_without_blobs(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _without_blobs(dataclasses.asdict(value))
    return value


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
    cell as it goes to the tab, before the column's ``format``. A number is
    a number, a date is its ISO text, a ``Decimal`` its text and an ``Enum``
    its value. A tone is one of ``muted``, ``primary``,
    ``accent``, ``success``, ``warning`` and ``destructive``, or ``None``."""

    type: ClassVar[str] = "Table"
    payloads: ClassVar[dict[str, str]] = {
        "on_select": "the selected row keys",
        "on_row_click": "the row's key",
        "on_action": "[action_id, row_key]",
        "on_sort": "[[column, 'asc' | 'desc'], ...]",
        "on_filter": "{'columns': {column: value}, 'search': text}",
        "on_move": "a RowMove: the row's key and its new place",
        "on_edit": "a CellEdit: the row's key, the column and the value typed",
    }
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"tones", "rows"})

    rows: Sequence[Any] = []
    columns: list[Column] | None = None
    row_key: str = "id"
    height: int | str | None = None
    fill: bool = False
    """The table takes the room that is left, on a page or in a ``Stack``
    that fills, and its rows scroll inside it. In place of a ``height``."""
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
    on_move: Any = None
    """With a handler here the rows have a grip and are dragged into
    another order, or moved a place at a time with Alt and an arrow key.
    The handler gets a ``RowMove`` and changes the rows, and the table
    drawn from them is where the row ends up: a handler that leaves the
    rows as they were sends the row back. Such a table shows its rows in
    the order they have, so it is not sorted by a column, filtered,
    searched or paged, and it has at most 200 rows, each with a key."""

    @model_validator(mode="after")
    def _one_height(self) -> Table:
        if self.fill and self.height is not None:
            raise ValueError("a table has a height or fills the room that is left, not both")
        return self

    on_edit: Any = None
    """With a handler here the cells of the columns that are ``editable``
    are typed over where they stand. The handler gets a ``CellEdit`` and
    changes the row, and the table drawn from the rows is what the cell
    shows: a handler that leaves the row as it was sends the cell back.
    Each row has a key. Such a table's rows are not pressed, so it does
    not go with ``on_row_click`` or ``selection="row"``."""

    @model_validator(mode="after")
    def _typed_cells_have_a_column(self) -> Table:
        if self.on_edit is None:
            return self
        if not any(c.editable and not c.hidden for c in self.columns or []):
            raise ValueError(
                "a table with on_edit has a column that is editable and shown, and none is"
            )
        if self.on_row_click is not None or self.selection == "row":
            other = "on_row_click" if self.on_row_click is not None else 'selection="row"'
            raise ValueError(
                "a press on a cell that is typed over opens it, so on_edit does not go with "
                f"{other}, where a press is on the row"
            )
        return self

    @model_validator(mode="after")
    def _dragged_rows_keep_their_order(self) -> Table:
        if self.on_move is None:
            return self
        other = [
            name
            for name, on in (
                ("filters", self.filters),
                ("search", self.search),
                ("page_size", self.page_size is not None),
                ("default_sort", bool(self.default_sort)),
                ("on_sort", self.on_sort is not None),
                ("on_filter", self.on_filter is not None),
            )
            if on
        ]
        if other:
            raise ValueError(
                "a table whose rows are dragged shows them in the order they have, so "
                f"on_move does not go with {' or '.join(other)}"
            )
        return self

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
            tone_rows = [_tone(self.tones(raw), "a row") for raw in self.rows]
        elif self.tones:
            for raw, row in zip(self.rows, rows, strict=True):
                cells = {}
                for col, fn in self.tones.items():
                    tone = _tone(fn(raw, row.get(col)), f"a cell of {col!r}")
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
        keyed = False
        if any(row_key in row for row in rows):
            named = [row.get(row_key) for row in rows]
            clash = _clash(named)
            if clash is None:
                row_keys = named
                keyed = True
            elif (
                self.selection != "none"
                or self.on_row_click
                or self.row_actions
                or self.selected
                or self.on_move
                or self.on_edit
            ):
                if len(clash) == 1:
                    said = f"row {clash[0]} has no {row_key!r}"
                else:
                    first, second = clash
                    said = f"rows {first} and {second} share the {row_key!r} {named[first]!r}"
                    if named[first] != named[second]:
                        said += f" and {named[second]!r}, which are one value in a browser"
                raise ValueError(
                    f"table {said}; a table that selects, opens, moves, edits or acts on a "
                    "row needs a row_key whose values tell its rows apart"
                )
        if rows and not keyed and (self.on_move is not None or self.on_edit is not None):
            what = "rows are dragged" if self.on_move is not None else "cells are typed over"
            raise ValueError(
                f"a table whose {what} names each row by its {row_key!r}, and these rows have none"
            )
        if self.on_move is not None:
            if len(rows) > MOVABLE:
                raise ValueError(
                    f"a table whose rows are dragged has at most {MOVABLE} rows, "
                    f"and this one has {len(rows)}"
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
            fill: bool = False,
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
            on_move: Any = None,
            on_edit: Any = None,
        ) -> None: ...
