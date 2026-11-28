---
title: Data
order: 4
description: Tables with sorting, filtering, selection and actions, and stats.
---

# Data
<!-- keywords: table, grid, datatable, dataframe, pandas, rows -->

`ui.Table` shows rows, which can be dicts, Pydantic models or
dataclasses. Columns come from the rows unless `columns` names them, each
with a `header`, a `format`, a `width`, an `align`, and whether it is
`sortable` or `filterable`. A column without a `header` is headed by its
key exactly as written, which keeps the names of data the app did not
make, an upload for one, as they are. A `width` is a number of pixels or
a length as CSS writes one, such as `"20rem"`. It is what the column
asks for, and a table that is short of room gives it less.

## A plain table

Sorting is on by default and happens in the browser. `row_key` names the
field that identifies a row, `id` unless told otherwise. A table that
selects, opens or acts on a row, or is given `selected`, needs values
there that tell its rows apart. Rows that share a value or have none
make the page fail with an error that names them, since a handler would
get one key for two rows. A table that only shows its rows goes by their
position when the field does not tell them apart, as the rows of a
query's result may not.

```python live
ROWS = [
    {"id": 1, "name": "Ada", "role": "Engineer", "score": 0.92, "joined": "2024-03-01", "active": True},
    {"id": 2, "name": "Grace", "role": "Admiral", "score": 0.88, "joined": "2023-11-15", "active": True},
    {"id": 3, "name": "Edsger", "role": "Professor", "score": 0.75, "joined": "2022-06-30", "active": False},
    {"id": 4, "name": "Barbara", "role": "Architect", "score": 0.81, "joined": "2024-08-12", "active": True},
]

ui.Table(rows=ROWS)
```

## Columns and formats
<!-- keywords: currency, number format, date format, column header, grouped headers, column groups, spanning header, multi-level header -->

`format` renders a value as `text`, `number`, `integer`, `percent`,
`currency`, `date`, `datetime`, `bool`, `badge`, `link` or `code`.
Numbers and dates follow the theme's `locale`, and `currency` uses the
theme's `currency`, euros unless the theme names another.

```python live
ui.Table(
    rows=ROWS,
    columns=[
        ui.Column(key="name", header="Name"),
        ui.Column(key="role", header="Role", format="badge"),
        ui.Column(key="score", header="Score", format="percent", align="right"),
        ui.Column(key="joined", header="Joined", format="date"),
        ui.Column(key="active", header="Active", format="bool", align="center"),
    ],
    default_sort=[("score", "desc")],
)
```

A `group` puts one heading over columns that stand next to each other,
such as a year over its quarters. Columns with the same `group` share
the heading, and a column without one stands on its own. The columns
under a heading sort and filter like any other.

```python live
SALES = [
    {"region": "North", "q3": 120, "q4": 140, "q1": 150, "q2": 170, "growth": 0.04},
    {"region": "South", "q3": 127, "q4": 145, "q1": 153, "q2": 172, "growth": 0.05},
    {"region": "East", "q3": 134, "q4": 150, "q1": 156, "q2": 174, "growth": 0.06},
    {"region": "West", "q3": 141, "q4": 155, "q1": 159, "q2": 176, "growth": 0.07},
]

ui.Table(
    rows=SALES,
    row_key="region",
    columns=[
        ui.Column(key="region", header="Region"),
        ui.Column(key="q3", header="Q3", group="2023", align="right"),
        ui.Column(key="q4", header="Q4", group="2023", align="right"),
        ui.Column(key="q1", header="Q1", group="2024", align="right"),
        ui.Column(key="q2", header="Q2", group="2024", align="right"),
        ui.Column(key="growth", header="Growth", format="percent", align="right"),
    ],
)
```

## Search, filters and pages
<!-- keywords: pagination, paging, filter, sort, search -->

`search=True` adds a box that matches any column. `filters=True` adds a
filter row whose kind follows each column's values, and `page_size` pages
the rows. `summary` is the count line under the table, or custom text.

```python live
ui.Table(rows=ROWS, search=True, filters=True, page_size=3, summary="People in the pilot")
```

## Selection and row actions
<!-- keywords: select rows, bulk actions, click a row, checkbox -->

`selection="row"` or `"rows"` lets the user pick, and `on_select`
receives the keys. `row_actions` adds a menu per row, and `on_action`
receives `(action id, row key)`. `on_row_click` receives the key of the
clicked row.

A table whose rows can be pressed takes the keyboard as well. Tab stops
at one of its rows, the arrow keys, Home and End move between the rows
of the page, and Enter or Space presses the row.

With `"rows"`, a press on a checkbox with shift held sets every row from
the last checkbox used to that one to the same state, selected or
cleared, in the order the table shows them.

