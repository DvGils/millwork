---
title: Feedback
order: 3
description: Toasts, alerts, dialogs, confirm and ask, progress and empty states.
---

# Feedback

Telling the user what is going on, with alerts, toasts, dialogs, progress
and the empty and loading states.

## Alert
<!-- keywords: banner, callout, notice, warning -->

`ui.Alert` is a banner with a `title`, a `description`, a `tone`, an `icon`,
`actions` and, with `dismissable`, a close button that fires `on_dismiss`.
Children go under the description, for what a line of text cannot hold.

```python live
ui.Stack(
    ui.Alert(title="Heads up", description="Something to know, with the default tone."),
    ui.Alert(title="Saved", description="The project was saved.", tone="success"),
    ui.Alert(title="Check the dates", description="The end is before the start.", tone="warning"),
    ui.Alert(
        title="Upload failed",
        description="The file was larger than 50 MB.",
        tone="destructive",
        actions=[ui.Button("Try again", size="sm", on_click=lambda s, _: s.toast("Retrying"))],
    ),
    ui.Alert(
        ui.Markdown("- `orders.csv` has no header row\n- `returns.csv` is empty"),
        title="Two files were skipped",
        tone="warning",
    ),
    ui.Alert(title="Dismiss me", dismissable=True, on_dismiss=lambda s, _: s.toast("Dismissed")),
    gap=3,
)
```

## Toast
<!-- keywords: notification, snackbar, flash message -->

A toast is a command rather than a component. Call `s.toast(message,
tone=, title=)` from any handler. `action=(label, handler)` puts a button
on it that runs the handler once. A toast shows on top of an open
dialog, sheet or question, and its button can be pressed there.

```python live
ui.Row(
    ui.Button("Plain", variant="outline", on_click=lambda s, _: s.toast("A plain toast.")),
    ui.Button(
        "Success", variant="outline", on_click=lambda s, _: s.toast("Saved.", tone="success")
    ),
    ui.Button(
        "With title",
        variant="outline",
        on_click=lambda s, _: s.toast("Three rows changed.", title="Imported"),
    ),
    ui.Button(
        "With action",
        variant="outline",
        on_click=lambda s, _: s.toast(
            "Deleted.", tone="destructive", action=("Undo", lambda s, _: s.toast("Restored."))
        ),
    ),
    gap=2,
    wrap=True,
)
```

## Highlight
<!-- keywords: spotlight, tour, onboarding, coach mark, guide, walkthrough, point at -->

`s.highlight(name, color)` puts a frame around a component so the person
finds it. An assistant in the app answers a question about how something
is done with it, by pointing at where it is done. The name is a key or an
id, and `form/field` names a field of a form. A row of a table and a
value in a chart have names too, which the end of this section shows.
Unlike a toast it stays: the session holds it until the person gets to
the component. The frame lies just over its component, so a dialog or
the window of a floating assistant that covers part of the component
covers that part of the frame too.

The buttons on top set highlights on the card under them.

```python live
from pydantic import BaseModel


class Invite(BaseModel):
    name: str = ""
    email: str = ""


class Inviting(BaseModel):
    open: bool = False


def three(s, _):
    s.highlight("hl-solid", "blue")
    s.highlight("hl-pulse", "orange", style="pulse", label="New")
    s.highlight("hl-trace", "#0a7d5c", style="trace", seconds=8)


def steps(s, _):
    s.highlight("hl-invite", "blue", step=1)
    s.highlight("hl-form/email", "orange", step=2, style="trace")
    s.highlight("hl-send", "green", step=3)


def inviting(open):
    def handler(s, _):
        s.state.inviting.open = open

    return handler


def example(s):
    return ui.Stack(
        ui.Row(
            ui.Button("Show the three styles", on_click=three),
            ui.Button("Show how to invite", on_click=steps),
            ui.Button("Take them off", variant="outline", on_click=lambda s, _: s.highlight(None)),
            gap=2,
            wrap=True,
        ),
        ui.Card(
            ui.Grid(
                ui.Stat(label="Solid", value="128", hint="members", key="hl-solid"),
                ui.Stat(label="Pulse", value="12", hint="invited", key="hl-pulse"),
                ui.Stat(label="Trace", value="3", hint="teams", key="hl-trace"),
                cols={"sm": 1, "md": 3},
            ),
            title="Members",
            footer=ui.Button(
                "Invite someone", key="hl-invite", variant="outline", on_click=inviting(True)
            ),
        ),
        ui.Dialog(
            ui.Form(Invite, key="hl-form", submit=None, on_submit=inviting(False)),
            open=s.state.inviting.open,
            title="Invite someone",
            footer=ui.Button("Send", key="hl-send", form="hl-form"),
            on_close=inviting(False),
            key="hl-dialog",
        ),
        gap=4,
    )
```

