---
title: Inputs
order: 2
description: Every control, which side owns its value, and how changes reach Python.
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
    st = s.state.owner
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
submits the Form with that key from anywhere on the page. With `href` the
button goes somewhere instead of calling a handler. A page of the app
opens on the session like a `ui.Link` does, any other address is the
browser's, and `target="_blank"` opens a new tab. Such a button is a real
link, so a middle click opens it in a new tab. An `icon` is one
of lucide's names, the set in `mw.ICONS`, and a name outside it is refused
when the component is made, with the closest names in the error. It can
also be a file of the app's own, as [Icon](/components/text#icon)
describes.

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
    ui.Row(
        ui.Button("To the Layout page", href="/components/layout", icon="arrow-right", icon_position="end"),
        ui.Button("Print this page", icon="printer", variant="outline", on_click=lambda s, _: s.print()),
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
clear button. A password has a button that shows what was typed, as does
a password field in a form and on the sign-in page. `on_change` fires after a pause in typing, set by
`debounce_ms` and 250 ms by default, and `on_submit` fires on Enter.

What is typed reaches the server before anything else the tab sends, so
a button pressed right after typing finds the text in state. The page
is only drawn again after that, though. A button whose `disabled` is
worked out from the typed text is therefore still disabled at a press
that comes within the pause, and the press does nothing. A send button
stays enabled and its handler checks the text.

`clear_on_submit=True` empties the field at the Enter, in the browser,
ready for the next entry: a line for a list, a code from a scanner, a
message. The handler gets the text and has nothing to clear, and the
keyboard stays in the field. A handler that empties a value it holds, or
calls `s.reset`, does so a round trip later, and what was typed in that
time goes with it. A `Textarea` takes the same at Ctrl+Enter.

```python live
from pydantic import BaseModel


class Lines(BaseModel):
    taken: list[str] = []


def take(s, text):
    if text:
        s.state.lines.taken.append(text)


def example(s):
    taken = s.state.lines.taken
    return ui.Stack(
        ui.Input(placeholder="A line, then Enter", clear_on_submit=True, on_submit=take),
        ui.Text(", ".join(taken[-6:]) or "Nothing yet.", variant="muted"),
        gap=2,
    )
```

`autofocus=True` puts the keyboard in a field whenever the field is put
on the page: when the page opens, after a reload, in a dialog as it opens.
An `Input`, a `Textarea` and a `NumberInput` take it. `s.focus(key)` moves
the keyboard from a handler, into a field or into the first thing that
takes it inside any other component. It happens once the page has been
drawn again, so a handler can open a dialog and name a field in it, and
one that calls `s.navigate` first names a field of the page it goes to.
A field of a `ui.Form` is named by the form's key, a slash and the
field's name, as `s.focus("order/amount")`.

```python live
def example(s):
    return ui.Row(
        ui.Input(key="code-field", placeholder="A code"),
        ui.Button("Put the keyboard there", variant="outline", on_click=lambda s, _: s.focus("code-field")),
        gap=3,
    )
```

`max_length` caps what the field takes, and `counter=True` shows under the
field how much it holds, against the limit when there is one. The count
takes the destructive color once the field is full. A field of the kind
`number` is the exception, since a browser puts no limit on its length.
The count makes the field taller, so in a `ui.Row` what stands next to it
is centered on the two together, and `align="start"` on the row lines
them up at the top.

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
    ui.Input(placeholder="A short title", max_length=20, counter=True),
    ui.Input(value="Read only", readonly=True),
    ui.Input(value="Disabled", disabled=True),
    gap=3,
)
```

## Textarea

`ui.Textarea` is several lines. `rows` sets the starting height,
`autosize` grows it with the text, up to most of the window, and
`max_length` caps it and `counter=True` shows the count under it, as on
an `Input`. The count is the browser's own, the one `max_length` stops at,
in which most emoji are two characters. Ctrl+Enter submits.

The browser checks the spelling of a text field until it holds more than
5,000 characters, where checking would slow a paste down. `spellcheck`
says it outright, on a `Textarea` and on an `Input`. `False` is for text
that is not prose, such as code, an id or a list of names. `True` keeps
the checking on however long the text gets.

```python live
ui.Textarea(
    placeholder="Notes. Ctrl+Enter submits.",
    rows=3,
    autosize=True,
    max_length=200,
    counter=True,
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
pairs, or `ui.Option` objects with an `icon`, `disabled` and a `group`.
`clearable` allows no choice.

An option's `icon` stands in front of its label wherever options are
listed, here and in a Combobox, a MultiSelect and the three groups below,
and in the closed field for the one that was chosen. It is a name from
the bundle or a file of the app's own, as [Icon](/components/text#icon)
describes.

```python live
ui.Row(
    ui.Select(options=["Fast", "Balanced", "Thorough"], default="Balanced"),
    ui.Select(
        options=[
            ui.Option(value="open", label="Open", icon="clock"),
            ui.Option(value="done", label="Done", icon="check"),
            ui.Option(value="kept", label="Archived", icon="archive"),
        ],
        default="done",
    ),
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
session's socket, without a render. `allow_custom=True` adds a last row
that takes the text as typed, so the value can be something that is no
option.

With `options`, the first match is lit while typing, and Enter takes the
row that is lit. That is the typed text when nothing else matches, or
after moving down to its row. With `on_search` the list is Python's answer
to an earlier keystroke, so no row is lit until one is moved to, and
Enter then takes the text as typed when `allow_custom` is set. With
`allow_custom`, text that is typed and then left is taken as the value
too.

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
Typing narrows the list to what can still be added, with the first match
lit, so Enter adds it. Enter with text in the field never submits a form
the field is in. The whole list, with what is chosen ticked, shows while
nothing is typed.

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
    s.state.pipeline.steps = steps


def example(s):
    st = s.state.pipeline
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
A radio and a checkbox show an option's `description` under its label.
Pressing the pressed button of a `ToggleGroup` lets it go, and
`on_change` then gets `None`, or the list without it with `multiple`.

```python live
ui.Stack(
    ui.RadioGroup(options=["Small", "Medium", "Large"], default="Medium", orientation="horizontal"),
    ui.CheckboxGroup(
        options=[
            ui.Option(value="a", label="Alerts", icon="bell", description="Only the important ones"),
            ui.Option(value="d", label="Digest", icon="mail"),
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
receives the chosen id. `confirm="..."` on an item asks before its handler
runs, in the dialog's destructive style when the item is destructive. The
look alone asks nothing, since only the app knows whether an action can be
undone. The same holds for a table's `row_actions` and a file card's
`actions`. The menu is at least as wide as its trigger and grows to fit
its longest item.

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