```python live
from pydantic import BaseModel


class Selection(BaseModel):
    keys: list = []
    last: str = ""


def example(s):
    st = s.state.selection
    return ui.Stack(
        ui.Table(
            rows=ROWS,
            columns=[ui.Column(key="name"), ui.Column(key="role")],
            selection="rows",
            selected=st.keys,
            on_select=lambda s, keys: setattr(st, "keys", keys),
            row_actions=[
                ui.MenuItem(id="edit", label="Edit", icon="pencil"),
                ui.MenuItem(id="remove", label="Remove", icon="trash-2", destructive=True),
            ],
            on_action=lambda s, a: setattr(st, "last", f"{a[0]} on row {a[1]}"),
            on_row_click=lambda s, key: setattr(st, "last", f"clicked row {key}"),
        ),
        ui.Text(f"Selected: {st.keys}. Last: {st.last or 'nothing'}", variant="muted"),
        gap=3,
    )
```

## Rows that are dragged
<!-- keywords: reorder rows, drag and drop, sortable rows, row order, grip, on_move, RowMove -->

`on_move` gives each row a grip to drag it into another order by. Alt
with an arrow key on the grip moves the row a place at a time. The
handler gets a `ui.RowMove` with the row's `key` and the place it was
moved `to`, counted from 0, and changes the rows. The table drawn from
them is where the row ends up, so a handler that leaves the rows as
they were sends the row back.

```python live
from pydantic import BaseModel


class Stage(BaseModel):
    name: str
    hours: float


class Route(BaseModel):
    stages: list[Stage] = [
        Stage(name="Trailhead to the ford", hours=2.5),
        Stage(name="Ford to the saddle", hours=3.0),
        Stage(name="Saddle to the hut", hours=1.5),
        Stage(name="Hut to the summit", hours=4.0),
        Stage(name="Summit to the road", hours=3.5),
    ]


def example(s):
    stages = s.state.route.stages

    def move(s, moved):
        at = next(i for i, stage in enumerate(stages) if stage.name == moved.key)
        stages.insert(moved.to, stages.pop(at))

    return ui.Table(
        rows=stages,
        row_key="name",
        columns=[
            ui.Column(key="name", header="Stage"),
            ui.Column(key="hours", header="Hours", format="number", align="right"),
        ],
        on_move=move,
    )
```

Such a table shows its rows in the order they have. So it is not sorted
by a column, and `on_move` does not go with `filters`, `search`,
`page_size` or `default_sort`. Every row has a key that tells it from
the others, and there are at most two hundred rows. Selection works
beside it. A range picked with shift goes by the order the rows are
shown in, and a selected row that is dragged moves alone.

## Cells that are typed over
<!-- keywords: editable cell, edit in place, inline edit, spreadsheet, grid, data entry, on_edit, CellEdit, editable column -->

`editable=True` on a column lets its cells be typed over where they
stand, in a table that has `on_edit`. A press on such a cell opens it as
a field. The handler gets a `ui.CellEdit` with the row's `key`, the
`column` and the `value`, and changes the row. The table drawn from the
rows is what the cell shows, so a handler that leaves the row as it was
sends the cell back.

```python live
from pydantic import BaseModel


class Leg(BaseModel):
    id: int
    name: str
    hours: float
    shade: float
    open: bool


class Hike(BaseModel):
    legs: list[Leg] = [
        Leg(id=1, name="Trailhead to the ford", hours=2.5, shade=0.6, open=True),
        Leg(id=2, name="Ford to the saddle", hours=3.0, shade=0.25, open=True),
        Leg(id=3, name="Saddle to the hut", hours=1.5, shade=0.1, open=False),
        Leg(id=4, name="Hut to the summit", hours=4.0, shade=0.0, open=True),
    ]


def example(s):
    legs = s.state.hike.legs

    def edit(s, typed):
        leg = next(leg for leg in legs if leg.id == typed.key)
        if typed.value in ("", None):
            s.toast("Every cell of a leg has something in it.", tone="warning")
            return
        if typed.column == "hours" and not 0 < typed.value <= 24:
            s.toast("A leg takes up to a day.", tone="warning")
            return
        setattr(leg, typed.column, typed.value)

    return ui.Table(
        rows=legs,
        columns=[
            ui.Column(key="name", header="Leg", editable=True),
            ui.Column(key="hours", header="Hours", format="number", align="right", editable=True),
            ui.Column(key="shade", header="In shade", format="percent", align="right", editable=True),
            ui.Column(key="open", header="Open", format="bool", align="center", editable=True),
        ],
        sortable=False,
        on_edit=edit,
    )
```

