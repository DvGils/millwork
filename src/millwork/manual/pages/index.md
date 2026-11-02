---
title: Welcome
order: 0
---

# millwork

millwork is a Python framework for data tools and AI applications. The
browser runs one prebuilt React bundle, and Python describes the page and
handles what happens on it. You write Python only. There is no JavaScript
to build, and every piece of state lives on the server.

## Install

millwork is on PyPI and needs Python 3.12 or newer.

```
uv add millwork
```

`pip install millwork` works too. An app is one file:

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

This manual is itself a millwork app. `millwork docs` serves it. Its pages
are Markdown files inside the package, and the sidebar, the search box and
the header are catalog components. Every example runs. The component you
see is produced by the Python shown beneath it, executed by the same server
that serves these pages. Try the button:

```python live
ui.Button("Say hello", icon="sparkles", on_click=lambda s, _: s.toast("Hello from Python."))
```

An example may hold state. An app declares one state model and reads
`s.state`, and the manual composes its own from the models its examples
define, one field per model named after the class, so `Clicks` is
`s.state.clicks`. A handler changes it and the page renders again. The
State chapter has the whole picture.

```python live
from pydantic import BaseModel


class Clicks(BaseModel):
    n: int = 0


def example(s):
    st = s.state.clicks
    return ui.Row(
        ui.Button("Add one", on_click=lambda s, _: setattr(st, "n", st.n + 1)),
        ui.Text(f"Clicked {st.n} times.", variant="muted"),
    )
```

A block either ends in an expression, which is the component, or defines
`example(s)`, a page function over the session. `mw` and `ui` are already
in scope. Everything else is imported, as in an app.

## Where to go next

The App chapters cover how an app is put together, from pages and routing
through state, signing in, theming and testing to running it somewhere.
The Components chapters walk through the catalog one group at a time,
with each component in its states and the Python that makes it. For a
lookup rather than a chapter, every component's props with their types
and defaults are listed at [/llms.txt](/llms.txt), which `millwork
reference` prints as well.
