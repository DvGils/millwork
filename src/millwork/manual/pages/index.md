---
title: Welcome
order: 0
---

# millwork

millwork is a Python framework for data tools and AI applications. The browser
runs one prebuilt React bundle; Python describes the page and handles its
events. The project is Python only: the bundle is prebuilt, and Python owns
every piece of state.

## Install

millwork is on PyPI and needs Python 3.12 or newer:

```
uv add millwork
```

or `pip install millwork`. Then an app is one file:

```python
import millwork as mw
from millwork import ui

app = mw.App("hello")


@app.page("/")
def home(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text("Hello."))
```

Run it with `uv run millwork run app.py` and open the address it prints.

## How this manual works

This manual is itself a millwork app. `millwork docs` serves it; its pages
are Markdown files inside the package, and the sidebar, the search box and
the header are catalogue components. Every example runs: the component you
see is produced by the Python shown beneath it, executed by the server that
serves these pages. Try the button:

```python live
ui.Button("Say hello", icon="sparkles", on_click=lambda s, _: s.toast("Hello from Python."))
```

An example may hold state. `state(Model)` returns an instance of your model
that lives for the session, so a handler can change it and the page re-renders:

```python live
from pydantic import BaseModel


class Counter(BaseModel):
    n: int = 0


def example(s):
    st = state(Counter)
    return ui.Row(
        ui.Button("Add one", on_click=lambda s, _: setattr(st, "n", st.n + 1)),
        ui.Text(f"Clicked {st.n} times.", variant="muted"),
    )
```

A block ends in an expression, which is the component, or defines
`example(s)`, a page function over the session. `mw` and `ui` are in scope;
everything else is imported, as in an app.

## Where to go next

The App chapters say how an app is put together: pages and routing, state
and handlers, signing in, theming, testing, running and deploying. The
Components chapters walk through the catalogue, one group at a time, each
component in its states with the Python that makes it.
