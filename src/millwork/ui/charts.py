"""Charts: rows in, a drawn chart out, coloured from the theme's chart tokens.

A chart takes rows like the Table does. ``x`` names the category or time
column; ``y`` names one value column or several (wide rows), or one value
column with ``by`` naming the column that holds the series name (long rows),
which Python pivots to wide before the wire. Series keep the order they are
given or first appear in and take ``chart-1`` to ``chart-5`` in that order,
so a series keeps its colour when a filter removes a neighbour.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, PrivateAttr, model_validator
from pydantic_core import to_jsonable_python

from millwork.nodes import Component

MAX_SERIES = 5
"""Five hues the theme defines; a sixth series would need a generated colour."""

ValueFormat = Literal["number", "integer", "percent", "currency"]


def _value(v: Any) -> Any:
    # A Decimal (database rows) would become a string, and a string is a gap.
    if isinstance(v, Decimal):
        return float(v)
    return to_jsonable_python(v)


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, BaseModel):
        return {k: _value(v) for k, v in row.model_dump().items()}
    if isinstance(row, Mapping):
        return {str(k): _value(v) for k, v in row.items()}
    raise TypeError(f"a chart row is a mapping or a model, not {type(row).__name__}")


def _series_spec(y: Any) -> list[dict[str, str]]:
    if isinstance(y, str):
        return [{"key": y, "label": y}]
    if isinstance(y, Mapping):
        return [{"key": str(k), "label": str(v)} for k, v in y.items()]
    if isinstance(y, Sequence):
        out: list[dict[str, str]] = []
        for item in y:
            if isinstance(item, str):
                out.append({"key": item, "label": item})
            elif isinstance(item, Sequence) and len(item) == 2:
                out.append({"key": str(item[0]), "label": str(item[1])})
            else:
                raise TypeError("a series is a column name or a (column, label) pair")
        return out
    raise TypeError("y is a column name, a list of them, or a mapping of column to label")


class _Chart(Component):
    """What every chart shares: rows, the x column, series, formats, a click."""

    wire_exclude: ClassVar[frozenset[str]] = frozenset({"rows", "y", "by"})

    rows: Sequence[Any]
    x: str
    y: Any
    by: str | None = None
    format: ValueFormat | None = None
    labels: bool = False
    legend: bool | None = None
    emphasis: str | None = None
    height: int | None = None
    on_click: Any = None

    # Built once from the rows: the series in drawing order and the wide points.
    _series: list[dict[str, str]] = PrivateAttr()
    _points: list[dict[str, Any]] = PrivateAttr()

    def __init__(self, rows: Sequence[Any] = (), **props: Any) -> None:
        super().__init__(rows=rows, **props)

    @model_validator(mode="after")
    def _check(self) -> _Chart:
        if self.by is not None and not isinstance(self.y, str):
            raise ValueError("with by=, y names the one column that holds the values")
        dicts = [_row_dict(r) for r in self.rows]
        if dicts:
            wanted = [self.x, self.by, str(self.y)] if self.by else [self.x]
            missing = [c for c in wanted if c not in dicts[0]]
            if missing:
                raise ValueError(f"the rows have no column {missing[0]!r}")
        series = self._build_series(dicts)
        if not series:
            raise ValueError("a chart needs at least one series")
        if len(series) > MAX_SERIES:
            raise ValueError(
                f"a chart draws {MAX_SERIES} series at most; fold the rest into one, "
                "or draw several charts"
            )
        keys = [s["key"] for s in series]
        if len(set(keys)) != len(keys):
            raise ValueError("series keys repeat")
        if "x" in keys:
            raise ValueError("a series cannot be called 'x'; that name is the category")
        if self.emphasis is not None and self.emphasis not in keys:
            raise ValueError(f"emphasis names a series; {self.emphasis!r} is not one of {keys}")
        if dicts and self.by is None:
            missing = [k for k in keys if k not in dicts[0]]
            if missing:
                hint = ""
                if isinstance(self.y, tuple) and len(self.y) == 2:
                    hint = " (a (column, label) pair goes inside a list)"
                raise ValueError(f"the rows have no column {missing[0]!r}{hint}")
        self._series = series
        self._points = self._build_points(dicts, keys)
        return self

    def _build_series(self, dicts: list[dict[str, Any]]) -> list[dict[str, str]]:
        if self.by is None:
            return _series_spec(self.y)
        value = str(self.y)
        seen: dict[str, None] = {}
        for r in dicts:
            name = r.get(self.by)
            if name is not None:
                seen.setdefault(str(name), None)
        return [{"key": k, "label": k} for k in seen] or [{"key": value, "label": value}]

    def _build_points(self, dicts: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
        if self.by is None:
            return [{"x": r.get(self.x), **{k: r.get(k) for k in keys}} for r in dicts]
        value = str(self.y)
        order: dict[Any, dict[str, Any]] = {}
        for r in dicts:
            x = r.get(self.x)
            try:
                point = order.setdefault(x, {"x": x})
            except TypeError:
                raise ValueError(f"with by=, x values must be hashable, not {x!r}") from None
            name = r.get(self.by)
            if name is None:
                continue
            if str(name) in point:
                raise ValueError(
                    f"two rows have {self.x}={x!r} and {self.by}={name!r}; group the rows first"
                )
            point[str(name)] = r.get(value)
        return [{"x": p["x"], **{k: p.get(k) for k in keys}} for p in order.values()]

    def series(self) -> list[dict[str, str]]:
        """The series on the wire: ``{key, label}`` in drawing order."""
        return self._series

    def points(self) -> list[dict[str, Any]]:
        """Wide rows: ``x`` plus one value per series key, in row order."""
        return self._points

    def wire_extra(self) -> dict[str, Any]:
        return {"data": self._points, "series": self._series}


class BarChart(_Chart):
    """Bars for magnitudes by category: grouped, ``stacked``, ``horizontal``.

    ``stacked="percent"`` stacks to a full bar. ``diverging`` is for an
    ordered scale such as agree to disagree: the series are a scale from
    one pole to the other, drawn to either side of a neutral midpoint, and
    coloured from two hues through grey instead of five. Its values are
    counts, never negative, and it draws no value labels.
    """

    type: ClassVar[str] = "BarChart"
    stacked: bool | Literal["percent"] = False
    horizontal: bool = False
    diverging: bool = False

    @model_validator(mode="after")
    def _check_bars(self) -> BarChart:
        if self.diverging and self.stacked == "percent":
            raise ValueError("a diverging chart is stacked around its midpoint; percent is not")
        if self.diverging and self.emphasis is not None:
            raise ValueError("a diverging chart colours a scale, not one series")
        if self.diverging:
            for point in self.points():
                for k, v in point.items():
                    if k != "x" and isinstance(v, int | float) and v < 0:
                        raise ValueError(
                            f"a diverging chart stacks counts to either side; {k}={v!r} is negative"
                        )
        return self


class LineChart(_Chart):
    """Lines over an ordered x: one per series, a crosshair tooltip across them.

    ``curve`` smooths the lines; ``dots`` marks every point.
    """

    type: ClassVar[str] = "LineChart"
    curve: bool = False
    dots: bool = False


class AreaChart(_Chart):
    """Lines with the space under them filled; ``stacked`` adds the series up."""

    type: ClassVar[str] = "AreaChart"
    stacked: bool | Literal["percent"] = False
    curve: bool = False


class PieChart(Component):
    """Shares of a whole: one slice per row, ``x`` naming the slice and ``y``
    the value. Slices take ``chart-1`` to ``chart-5`` in row order. Over five,
    the smallest fold into one slice named by ``other``, drawn in grey; with
    ``other=None`` a sixth row is refused instead. ``donut`` leaves the middle
    open and ``center`` writes a figure there. ``labels`` writes each slice's
    share beside it."""

    type: ClassVar[str] = "PieChart"
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"rows", "y", "other"})

    rows: Sequence[Any]
    x: str
    y: str
    format: ValueFormat | None = None
    labels: bool = False
    legend: bool | None = None
    donut: bool = False
    center: str | None = None
    other: str | None = "Other"
    height: int | None = None
    on_click: Any = None

    _slices: list[dict[str, Any]] = PrivateAttr()

    def __init__(self, rows: Sequence[Any] = (), **props: Any) -> None:
        super().__init__(rows=rows, **props)

    @model_validator(mode="after")
    def _check(self) -> PieChart:
        if self.x == self.y:
            raise ValueError("x names the slice and y its value; they are different columns")
        dicts = [_row_dict(r) for r in self.rows]
        if dicts:
            for c in (self.x, self.y):
                if c not in dicts[0]:
                    raise ValueError(f"the rows have no column {c!r}")
        slices: list[dict[str, Any]] = []
        for r in dicts:
            v = r.get(self.y)
            if v is None:
                continue
            if not isinstance(v, int | float):
                raise ValueError(f"a slice's value is a number, not {v!r}")
            if v < 0:
                raise ValueError(
                    f"a pie has no negative slice; {self.x}={r.get(self.x)!r} is {v!r}"
                )
            slices.append({"x": r.get(self.x), "value": v, "other": False})
        if len(slices) > MAX_SERIES:
            if self.other is None:
                raise ValueError(
                    f"a pie draws {MAX_SERIES} slices at most; fold the rest into one, "
                    "or let other= name the slice they fold into"
                )
            # The largest keep their place and their colour; the rest become one.
            ranked = sorted(range(len(slices)), key=lambda i: slices[i]["value"], reverse=True)
            kept = sorted(ranked[: MAX_SERIES - 1])
            rest = sum(slices[i]["value"] for i in ranked[MAX_SERIES - 1 :])
            slices = [slices[i] for i in kept] + [{"x": self.other, "value": rest, "other": True}]
        self._slices = slices
        return self

    def slices(self) -> list[dict[str, Any]]:
        """The slices on the wire: ``{x, value, other}`` in drawing order."""
        return self._slices

    def wire_extra(self) -> dict[str, Any]:
        return {"data": self._slices}


__all__ = ["AreaChart", "BarChart", "LineChart", "PieChart", "MAX_SERIES"]
