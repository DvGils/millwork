---
title: Feedback
order: 3
---

# Feedback

Telling the user what is going on, with alerts, toasts, dialogs, progress
and the empty and loading states.

## Alert

`ui.Alert` is a banner with a `title`, a `description`, a `tone`, an `icon`,
`actions` and, with `dismissable`, a close button that fires `on_dismiss`.

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
    ui.Alert(title="Dismiss me", dismissable=True, on_dismiss=lambda s, _: s.toast("Dismissed")),
    gap=3,
)
```

## Toast

A toast is a command rather than a component. Call `s.toast(message,
tone=, title=)` from any handler. `action=(label, handler)` puts a button
on it that runs the handler once.

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

## Dialog

`ui.Dialog` is open when state says so. It has a `title`, a
`description`, a `footer` and a `size` from `sm` to `full`. `on_close`
fires when the user dismisses it, and the handler sets state so it
closes.

```python live
from pydantic import BaseModel


class Modal(BaseModel):
    open: bool = False


def example(s):
    st = s.state.modal

    def close(s, _):
        st.open = False

    return ui.Row(
        ui.Button("Open a dialog", on_click=lambda s, _: setattr(st, "open", True)),
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

Two session calls wait for the user from inside a handler. `await s.confirm(
title, description=, destructive=)` shows a dialog and returns True or
False. `await s.ask(component)` shows any component and returns what it
submits. A `Form` answers with its validated model, and a closed dialog
answers None.

```python live
from pydantic import BaseModel


class Asked(BaseModel):
    answer: str = "nothing yet"


async def confirm(s, _):
    st = s.state.asked
    ok = await s.confirm("Archive the project?", "You can restore it later.", destructive=True)
    st.answer = "archived" if ok else "kept"


def example(s):
    st = s.state.asked
    return ui.Row(
        ui.Button("Archive", variant="outline", on_click=confirm),
        ui.Text(f"Result: {st.answer}", variant="muted"),
        gap=3,
    )
```

## Sheet

`ui.Sheet` slides a panel in from a `side`. Like a dialog it is open when
state says so and `on_close` lets the handler close it.

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

`ui.Progress` is a bar for a `value` from 0 to 1 with a `label` and a
`description`, or for a running task, as the Tasks chapter shows.
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
