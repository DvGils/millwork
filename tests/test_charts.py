import datetime as dt

import pytest
from pydantic import BaseModel

from millwork import ui
from millwork.nodes import build

WIDE = [
    {"month": "Jan", "sales": 10, "costs": 7},
    {"month": "Feb", "sales": 12, "costs": 8},
]
LONG = [
    {"month": "Jan", "region": "North", "sales": 10},
    {"month": "Jan", "region": "South", "sales": 4},
    {"month": "Feb", "region": "South", "sales": 5},
    {"month": "Feb", "region": "North", "sales": 12},
    {"month": "Mar", "region": "North", "sales": None},
]


def test_wide_rows_on_the_wire() -> None:
    node = build(ui.BarChart(WIDE, x="month", y=["sales", "costs"], on_click=lambda s, p: None))
    props = node.nodes["root"].props
    assert "rows" not in props and "y" not in props
    assert props["series"] == [
        {"key": "sales", "label": "sales"},
        {"key": "costs", "label": "costs"},
    ]
    assert props["data"] == [
        {"x": "Jan", "sales": 10, "costs": 7},
        {"x": "Feb", "sales": 12, "costs": 8},
    ]
    assert props["on_click"] is True and props["stacked"] is False


def test_series_labels_from_a_mapping_or_pairs() -> None:
    chart = ui.LineChart(WIDE, x="month", y={"sales": "Sales", "costs": "Costs"})
    assert [s["label"] for s in chart.series()] == ["Sales", "Costs"]
    chart = ui.LineChart(WIDE, x="month", y=[("sales", "Sales")])
    assert chart.series() == [{"key": "sales", "label": "Sales"}]
    assert ui.LineChart(WIDE, x="month", y="sales").series() == [{"key": "sales", "label": "sales"}]


def test_long_rows_pivot_in_first_seen_order() -> None:
    chart = ui.BarChart(LONG, x="month", y="sales", by="region", stacked=True)
    assert [s["key"] for s in chart.series()] == ["North", "South"]
    assert chart.points() == [
        {"x": "Jan", "North": 10, "South": 4},
        {"x": "Feb", "North": 12, "South": 5},
        {"x": "Mar", "North": None, "South": None},
    ]


def test_models_and_dates_as_rows() -> None:
    class Day(BaseModel):
        day: dt.date
        hits: int

    rows = [Day(day=dt.date(2026, 1, 1), hits=3), Day(day=dt.date(2026, 1, 2), hits=5)]
    assert ui.AreaChart(rows, x="day", y="hits").points() == [
        {"x": "2026-01-01", "hits": 3},
        {"x": "2026-01-02", "hits": 5},
    ]


def test_validation() -> None:
    with pytest.raises(ValueError, match="at most"):
        ui.BarChart(WIDE, x="month", y=["a", "b", "c", "d", "e", "f"])
    with pytest.raises(ValueError, match="no column 'nope'"):
        ui.BarChart(WIDE, x="nope", y="sales")
    with pytest.raises(ValueError, match="no column 'size'"):
        ui.BarChart(WIDE, x="month", y="size")
    with pytest.raises(ValueError, match="emphasis names a series"):
        ui.BarChart(WIDE, x="month", y="sales", emphasis="costs")
    with pytest.raises(ValueError, match="with by="):
        ui.BarChart(LONG, x="month", y=["sales", "x"], by="region")
    with pytest.raises(ValueError, match="repeat"):
        ui.BarChart(WIDE, x="month", y=["sales", "sales"])
    with pytest.raises(ValueError, match="percent is not"):
        ui.BarChart(WIDE, x="month", y=["sales", "costs"], diverging=True, stacked="percent")
    with pytest.raises(ValueError, match="at least one"):
        ui.BarChart(WIDE, x="month", y=[])
    with pytest.raises(TypeError, match="mapping or a model"):
        ui.BarChart([("Jan", 1)], x="month", y="sales")


def test_empty_rows_are_fine() -> None:
    props = build(ui.LineChart(x="month", y="sales")).nodes["root"].props
    assert props["data"] == [] and props["series"] == [{"key": "sales", "label": "sales"}]