The color is `red`, `orange`, `yellow`, `green`, `blue`, `pink` or
`primary`, each a color of the theme, or a hex code for a brand's own.
Without one it is blue.
`style=` is `solid`, `pulse` or `trace`, and someone who asked their
system for less motion gets `solid`. `label=` puts a short word on the
frame.

Highlights with a `step=` show one after the other, each with its number
on it. The second shows when the first is done. Using the component of a
later step ends the ones before it, so someone who opens the dialog
another way is not left with a frame on the button. Highlights without a
step show together.

A highlight goes when the person points at the component, presses it or
types in it. The keyboard that a dialog puts in its first field as it
opens does not count. `seconds=` takes it off after that long on the
screen. `s.highlight(name, None)` takes one off and `s.highlight(None)`
takes all off. Leaving the page ends its highlights, and a reload keeps
them. `page="/settings"` sets one for another page, which waits until
the person gets there. `scroll=True` brings a component that is out of
view into it.

A highlight for a component that is not on the page yet waits until it
is, and one in a closed dialog shows when the dialog opens. One that is
asked for by work that began on a page the person has left since, a
reply that took its time, is not set. A field of an item in a form's
list has no name yet. `s.outline()` says what is highlighted, so an
assistant reads its own highlights back with the page, as
[Accessing the session](/state/accessing-the-session) describes.

A highlight can be on one row of a table or on one value of a chart. The
name is the table's, a slash and the row's key, as `orders/1042`, or the
chart's, a slash and the value along its axis, as `sales/Mar`. On a chart
the frame is around what the chart draws for that value, which is the
bars, the points of the lines or the slice. A number or a text is
written as Python prints it, so `f"orders/{order.id}"` names the row. A
date or a time is written in its ISO form, as `day.isoformat()` gives
it. In a table whose rows have no `row_key` column a row goes by its
place, from 0.

```python live
HL_SALES = [
    {"month": "Jan", "sales": 82},
    {"month": "Feb", "sales": 95},
    {"month": "Mar", "sales": 41},
    {"month": "Apr", "sales": 104},
]
HL_ORDERS = [
    {"id": 1041, "customer": "Kestrel Books", "month": "Mar", "amount": 1240},
    {"id": 1042, "customer": "Alder & Sons", "month": "Mar", "amount": 380},
    {"id": 1043, "customer": "Rowan Supply", "month": "Apr", "amount": 2150},
]


def the_dip(s, _):
    s.highlight("hl-sales/Mar", "orange", label="The dip")
    s.highlight("hl-orders/1042", "orange", style="trace")


def example(s):
    return ui.Stack(
        ui.Row(
            ui.Button("Point at March", on_click=the_dip),
            ui.Button("Take them off", variant="outline", on_click=lambda s, _: s.highlight(None)),
            gap=2,
        ),
        ui.Grid(
            ui.Card(ui.BarChart(HL_SALES, x="month", y="sales", height=180, key="hl-sales")),
            ui.Card(ui.Table(rows=HL_ORDERS, summary=False, key="hl-orders")),
            cols={"sm": 1, "md": 2},
        ),
        gap=4,
    )
```

Such a highlight follows the data. It waits for a row that is not in the
table yet, goes from the screen when the row does, and with
`scroll=True` a table turns to the row's page and scrolls to it. A row
that a filter or the search box hides shows no frame. Pointing at the
row or the bar takes the highlight off, as it does on a component.

## Dialog
<!-- keywords: modal, popup, overlay, window -->

`ui.Dialog` is open when state says so. It has a `title`, a
`description`, a `footer` and a `size` from `sm` to `full`. `on_close`
fires when the user dismisses it, and the handler sets state so it
closes. A dialog is never taller than the window. The title and the
footer stay in place, and the body between them scrolls when what it
holds is taller or wider than the dialog.

With `dismissable=False` a dialog has no cross, and Escape and a click
outside do nothing. It closes by what the page puts in it, so the person
has to choose. Such a dialog lies over a floating assistant, where one
that can be dismissed lies under it.

```python live
from pydantic import BaseModel


class Modal(BaseModel):
    open: bool = False
    held: bool = False
    chose: str = ""


def example(s):
    st = s.state.modal

    def close(s, _):
        st.open = False

    def choose(what):
        def chosen(s, _):
            st.held, st.chose = False, what

        return chosen

    return ui.Row(
        ui.Button("Open a dialog", on_click=lambda s, _: setattr(st, "open", True)),
        ui.Button("Open one that stays", variant="outline", on_click=lambda s, _: setattr(st, "held", True)),
        ui.Text(st.chose, variant="muted"),
        ui.Dialog(
            ui.Text("A file with this name is already there."),
            open=st.held,
            title="Keep or replace?",
            size="sm",
            dismissable=False,
            footer=ui.Row(
                ui.Button("Keep both", variant="outline", on_click=choose("Kept both.")),
                ui.Button("Replace", on_click=choose("Replaced.")),
                gap=2,
            ),
        ),
        ui.Dialog(
            ui.Text("Dialogs hold any children. This one has a footer with a button."),
            open=st.open,
            title="A dialog",
            description="Close it with the button, the cross, Escape or a click outside.",
            footer=ui.Button("Done", on_click=close),
            on_close=close,
        ),
    )
```

