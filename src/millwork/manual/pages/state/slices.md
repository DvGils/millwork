---
title: One slice per feature
order: 1
description: How a bigger app splits its state into slices that the root composes.
related: /state/lists-and-keys, /testing
---

# One slice per feature

A bigger app does not grow one long class. Each feature owns a slice,
declared next to the pages that use it, and the root composes the slices.
The root is the app's table of contents, the one file that knows every
feature, and it grows by one line per feature.

```python
# reports/state.py
class ReportsState(BaseModel):
    selected: str | None = None
    filters: dict[str, str] = {}


# editor/state.py
class EditorState(BaseModel):
    document: str | None = None
    dirty: bool = False


# state.py
class State(BaseModel):
    prefs: Prefs = Prefs()
    reports: ReportsState = ReportsState()
    editor: EditorState = EditorState()


# reports/pages.py
@app.page("/reports")
def reports(s: mw.Session[State]) -> ui.Component:
    st = s.state.reports
    return ui.Page(...)


@reports.close
async def leave(s: mw.Session[State]) -> None:
    s.state.reports = ReportsState()
```

A page in `reports/` reads `s.state.reports` and never touches the rest.
The whole session is one object, which is what a test hands to
`TestApp.open(state=...)`, what a debug view shows, and what an app saves
when it wants a session to come back later.

## A reusable piece

A piece of a page that appears in several places is a function. It takes
its slice of the state and the handler it should call, and returns
components. Composition is passing the slice, and nothing is registered or
namespaced.

```python
def filter_bar(st: ReportsState, on_change) -> ui.Component:
    return ui.Row(
        *(
            ui.Input(value=value, on_change=partial(on_change, field=field), key=field)
            for field, value in st.filters.items()
        )
    )


@app.page("/reports")
def reports(s: mw.Session[State]) -> ui.Component:
    return ui.Page(filter_bar(s.state.reports, set_filter))
```

`partial` binds the field as a keyword, so the handler still takes the
session and the payload first. [Lists and keys](/state/lists-and-keys)
builds on the same move for components made from data.
