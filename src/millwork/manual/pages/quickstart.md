---
title: Quickstart
order: 1
description: Install millwork and run a first app in a few minutes.
related: /pages/pages-and-routes, /state/state-and-handlers, /components/layout
---

# Quickstart

millwork is on PyPI and needs Python 3.12 or newer.

```
uv add millwork
```

`pip install millwork` works too.

## A first app

An app is one file. It makes an `App`, registers a page on a path, and the
page is a function of the session that returns the component tree.

```python
import millwork as mw
from millwork import ui

app = mw.App("hello")


@app.page("/")
def home(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text("Hello."))
```

Run it and open the address it prints:

```
uv run millwork run app.py
```

## Something that happens

A handler is a callable on an `on_*` prop. It gets the session and the
event's payload, changes state, and the page renders again. State is a
Pydantic model the app declares once, and `s.state` is the session's
instance of it.

```python
import millwork as mw
from millwork import ui
from pydantic import BaseModel


class State(BaseModel):
    n: int = 0


app = mw.App("hello", state=State)


def bump(s: mw.Session[State], _) -> None:
    s.state.n += 1


@app.page("/")
def home(s: mw.Session[State]) -> ui.Component:
    return ui.Page(
        ui.Text(f"Clicked {s.state.n} times."),
        ui.Button("Add one", on_click=bump),
    )
```

That is the shape of every millwork app: a state, pages that draw it, and
handlers that change it. `millwork run app.py --reload --debug` restarts
the process when a file changes and shows page errors in the tab, which is
the loop while building.

## On this page

The same example, running here:

```python live
from pydantic import BaseModel


class Taps(BaseModel):
    n: int = 0


def example(s):
    st = s.state.taps
    return ui.Stack(
        ui.Text(f"Clicked {st.n} times."),
        ui.Button("Add one", on_click=lambda s, _: setattr(st, "n", st.n + 1), cls="self-start"),
        gap=3,
    )
```

From here, [Pages and routes](/pages/pages-and-routes) is how an app
grows beyond one page, [State and handlers](/state/state-and-handlers) is
how state and handlers work in full, and the Components pages show what
there is to draw with.
