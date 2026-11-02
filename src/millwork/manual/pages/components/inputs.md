---
title: Inputs
order: 2
---

# Inputs

Controls the user types into or picks from. Each one tells Python what
happened through an `on_change` handler, and most can be owned by either side.

## Who owns the value

A control with `default=` keeps its own value in the browser and reports
changes. A control with `value=` shows what Python says and only changes
when Python changes it. Give one or the other. Pass `value` when the page
needs to read or reset the control, and `default` when it does not.

```python live
from pydantic import BaseModel


class Owner(BaseModel):
    text: str = ""


def example(s):
    st = state(Owner)
    return ui.Stack(
        ui.Input(
            value=st.text,
            placeholder="Python owns this one",
            on_change=lambda s, v: setattr(st, "text", v),
        ),
        ui.Row(
            ui.Text(f"Python sees: {st.text!r}", variant="muted"),
            ui.Button(
                "Clear from Python",
                size="sm",
                variant="outline",
                on_click=lambda s, _: setattr(st, "text", ""),
            ),
            gap=3,
        ),
        ui.Input(
            default="The browser owns this one", on_change=lambda s, v: s.toast(f"Changed to {v!r}")
        ),
        gap=3,
    )
```

## Button

`ui.Button` takes a label, a `variant`, a `size`, an `icon` before the
label or after it with `icon_position="end"`, `loading`, `disabled` and a
`tooltip`. `confirm="..."` asks before the handler runs. `form="key"`
submits the Form with that key from anywhere on the page. An `icon` is one
of lucide's names, the set in `mw.ICONS`, and a name outside it is refused
when the component is made, with the closest names in the error.

```python live
ui.Stack(
    ui.Row(
        ui.Button("Primary"),
        ui.Button("Secondary", variant="secondary"),
        ui.Button("Outline", variant="outline"),
        ui.Button("Ghost", variant="ghost"),
        ui.Button("Link", variant="link"),
        ui.Button("Destructive", variant="destructive"),
        gap=2,
        wrap=True,
    ),
    ui.Row(
        ui.Button("Small", size="sm", variant="outline"),
        ui.Button("Medium", variant="outline"),
        ui.Button("Large", size="lg", variant="outline"),
        ui.Button("With icon", icon="download", variant="outline"),
        ui.Button("Icon after", icon="arrow-right", icon_position="end", variant="outline"),
        gap=2,
        wrap=True,
    ),
    ui.Row(
        ui.Button("Loading", loading=True),
        ui.Button("Disabled", disabled=True),
        ui.Button("With tooltip", tooltip="Explains itself on hover", variant="outline"),
        ui.Button(
            "Delete",
            variant="destructive",
            confirm="Delete this for good?",
            on_click=lambda s, _: s.toast("Deleted.", tone="destructive"),
        ),
        gap=2,
        wrap=True,
    ),
    gap=3,
)
```

## ButtonGroup

`ui.ButtonGroup` joins buttons into one control.

```python live
ui.ButtonGroup(
    ui.Button("Day", variant="outline", on_click=lambda s, _: s.toast("Day")),
    ui.Button("Week", variant="outline", on_click=lambda s, _: s.toast("Week")),
    ui.Button("Month", variant="outline", on_click=lambda s, _: s.toast("Month")),
)
```

## Input

`ui.Input` is a single line of text. `kind` chooses the keyboard and the
validation, from `text`, `password`, `email`, `number`, `search` and
`url`. `prefix_icon` and `suffix` decorate it, and `clearable` adds a
clear button. `on_change` fires after a pause in typing, set by
`debounce_ms` and 250 ms by default, and `on_submit` fires on Enter.

```python live
ui.Stack(
    ui.Input(
        placeholder="Search",
        prefix_icon="search",
        kind="search",
        clearable=True,
        on_submit=lambda s, v: s.toast(f"Searching for {v!r}"),
    ),
    ui.Input(placeholder="Distance", suffix="km", kind="number"),
    ui.Input(placeholder="Password", kind="password"),
    ui.Input(value="Read only", readonly=True),
    ui.Input(value="Disabled", disabled=True),
    gap=3,
)
```

## Textarea

`ui.Textarea` is several lines. `rows` sets the starting height,
`autosize` grows it with the text, and `max_length` caps it. Ctrl+Enter
submits.

```python live
ui.Textarea(
    placeholder="Notes. Ctrl+Enter submits.",
    rows=3,
    autosize=True,
    max_length=200,
    on_submit=lambda s, v: s.toast(f"{len(v)} characters"),
)
```

## NumberInput

`ui.NumberInput` takes a number within `min` and `max`, stepping by `step`,
with an optional `suffix`. It reports on blur and on Enter.

```python live
ui.Row(
    ui.NumberInput(default=3, min=1, max=10, step=1, suffix="items"),
    ui.NumberInput(default=0.5, min=0, max=1, step=0.1, placeholder="0 to 1"),
    gap=4,
)
```

## Slider

`ui.Slider` picks a number by dragging. `marks` labels points under the
track, and `show_value` prints the value beside it. It reports on
release.

```python live
ui.Stack(
    ui.Slider(default=40, min=0, max=100, step=10),
    ui.Slider(default=0.3, min=0, max=1, step=0.1, marks={0: "cold", 0.5: "warm", 1: "hot"}),
    gap=6,
)
```

## Switch and Checkbox

Both are a yes or no with a `label` and an optional `description`. Use
`checked` or `default_checked`.