The value comes in the column's own type. A text is a `str`, a `number`
or a `currency` a `float`, an `integer` an `int`, and a `bool` a yes or
no that is set where it stands, without a field. A number is typed the
way the theme's `locale` writes one, and a `percent` as the number that
is shown, so 25 is typed for the 0.25 the row holds. A number that is
emptied is `None`. What is no number, or no whole one in a column of
integers, keeps its field open for as long as the keyboard is in it. A
field that is opened and left as it was says nothing.

The keyboard works the cells as well. Tab stops at one of them, and the
arrow keys go between the cells that are typed over. Enter, F2 or simply
typing opens a cell. In the field Enter says the value and goes down,
Tab says it and goes on to the next cell, and Escape leaves the cell as
it was. Tab goes on from a yes or no as well, so a row can be filled in
with Tab alone.

Each row has a key that tells it from the others, and a cell that is
typed over is one line. A press on a cell opens it, so `on_edit` does
not go with `on_row_click` or `selection="row"`, where a press is on the
row. It goes with checkboxes and with rows that are dragged. A row in a
column the table is sorted by takes its new place as soon as its value
changes. Without `on_edit` the columns are shown as any other, so a
page that lets only some people type leaves the handler out for the
rest.

## Tones

`tones` colors rows. It is a function of the row returning a tone, or a
mapping from column key to a function of the row and the cell, called as
`fn(row, value)`. The row is the one given in `rows`, so a model is still
a model there. The value is the cell as it goes to the tab, before the
column's `format`. A number is a number, a date is its ISO text, a
`Decimal` is its text and an `Enum` its value, and the row has each as it
was given. Returning `None` leaves the row or cell as it is, and
anything that is no tone is refused. A row's tone tints the row, and a
cell's tone colors the cell's text, or the badge when the column is one.
On a badge `muted` and `accent` look like no tone at all.

```python live
ui.Table(
    rows=ROWS,
    columns=[ui.Column(key="name"), ui.Column(key="score", format="percent")],
    tones=lambda r: "success" if r["score"] > 0.85 else ("warning" if r["score"] < 0.8 else None),
)
```

```python live
ui.Table(
    rows=ROWS,
    columns=[
        ui.Column(key="name"),
        ui.Column(key="role", format="badge"),
        ui.Column(key="score", format="percent"),
    ],
    tones={
        "score": lambda r, v: "success" if v > 0.85 else ("destructive" if v < 0.8 else None),
        "role": lambda r, v: "warning" if not r["active"] else None,
    },
)
```

## Long tables
<!-- keywords: virtual scroll, performance, many rows -->

Every row is in the browser, and a table of thousands stays quick.
`height` gives the table a box of its own to scroll in, with the header
staying at its top. A table longer than two hundred rows draws the rows
in view and a margin around them, so the page holds a few hundred cells
however long the table is. The browser's own find then sees the rows
that are drawn, which is what `search=True` is for. A change to the rows
sends the rows that changed and draws those again, so a task can add to
a long table as it runs.

`fill=True` takes the place of a `height` on
[a page that fills the window](/components/layout#a-page-that-fills-the-window).
The table then takes the room that is left, and its rows scroll inside
it.

```python live
LONG = [{"id": i, "customer": f"Customer {i}", "amount": 12.5 * i} for i in range(1, 2001)]

ui.Table(
    rows=LONG,
    columns=[
        ui.Column(key="id"),
        ui.Column(key="customer"),
        ui.Column(key="amount", format="currency", align="right"),
    ],
    height=320,
)
```

## Long text
<!-- keywords: truncate, ellipsis, clamp, overflow, wrap, long cell, remaining width -->

A cell is one line, and a long text widens its column until the table
scrolls sideways. `wrap=True` on a column lets the text wrap instead.
`lines` cuts a cell to that many lines, with three dots where it ends.
The whole text shows under the pointer, and `search=True` reads all of
it. A column with `lines` and no `width` takes the width the other
columns leave, and two such columns share it.

```python live
NOTES = [
    {"id": 1, "by": "Ada", "note": "The path along the river is closed past the second bridge until the bank is mended, so the loop takes the road for a mile."},
    {"id": 2, "by": "Grace", "note": "Open."},
    {"id": 3, "by": "Edsger", "note": "The hut at the top has water again, but the stove is out and the shutters on the north side do not close."},
]

ui.Table(
    rows=NOTES,
    columns=[
        ui.Column(key="id", width=60),
        ui.Column(key="by", header="By"),
        ui.Column(key="note", header="Note", lines=1),
    ],
)
```

## Empty

`empty` is the text shown when there are no rows.

```python live
ui.Table(rows=[], columns=[ui.Column(key="name"), ui.Column(key="role")], empty="No people match.")
```
