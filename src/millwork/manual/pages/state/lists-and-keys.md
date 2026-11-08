---
title: Lists and keys
order: 2
description: Components generated from data, handlers that know their entry, and the key that gives a component its identity.
related: /state/slices, /components/data
---

# Lists and keys

A page does not always know how many components it needs. A button adds
a card with inputs each time it is pressed, a file arrives with one input
per column, a search returns rows with a control each. The state holds
one entry per piece in a dict or a list, the page renders a component per
entry, and each handler carries which entry it belongs to. The identity
travels with the handler, so nothing has to be looked up by a string
later, and `key` gives each component an identity across renders, which
the second half of this page is about.

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
session and the payload first.

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
