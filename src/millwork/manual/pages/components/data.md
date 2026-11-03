---
title: Data
order: 4
---

# Data

`ui.Table` shows rows, which can be dicts, Pydantic models or
dataclasses. Columns come from the rows unless `columns` names them, each
with a `header`, a `format`, a `width`, an `align`, and whether it is
`sortable` or `filterable`.

## A plain table

Sorting is on by default and happens in the browser. `row_key` names the
field that identifies a row, `id` unless told otherwise.

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

## Search, filters and pages

`search=True` adds a box that matches any column. `filters=True` adds a
filter row whose kind follows each column's values, and `page_size` pages
the rows. `summary` is the count line under the table, or custom text.

```python live
ui.Table(rows=ROWS, search=True, filters=True, page_size=3, summary="People in the pilot")
```

## Selection and row actions

`selection="row"` or `"rows"` lets the user pick, and `on_select`
receives the keys. `row_actions` adds a menu per row, and `on_action`
receives `(action id, row key)`. `on_row_click` receives the key of the
clicked row.

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

## Tones

`tones` colors rows. It is a function of the row returning a tone, or a
mapping from column key to a function of the row and the cell. A row's
tone tints the row, and a cell's tone colors the cell's text, or the
badge when the column is one.

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

## Empty

`empty` is the text shown when there are no rows.

```python live
ui.Table(rows=[], columns=[ui.Column(key="name"), ui.Column(key="role")], empty="No people match.")
```
