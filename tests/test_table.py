from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.nodes import build


class Q(BaseModel):
    id: int
    name: str
    type: str


def test_table_wire_shape() -> None:
    rows = [Q(id=1, name="q1", type="radiogroup"), Q(id=2, name="q2", type="unknown")]
    t = ui.Table(
        rows=rows,
        columns=["name", ui.Column(key="type", header="Type", format="badge")],
        tones=lambda q: "destructive" if q.type == "unknown" else None,
        selection="row",
        selected=[2],
        on_select=lambda s, keys: None,
    )
    node = build(t).nodes["root"]
    assert "tones" not in node.props and "rows" in node.props
    assert node.props["keys"] == [1, 2]
    assert node.props["columns"][1] == {
        "key": "type",
        "header": "Type",
        "width": None,
        "align": "left",
        "format": "badge",
        "sortable": True,
        "filterable": True,
        "hidden": False,
        "wrap": False,
    }
    assert node.props["tone_rows"] == [None, "destructive"]
    assert node.props["selected"] == [2] and node.props["on_select"] is True


def test_a_model_row_is_what_the_model_dumps_and_other_rows_are_refused() -> None:
    import dataclasses
    import datetime as dt
    import types

    import pytest
    from pydantic import ConfigDict, Field

    class Sale(BaseModel):
        id: int
        when: dt.date
        amount: float = Field(alias="total")

    class ByAlias(Sale):
        model_config = ConfigDict(serialize_by_alias=True)

    @dataclasses.dataclass
    class Point:
        id: int
        when: dt.date

    sale = Sale(id=1, when=dt.date(2026, 1, 2), total=9.5)
    rows = [
        sale,
        {"id": 2, 7: dt.date(2026, 1, 3)},
        types.MappingProxyType({"id": 3, "when": dt.date(2026, 1, 4)}),
        Point(id=4, when=dt.date(2026, 1, 5)),
    ]
    props = build(ui.Table(rows=rows)).nodes["root"].props
    assert props["rows"] == [
        sale.model_dump(mode="json"),
        {"id": 2, "7": "2026-01-03"},
        {"id": 3, "when": "2026-01-04"},
        {"id": 4, "when": "2026-01-05"},
    ]
    assert props["keys"] == [1, 2, 3, 4]
    assert props["tone_rows"] == [] and props["tone_cells"] == []
    # A table of models alone is their dumps, under the names each model dumps by.
    aliased = ByAlias(id=5, when=dt.date(2026, 1, 6), total=1.0)
    props = build(ui.Table(rows=[sale, aliased])).nodes["root"].props
    assert props["rows"] == [sale.model_dump(mode="json"), aliased.model_dump(mode="json")]
    assert "amount" in props["rows"][0] and "total" in props["rows"][1]
    for bad in ([1, 2], object()):
        with pytest.raises(TypeError, match="a table row is a mapping, a model or a dataclass"):
            build(ui.Table(rows=[bad]))


async def test_a_changed_row_is_the_only_row_sent(tmp_path) -> None:
    from millwork.protocol import Patch
    from millwork.testing import TestApp

    class Rows(BaseModel):
        rows: list[dict] = [{"id": i, "n": i} for i in range(500)]

    app = mw.App("t", state=Rows, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[Rows]) -> ui.Component:
        return ui.Page(
            ui.Table(
                rows=s.state.rows,
                tones={"n": lambda row, v: "warning" if v < 0 else None},
                key="t",
            ),
            ui.Button("change", key="change", on_click=change),
            ui.Button("add", key="add", on_click=add),
        )

    def change(s: mw.Session[Rows], _: object) -> None:
        s.state.rows[7]["n"] = -1

    def add(s: mw.Session[Rows], _: object) -> None:
        s.state.rows.insert(0, {"id": 500, "n": 0})

    async with TestApp(app).open("/") as page:

        async def ops_of(button: str) -> dict[str, list]:
            await page.click(button)
            patch = page.messages[-1]
            assert isinstance(patch, Patch)
            return {op.prop: op.edits for op in patch.ops}  # type: ignore[union-attr]

        # One row and its tone, where the whole table and every tone used to go.
        assert await ops_of("change") == {
            "rows": [(7, 1, [{"id": 7, "n": -1}])],
            "tone_cells": [(7, 1, [{"n": "warning"}])],
        }
        # A row put in front moves the rest along: its key and its tone go with it.
        # The tone list grows by one empty place, wherever among the empty ones.
        assert await ops_of("add") == {
            "rows": [(0, 0, [{"id": 500, "n": 0}])],
            "keys": [(0, 0, [500])],
            "tone_cells": [(7, 0, [None])],
        }
        props = page.find("t").props
        assert props["rows"][8] == {"id": 7, "n": -1} and props["tone_cells"][8] == {"n": "warning"}


