---
title: State and handlers
order: 1
---

# State and handlers

A page is a function of the session's state. A handler changes that state;
the page renders again; the browser gets the difference. There is nothing
reactive to subscribe to and nothing to invalidate: whatever a page shows
comes from `s.state`, and the only place where things change is a handler.

## The loop

`s.state` is an instance of the model named on the page, or on the app for
every page. A handler is any callable bound to an `on_*` prop. It receives
the session and the event's payload: the new value for `on_change`, the
validated model for a form's `on_submit`, nothing of use for `on_click`.
It may be sync or async. When it returns, the page renders once, under a
lock, so a render never sees state a handler is still changing.

```python live
from pydantic import BaseModel


class Counter(BaseModel):
    n: int = 0
    note: str = ""


def bump(s, _):
    state(Counter).n += 1


async def remember(s, text):
    state(Counter).note = text


def example(s):
    st = state(Counter)
    return ui.Stack(
        ui.Row(
            ui.Button("Count", on_click=bump),
            ui.Text(f"{st.n} so far", variant="muted"),
            gap=3,
        ),
        ui.Input(value=st.note, placeholder="Type, then look right", on_change=remember),
        ui.Text(f"Python holds {st.note!r}", variant="muted"),
        gap=3,
    )
```

A handler that raises shows "Something went wrong." as a toast and the log
has the traceback; the page stays as it was. A handler that needs to ask
first uses `s.confirm` or `s.ask`, in the Feedback chapter.

## Keys

Every component takes a `key`. A key is a component's identity across
renders: a keyed node keeps its browser-side state (what is typed, which
tab is open, where a list is scrolled) when the tree around it changes,
and a list of keyed rows that is reordered moves the rows instead of
redrawing them. Siblings without keys are told apart by position, which is
right for a fixed layout and wrong for a list built from data.

```python live
from pydantic import BaseModel


class Todo(BaseModel):
    items: list[str] = ["Read the manual", "Build a page", "Ship it"]


def drop(s, item):
    state(Todo).items.remove(item)


def example(s):
    st = state(Todo)
    return ui.Stack(
        *(
            ui.Row(
                ui.Text(item),
                ui.Button(icon="x", size="sm", variant="ghost", on_click=lambda s, _, i=item: drop(s, i)),
                justify="between",
                key=item,
            )
            for item in st.items
        ),
        ui.Button(
            "Put them back",
            size="sm",
            variant="outline",
            on_click=lambda s, _: setattr(st, "items", Todo().items),
        ),
        gap=2,
    )
```

A key is also how `s.reset(key)` returns a browser-owned control to its
`default`, and how `ui.Button(form=key)` finds its form. `hidden=True`
keeps a component in the tree without showing it, so its browser-side
state survives; `cls` adds Tailwind classes for a spacing or sizing tweak.

## Who owns a value

A control shows either what Python says (`value=`, with every change
reported through `on_change`) or what the browser holds (`default=`, with
changes reported but not required). Never both. The Inputs chapter shows
the two side by side. Inside a `ui.Form` every control is browser-owned
draft state until the form is submitted.

## Reaching the session from anywhere

Handlers get the session as their first argument. Code further down, a
helper or a library that wants to show a toast, calls `mw.session()`: it
returns the session of the handler or task that is running, on the loop
or in the thread of a sync task.

```python live
import millwork as mw


def notify(what: str) -> None:
    mw.session().toast(what, tone="success")


def example(s):
    return ui.Button("Call a helper", variant="outline", on_click=lambda s, _: notify("The helper found the session."))
```

`s.refresh()` asks for a render from code that is not a handler, such as
work spawned on the loop that changes state on its own. Many calls in one
tick are one render.

## What the framework notices

Some mistakes the framework can see, and says so: once per session, as a
log line with the page's path, and in debug mode as a toast as well.

- **A slow page function**, over 20 ms. The page function builds the tree
  and nothing else; I/O belongs in `connect` or a task.
- **A list without keys**: four or more siblings of one type without a
  key whose number changed between renders.
- **A handler that changed nothing**: no state, no command, no task.
  Usually a forgotten `await`.
- **A sync task that changed state from its thread.** A task reports
  through `progress()` and returns a result; the handler that awaits it
  puts the result in state.

The Running chapter says how to turn debug mode on.