def test_stat_delta_and_trend() -> None:
    props = (
        build(ui.Stat(label="Revenue", value="€12k", delta=0.12, good="up", trend=[1, 2, 3]))
        .nodes["root"]
        .props
    )
    assert props["delta"] == 0.12 and props["delta_format"] == "percent"
    assert props["trend"] == [1, 2, 3] and props["good"] == "up"


def test_the_data_layer_rejects_what_would_draw_wrong() -> None:
    from decimal import Decimal

    # A series called x would overwrite the category.
    with pytest.raises(ValueError, match="cannot be called 'x'"):
        ui.BarChart([{"t": "a", "x": 5}], x="t", y="x")
    with pytest.raises(ValueError, match="cannot be called 'x'"):
        ui.BarChart([{"t": "a", "k": "x", "v": 5}], x="t", y="v", by="k")
    # With by=, the value column is checked like the others.
    with pytest.raises(ValueError, match="no column 'nope'"):
        ui.BarChart(LONG, x="month", y="nope", by="region")
    # Two rows for one (x, by) pair means the rows were not grouped.
    with pytest.raises(ValueError, match="group the rows first"):
        ui.BarChart(
            LONG + [{"month": "Jan", "region": "North", "sales": 1}],
            x="month",
            y="sales",
            by="region",
        )
    with pytest.raises(ValueError, match="hashable"):
        ui.BarChart([{"m": [1], "r": "a", "v": 1}], x="m", y="v", by="r")
    with pytest.raises(ValueError, match="inside a list"):
        ui.BarChart(WIDE, x="month", y=("sales", "Sales"))
    # Database rows carry Decimals; they must stay numbers on the wire.
    chart = ui.LineChart([{"m": "a", "v": Decimal("1.5")}], x="m", y="v")
    assert chart.points() == [{"x": "a", "v": 1.5}]

    class Row(BaseModel):
        m: str
        v: Decimal

    assert ui.LineChart([Row(m="a", v=Decimal("2"))], x="m", y="v").points() == [
        {"x": "a", "v": 2.0}
    ]


def test_a_diverging_chart_takes_counts_only() -> None:
    with pytest.raises(ValueError, match="negative"):
        ui.BarChart([{"m": "a", "lo": -1, "hi": 2}], x="m", y=["lo", "hi"], diverging=True)


def test_a_pie_takes_one_slice_per_row_and_folds_the_rest() -> None:
    rows = [
        {"channel": "Direct", "visits": 120},
        {"channel": "Search", "visits": 410},
        {"channel": "Social", "visits": 230},
        {"channel": "Mail", "visits": 40},
        {"channel": "Ads", "visits": 90},
        {"channel": "Partners", "visits": 30},
        {"channel": "Print", "visits": None},
    ]
    props = (
        build(ui.PieChart(rows, x="channel", y="visits", on_click=lambda s, p: None))
        .nodes["root"]
        .props
    )
    assert "rows" not in props and "y" not in props and "other" not in props
    assert [s["x"] for s in props["data"]] == ["Direct", "Search", "Social", "Ads", "Other"]
    assert props["data"][-1] == {"x": "Other", "value": 70, "other": True}
    assert props["on_click"] is True and props["donut"] is False
    five = ui.PieChart(rows[:5], x="channel", y="visits")
    assert [s["other"] for s in five.slices()] == [False] * 5
    with pytest.raises(ValueError, match="at most"):
        ui.PieChart(rows, x="channel", y="visits", other=None)
    with pytest.raises(ValueError, match="negative"):
        ui.PieChart([{"c": "a", "v": -1}], x="c", y="v")
    with pytest.raises(ValueError, match="is a number"):
        ui.PieChart([{"c": "a", "v": "lots"}], x="c", y="v")
    with pytest.raises(ValueError, match="no column 'nope'"):
        ui.PieChart(rows, x="channel", y="nope")
    with pytest.raises(ValueError, match="different columns"):
        ui.PieChart(rows, x="visits", y="visits")
    assert build(ui.PieChart(x="c", y="v")).nodes["root"].props["data"] == []