## Confirm and ask
<!-- keywords: are you sure, prompt, modal question, yes or no -->

Two session calls wait for the user from inside a handler. `await s.confirm(
title, description=, destructive=)` shows a dialog and returns True or
False. `await s.ask(component)` asks with any component and returns what
it submits. A `Form` answers with its validated model, and a dialog that
is closed answers None.

The question is shown in a dialog. A `ui.Dialog` or a `ui.Sheet` given to
`s.ask` is shown as it is, with its own title and size. One with
`dismissable=False` stays until it is answered, and
`s.confirm(..., dismissable=False)` leaves its two buttons as the only
way out.

When the question closes, the keyboard goes back to the button that asked
it, so an Enter right after presses that button again. A handler that
wants it elsewhere says so after the answer, with `s.focus(key)`.

```python live
from pydantic import BaseModel, Field


class Asked(BaseModel):
    answer: str = "nothing yet"


class Rename(BaseModel):
    name: str = Field(title="New name", min_length=1)


async def confirm(s, _):
    st = s.state.asked
    ok = await s.confirm("Archive the project?", "You can restore it later.", destructive=True)
    st.answer = "archived" if ok else "kept"


async def rename(s, _):
    st = s.state.asked
    new = await s.ask(ui.Form(Rename, submit="Rename", cancel="Cancel"))
    st.answer = "left as it was" if new is None else f"renamed to {new.name}"


def example(s):
    st = s.state.asked
    return ui.Row(
        ui.Button("Archive", variant="outline", on_click=confirm),
        ui.Button("Rename", variant="outline", on_click=rename),
        ui.Text(f"Result: {st.answer}", variant="muted"),
        gap=3,
    )
```

## Sheet
<!-- keywords: drawer, side panel, slide-over -->

`ui.Sheet` slides a panel in from a `side`. Like a dialog it is open when
state says so and `on_close` lets the handler close it. `size` is how wide
a sheet at the left or right may get, from `sm` to `full` as on a dialog.
`dismissable=False` holds it open as it does a dialog.

```python live
from pydantic import BaseModel


class Panel(BaseModel):
    open: bool = False


def example(s):
    st = s.state.panel
    return ui.Row(
        ui.Button(
            "Open settings", variant="outline", on_click=lambda s, _: setattr(st, "open", True)
        ),
        ui.Sheet(
            ui.Switch(label="Email summaries", default_checked=True),
            ui.Select(options=["Fast", "Thorough"], default="Fast"),
            open=st.open,
            side="right",
            title="Settings",
            description="A sheet holding a few controls.",
            on_close=lambda s, _: setattr(st, "open", False),
        ),
    )
```

## Spinner and Skeleton
<!-- keywords: loading state, busy, pending, placeholder, shimmer, wait -->

`ui.Spinner` shows work in progress with an optional `label`. `ui.Skeleton`
stands in for content still loading, shaped like `text`, a `card` or a
`table`.

```python live
ui.Stack(
    ui.Row(
        ui.Spinner(size="sm"),
        ui.Spinner(),
        ui.Spinner(size="lg", label="Loading the project"),
        gap=6,
    ),
    ui.Grid(
        ui.Skeleton(rows=3),
        ui.Skeleton(shape="card"),
        ui.Skeleton(shape="table", rows=4),
        cols={"sm": 1, "md": 3},
    ),
    gap=6,
)
```

## Empty
<!-- keywords: empty state, no data -->

`ui.Empty` is the state before there is anything, with a `title`, a
`description`, an `icon` and an `action`.

```python live
ui.Empty(
    title="No projects yet",
    description="Create one to start, or import from a file.",
    icon="inbox",
    action=ui.Button("New project", on_click=lambda s, _: s.toast("Creating")),
)
```

## Progress and Steps
<!-- keywords: progress bar, stepper, wizard, percentage -->

`ui.Progress` is a bar for a `value` from 0 to 1 with a `label` and a
`description`, or for a running task, as the [Tasks](/components/tasks) page shows.
`percent=False` leaves the value off the bar, for a plain meter.
`ui.Steps` draws a list of `mw.Step` items with their status.

```python live
ui.Stack(
    ui.Progress(value=0.65, label="Importing", description="130 of 200 rows"),
    ui.Steps(
        items=[
            mw.Step(id="read", label="Read the document", status="done", note="12 pages"),
            mw.Step(id="find", label="Find the headings", status="running"),
            mw.Step(id="route", label="Add routing", status="pending"),
        ]
    ),
    gap=6,
)
```