```python live
ui.Stack(
    ui.Switch(
        label="Email me a summary", description="Once a day, at eight.", default_checked=True
    ),
    ui.Checkbox(
        label="I have read the terms", on_change=lambda s, v: s.toast("Read" if v else "Unread")
    ),
    ui.Checkbox(label="Disabled", disabled=True),
    gap=3,
)
```

## Select

`ui.Select` picks one from `options`. Options are strings, `(value, label)`
pairs, or `ui.Option` objects with a `description`, an `icon`, `disabled` and a
`group`. `clearable` allows no choice.

```python live
ui.Row(
    ui.Select(options=["Fast", "Balanced", "Thorough"], default="Balanced"),
    ui.Select(
        options=[
            ui.Option(value="nl", label="Dutch", group="Europe"),
            ui.Option(value="de", label="German", group="Europe"),
            ui.Option(value="ja", label="Japanese", group="Asia", disabled=True),
        ],
        placeholder="Language",
        clearable=True,
    ),
    gap=4,
)
```

## Combobox

`ui.Combobox` is a Select with a search box. With `options` it filters in
the browser. With `on_search`, Python answers each search over the
session's socket, without a render. `allow_custom=True` lets typed text
that matches nothing be the value.

```python live
PEOPLE = [("ada", "Ada Lovelace"), ("grace", "Grace Hopper"), ("edsger", "Edsger Dijkstra")]


async def search(s, query: str):
    return [p for p in PEOPLE if query.lower() in p[1].lower()]


def example(s):
    return ui.Row(
        ui.Combobox(options=PEOPLE, placeholder="Filters in the browser"),
        ui.Combobox(on_search=search, placeholder="Asks Python as you type", clearable=True),
        ui.Combobox(options=["red", "green"], allow_custom=True, placeholder="Or type your own"),
        gap=4,
        wrap=True,
    )
```

## MultiSelect

`ui.MultiSelect` picks several, shown as chips. `max` stops further picks.

```python live
ui.MultiSelect(
    options=["Alpha", "Beta", "Gamma", "Delta"],
    default=["Alpha"],
    max=3,
    placeholder="Pick up to three",
)
```

The chips keep the order they were picked in, and that is the order
Python receives. `sortable=True` lets the order be changed afterwards, by
dragging a chip to its place or focusing it and pressing Alt with an arrow
key. In a form, the same hint on the field, `json_schema_extra={"sortable":
True}`, does it.

```python live
from pydantic import BaseModel


class Pipeline(BaseModel):
    steps: list[str] = ["Collect", "Clean", "Model"]


def reorder(s, steps):
    state(Pipeline).steps = steps


def example(s):
    st = state(Pipeline)
    return ui.Stack(
        ui.MultiSelect(
            options=["Collect", "Clean", "Model", "Report", "Share"],
            value=st.steps,
            sortable=True,
            on_change=reorder,
        ),
        ui.Text(" then ".join(st.steps) or "Nothing yet.", variant="muted"),
        gap=2,
    )
```

## RadioGroup, CheckboxGroup and ToggleGroup

Three ways to choose from a short list. Radios pick one, checkboxes pick
several, and pressed buttons do either, with `multiple=True` for several.

```python live
ui.Stack(
    ui.RadioGroup(options=["Small", "Medium", "Large"], default="Medium", orientation="horizontal"),
    ui.CheckboxGroup(
        options=[
            ui.Option(value="a", label="Alerts", description="Only the important ones"),
            ui.Option(value="d", label="Digest"),
        ],
        default=["a"],
    ),
    ui.ToggleGroup(
        options=[("left", "Left"), ("center", "Center"), ("right", "Right")], default="left"
    ),
    ui.ToggleGroup(
        options=["Bold", "Italic", "Underline"], multiple=True, default=["Bold"], size="sm"
    ),
    gap=4,
)
```

## DatePicker

`ui.DatePicker` picks a date from a calendar, and `range=True` picks a
span. Values are ISO strings on the wire, and `date` objects are accepted.
`min` and `max` bound the days that can be picked.

```python live
ui.Row(
    ui.DatePicker(
        placeholder="A day", clearable=True, on_change=lambda s, v: s.toast(f"Picked {v}")
    ),
    ui.DatePicker(range=True, placeholder="A span", min="2026-01-01"),
    gap=4,
    wrap=True,
)
```

## DropdownMenu

`ui.DropdownMenu` opens a menu behind a `trigger` button. Items carry an
`icon`, `disabled`, `destructive` and `separator_after`, and `on_select`
receives the chosen id. A destructive item asks before its handler runs,
with its label as the question, and `confirm="..."` on an item puts the
question in the app's own words. The same holds for a table's
`row_actions` and a file card's `actions`.

```python live
ui.DropdownMenu(
    trigger=ui.Button("Actions", icon="more-horizontal", variant="outline"),
    items=[
        ui.MenuItem(id="rename", label="Rename", icon="pencil"),
        ui.MenuItem(id="copy", label="Duplicate", icon="copy", separator_after=True),
        ui.MenuItem(id="delete", label="Delete", icon="trash-2", destructive=True),
    ],
    on_select=lambda s, item: s.toast(f"Chose {item}"),
)
```

## Field

`ui.Field` puts a `label`, `help` and an `error` around one control, for a
form built by hand rather than from a model.

```python live
from pydantic import Field

ui.Grid(
    ui.Field(ui.Input(placeholder="Ada"), label="Name", required=True, help="As on your badge."),
    ui.Field(
        ui.Input(placeholder="ada@example.com", kind="email"),
        label="Email",
        error="This address bounced.",
    ),
    cols={"sm": 1, "md": 2},
)
```