def test_table_cell_tones_and_default_columns() -> None:
    t = ui.Table(
        rows=[{"id": "a", "n": 3}, {"id": "b", "n": -1}],
        tones={"n": lambda row, v: "warning" if v < 0 else None},
    )
    props = build(t).nodes["root"].props
    assert [c["key"] for c in props["columns"]] == ["id", "n"]
    # A column is headed by its key in plain words until it is given a header.
    headed = build(ui.Table(rows=[], columns=["first_name", ui.Column(key="n", header="Count")]))
    assert [c["header"] for c in headed.nodes["root"].props["columns"]] == ["First name", "Count"]
    assert props["tone_cells"] == [None, {"n": "warning"}]


def test_rows_of_any_shape_become_json() -> None:
    import datetime as dt
    import enum
    import json
    from decimal import Decimal

    import pytest

    class Kind(enum.Enum):
        A = "a"

    rows = [
        {"id": 1, "when": dt.date(2026, 1, 2), "amount": Decimal("1.50"), "kind": Kind.A},
        Q(id=2, name="q", type="t"),
    ]
    props = build(ui.Table(rows=rows, default_sort=[("id", "desc")])).nodes["root"].props
    json.dumps(props)
    assert props["rows"][0] == {"id": 1, "when": "2026-01-02", "amount": "1.50", "kind": "a"}
    # Columns follow the first row.
    assert [c["key"] for c in props["columns"]] == ["id", "when", "amount", "kind"]
    assert props["keys"] == [1, 2]
    assert props["default_sort"] == [["id", "desc"]]
    assert build(ui.Table()).nodes["root"].props["columns"] == []
    # Keys come from ``row_key``; without that column every row keys by its index,
    # and a table where only some rows have it is refused rather than mis-keyed.
    props = build(ui.Table(rows=[Q(id=9, name="a", type="t")], row_key="name")).nodes["root"].props
    assert props["keys"] == ["a"]
    assert build(ui.Table(rows=[{"n": 1}, {"n": 2}])).nodes["root"].props["keys"] == [0, 1]
    with pytest.raises(ValueError, match="row 1 has no 'id'"):
        build(ui.Table(rows=[{"id": 1}, {"n": "no key"}]))

    assert (
        build(ui.Table(columns=[{"key": "n", "format": "number"}]))
        .nodes["root"]
        .props["columns"][0]["format"]
        == "number"
    )
    with pytest.raises(TypeError):
        ui.Table(columns=[1])
    with pytest.raises(TypeError):
        build(ui.Table(rows=[("a", 1)]))
    with pytest.raises(ValueError):
        ui.Column(key="k", format="emoji")
    # A tone function sees a missing column as None and may answer nothing.
    props = (
        build(
            ui.Table(
                rows=[{"id": 1}, {"id": 2, "n": 5}],
                tones={"n": lambda row, v: "muted" if v is None else None},
            )
        )
        .nodes["root"]
        .props
    )
    assert props["tone_cells"] == [{"n": "muted"}, None] and props["tone_rows"] == []


async def test_table_events_reach_handlers_as_sent(tmp_path) -> None:
    from typing import Any

    from millwork.testing import TestApp

    seen: list[Any] = []
    app = mw.App("tb", public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Table(
                rows=[{"id": "a"}, {"id": "b"}],
                key="t",
                selection="rows",
                row_actions=[
                    ui.MenuItem(id="open", label="Open"),
                    ui.MenuItem(id="rm", label="Remove", destructive=True, confirm="Remove?"),
                ],
                on_select=lambda s, keys: seen.append(("select", keys)),
                on_row_click=lambda s, key: seen.append(("row", key)),
                on_action=lambda s, p: seen.append(("action", p)),
                on_sort=lambda s, p: seen.append(("sort", p)),
                on_filter=lambda s, p: seen.append(("filter", p)),
            )
        )

    async with TestApp(app).open("/") as page:
        t = page.find("t")
        await page.select(t, ["b", "zzz"])  # keys are the tab's claim; the handler decides
        await page.event(t, "row_click", "a")
        await page.action(t, "open", "a")
        await page.event(t, "sort", [["id", "asc"]])
        await page.event(t, "filter", {"columns": {"id": "a"}, "search": ""})
        # An action with a confirm asks first; cancelling keeps it from the handler.
        await page.action(t, "rm", "b")
        assert page.find(ui.Dialog).props["title"] == "Remove?"
        await page.answer(False)
        assert seen == [
            ("select", ["b", "zzz"]),
            ("row", "a"),
            ("action", ["open", "a"]),
            ("sort", [["id", "asc"]]),
            ("filter", {"columns": {"id": "a"}, "search": ""}),
        ]
        await page.action(t, "rm", "b")
        await page.answer(True)
        assert seen[-1] == ("action", ["rm", "b"])
