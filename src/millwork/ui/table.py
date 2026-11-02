"""The Table: rows as data, columns as a spec, tones instead of styles.

Phase 1: every row is in the browser;
sort, filter and pagination are the table's business; selection is the
server's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import to_jsonable_python

from millwork.icons import check_icon
from millwork.nodes import Component

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
    destructive: bool = False
    confirm: str | None = None
    separator_after: bool = False

    @field_validator("icon")
    @classmethod
    def _known_icon(cls, name: str | None) -> str | None:
        return check_icon(name)


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode="json")
    if isinstance(row, Mapping):
        return {str(k): to_jsonable_python(v) for k, v in row.items()}
    raise TypeError(f"a table row is a mapping or a model, not {type(row).__name__}")


class Table(Component):
    type: ClassVar[str] = "Table"
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
        rows = [_row_dict(r) for r in self.rows]
        columns = self.columns
        if columns is None:
            keys = list(rows[0].keys()) if rows else []
            columns = [Column(key=k) for k in keys]
        tone_rows: dict[int, str] = {}
        tone_cells: dict[int, dict[str, str]] = {}
        if callable(self.tones):
            for i, raw in enumerate(self.rows):
                tone = self.tones(raw)
                if tone:
                    tone_rows[i] = tone
        elif self.tones:
            for i, (raw, row) in enumerate(zip(self.rows, rows, strict=True)):
                for col, fn in self.tones.items():
                    tone = fn(raw, row.get(col))
                    if tone:
                        tone_cells.setdefault(i, {})[col] = tone
        # Keys the browser uses for selection and clicks. Rows without the key column
        # fall back to their index, which only works when no row has a key to clash with.
        keyed = [self.row_key in row for row in rows]
        if any(keyed) and not all(keyed):
            missing = keyed.index(False)
            raise ValueError(f"table row {missing} has no {self.row_key!r}; every row needs one")
        keys = [to_jsonable_python(row.get(self.row_key, i)) for i, row in enumerate(rows)]
        return {
            "rows": rows,
            "keys": keys,
            "columns": [c.model_dump(mode="json") for c in columns],
            "tone_rows": {str(i): t for i, t in tone_rows.items()},
            "tone_cells": {str(i): t for i, t in tone_cells.items()},
        }

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            rows: Sequence[Any] = ...,
            columns: list[Column] | None = None,
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
