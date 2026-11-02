---
title: State and handlers
order: 1
---

# State and handlers

A session has one state. It is a Pydantic model the app declares, it lives
for as long as the session does, and every page is a function of it. A
handler changes that state, the page renders again, and the browser gets
the difference. There is nothing reactive to subscribe to and nothing to
invalidate. Whatever a page shows comes from `s.state`, and a handler is
the only place where things change.

## The loop

A handler is any callable bound to an `on_*` prop. It receives the session
and the event's payload, which is the new value for `on_change`, the
validated model for a form's `on_submit`, and nothing of use for
`on_click`. It may be sync or async. When it returns, the page renders
once, under a lock, so a render sees state as the handler left it. A
handler that cannot take those two arguments is refused when the page is
built, with the expected shape in the error, so a one-argument lambda
fails before anyone clicks.

```python live
from pydantic import BaseModel


class Counter(BaseModel):
    n: int = 0
    note: str = ""


def bump(s, _):
    s.state.counter.n += 1


async def remember(s, text):
    s.state.counter.note = text


def example(s):
    st = s.state.counter
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

The manual composes its state from the models its examples define, one
field per model named after the class, so `Counter` here is
`s.state.counter`. An app declares the model itself, as the next section
shows.

A handler that raises shows "Something went wrong." as a toast and puts
the traceback in the log. The page stays as it was. A handler that needs
to ask first uses `s.confirm` or `s.ask`, both in the Feedback chapter.

## One state for the session

The app names the model once. Every page reads from the same instance,
and it stays as the tab moves from page to page, so what one page set is
there for the next to use. A value a page wants to forget on the way out
is reset in that page's `close` hook.

```python
class State(BaseModel):
    report: str | None = None
    filters: dict[str, str] = {}


app = mw.App("reports", state=State)


@app.page("/")
def choose(s: mw.Session[State]) -> ui.Component:
    return ui.Select(
        options=REPORTS,
        value=s.state.report,
        on_change=lambda s, name: setattr(s.state, "report", name),
    )


@app.page("/report")
def show(s: mw.Session[State]) -> ui.Component:
    return ui.Text(f"Showing {s.state.report}")
```

The `State` here is small because the app is. A bigger app does not grow
one long class. Each feature owns a slice, declared next to the pages that
use it, and the root composes the slices. The root is the app's table of
contents, the one file that knows every feature, and it grows by one line
per feature.

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

## Generated components

A page does not always know how many components it needs. A button adds
a card with inputs each time it is pressed, a file arrives with one input
per column, a search returns rows with a control each. The state holds
one entry per piece in a dict or a list, the page renders a component per
entry, and each handler carries which entry it belongs to. The identity
travels with the handler, so nothing has to be looked up by a string
later, and `key` gives each component an identity across renders, which
the next section is about.

```python live
from functools import partial

from pydantic import BaseModel


class Note(BaseModel):
    title: str = ""
    text: str = ""


class Board(BaseModel):
    notes: dict[int, Note] = {}
    next_id: int = 1


def add(s, _):
    s.state.board.notes[s.state.board.next_id] = Note()
    s.state.board.next_id += 1


def edit(s, value, note_id, field):
    setattr(s.state.board.notes[note_id], field, value)


def remove(s, _, note_id):
    del s.state.board.notes[note_id]


def example(s):
    board = s.state.board
    return ui.Stack(
        ui.Button("Add a note", variant="outline", on_click=add, cls="self-start"),
        *(
            ui.Card(
                ui.Input(value=note.title, placeholder="Title", on_change=partial(edit, note_id=i, field="title")),
                ui.Textarea(value=note.text, placeholder="Text", rows=2, on_change=partial(edit, note_id=i, field="text")),
                footer=ui.Button("Remove", size="sm", variant="ghost", on_click=partial(remove, note_id=i)),
                key=str(i),
            )
            for i, note in board.notes.items()
        ),
        ui.Text(f"{len(board.notes)} notes, {sum(1 for n in board.notes.values() if n.title)} with a title", variant="muted"),
        gap=3,
    )
```

`partial` binds the entry as a keyword, so the handler still takes the
session and the payload first. A reusable piece is built the same way.

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

## Keys

Every component takes a `key`, which is its identity across renders. A
keyed node keeps its browser-side state when the tree around it changes,
whether that is what was typed, which tab is open or where a list is
scrolled. A list of keyed rows that gets reordered moves the rows instead
of redrawing them. Siblings without keys are told apart by position, which
is right for a fixed layout and wrong for a list built from data.

```python live
from pydantic import BaseModel


class Todo(BaseModel):
    items: list[str] = ["Read the manual", "Build a page", "Ship it"]


def drop(s, item):
    s.state.todo.items.remove(item)


def example(s):
    st = s.state.todo
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
state survives. `cls` adds Tailwind classes for a spacing or sizing tweak.

## Who owns a value

A control shows either what Python says or what the browser holds. With
`value=`, every change is reported through `on_change` and Python decides
what the control shows. With `default=`, the browser holds the value and
changes are reported but not required. The Inputs chapter shows the two
side by side. Inside a `ui.Form` every control is browser-owned draft
state until the form is submitted.

## Reaching the session from anywhere

Handlers get the session as their first argument. Code further down, a
helper or a library that wants to show a toast, calls `mw.session()`. It
returns the session of the handler or task that is running, whether on the
loop or in the thread of a sync task.

```python live
import millwork as mw


def notify(what: str) -> None:
    mw.session().toast(what, tone="success")


def example(s):
    return ui.Button("Call a helper", variant="outline", on_click=lambda s, _: notify("The helper found the session."))
```

`s.refresh()` asks for a render from code that is not a handler, such as
work spawned on the loop that changes state on its own. Many calls in one
tick become one render. Data that several visitors share lives in a
database, not in the session, and a page that should follow changes made
elsewhere runs a task that waits for them and calls `s.refresh()` when one
arrives.

## What the framework notices

Some mistakes the framework can see, and it says so once per session, as a
log line with the page's path, and in debug mode as a toast as well.

- **A slow page function**, over 20 ms. The page function builds the tree,
  and I/O belongs in `connect` or a task.
- **A list without keys**, meaning four or more siblings of one type
  without a key whose number changed between renders.
- **A handler that changed nothing**, no state, no command, no task.
  Usually a forgotten `await`.
- **A sync task that changed state from its thread.** A task reports
  through `progress()` and returns a result, and the handler that awaits it
  puts the result in state.

The Running chapter says how to turn debug mode on.
