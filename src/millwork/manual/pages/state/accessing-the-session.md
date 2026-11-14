---
title: Accessing the session
order: 3
description: mw.session() for code that is not a handler, s.refresh() for changes made outside one, a signal for data that sessions share, and the page as data.
related: /components/tasks, /pages/sessions
---

# Accessing the session

Any code that runs for a session can reach it, and this page shows the
two ways. Handlers get the session as their first argument. Code further
down, a helper or a library that wants to show a toast, calls `mw.session()`. It
returns the session of the handler or task that is running, whether on the
loop or in the thread of a sync task.

```python live
import millwork as mw


def notify(what: str) -> None:
    mw.session().toast(what, tone="success")


def example(s):
    return ui.Button("Call a helper", variant="outline", on_click=lambda s, _: notify("The helper found the session."))
```

## A render from outside a handler

`s.refresh()` asks for a render from code that is not a handler, such as
work spawned on the loop that changes state on its own. Many calls in one
tick become one render.

## Data that sessions share

A session's state is its own. What several people see together, a list of
orders or who is on a page, is kept outside the sessions, in an object of
the app's or in a database, and each page function reads it there. A
`mw.Signal` stands next to that data. A page follows it, the code that
changes the data fires it, and every session that follows is drawn again.

```python
ORDERS: list[Order] = []
orders_changed = mw.Signal()


@app.page("/orders")
def orders(s: mw.Session[State]) -> ui.Component:
    return ui.Page(
        ui.Table(rows=ORDERS, key="orders"),
        ui.Form(Order, key="new", on_submit=add),
    )


@orders.connect
def follow_orders(s: mw.Session[State]) -> None:
    s.follow(orders_changed)


def add(s: mw.Session[State], order: Order) -> None:
    ORDERS.append(order)
    orders_changed.fire()
```

`s.follow(signal)` lasts for as long as the session is on the page, so
nothing has to undo it. It is said in the page's `connect` hook, which
[Sessions](/pages/sessions) describes and which gets the page's
parameters. Said in a handler it lasts until the next navigation, one to
the same page included, since `connect` runs again there and a handler
does not. A signal carries nothing. Firing it says
"look again", and the page function reads what it always reads. It can be
fired from a handler, a task or a thread, and many fires close together
are one drawing for each follower.

Make a signal for each thing that changes by itself. A signal that every
page follows draws every session at each fire. With one for the list of
orders and one for each order, a change to one order draws the pages that
show that order and no others.

A signal reaches the sessions of its own process. Data in a database is
also changed from elsewhere, by another replica of the app or by a job.
The process listens to the database once and fires the signal for its own
sessions. `app.spawn` runs that listener for as long as the app runs.

```python
@app.on_startup
def listen() -> None:
    app.spawn(forward_orders(), "listening for orders")


async def forward_orders() -> None:
    while True:
        try:
            async for _ in db.listen("orders"):
                orders_changed.fire()
        except OSError:
            await asyncio.sleep(5)
        orders_changed.fire()
```

Work that was spawned and fails is logged and not started again, so the
listener goes back to listening by itself when the connection drops. It
fires once as it does, for what changed while nobody listened.

A database that cannot tell of its changes is asked, for something small
such as a counter or the time of the last change, and the signal is fired
when that has moved.

```python
@app.on_startup
def watch() -> None:
    app.spawn(watch_orders(), "watching the orders")


async def watch_orders() -> None:
    seen = await db.orders_version()
    while True:
        await asyncio.sleep(5)
        if (now := await db.orders_version()) != seen:
            seen = now
            orders_changed.fire()
```

Either way it is one listener for the process, however many tabs are
open.

## The page as data

`s.outline()` gives the page as the person sees it, as data. An assistant
in the app reads it to answer what is on the page and where. It is a dict
for the page, with one for each component under `children`.
`s.outline(as_text=True)` gives the same as text for a model's prompt,
a line for a component with what it holds indented under it.

```python live
from pydantic import BaseModel


class Looked(BaseModel):
    text: str = "Press the button."


def look(s, _):
    s.state.looked.text = s.outline(within="outlined", as_text=True)


def example(s):
    return ui.Stack(
        ui.Card(
            ui.Table(
                rows=[
                    {"customer": "Kestrel Books", "amount": 980, "margin": 0.31},
                    {"customer": "Juniper Press", "amount": 120, "margin": 0.12},
                ],
                columns=[ui.Column(key="customer"), ui.Column(key="amount")],
                key="orders",
            ),
            ui.Input(key="note", placeholder="A note"),
            ui.Button("Export", key="export", variant="outline", disabled=True),
            title="Orders",
            key="outlined",
        ),
        ui.Button("Read the card", on_click=look),
        ui.Code(s.state.looked.text, language="text"),
        gap=3,
    )
```

It says what a person reads on each component, and nothing else that was
sent to the browser.

| In it | Not in it |
| --- | --- |
| Labels, texts and the values the page holds | A hidden component and what is inside it |
| The columns a table shows and its first rows | A row's fields that have no column, as `margin` above |
| A form's fields, by name | What is typed into a form, which the browser keeps |
| A chosen option, by its label | The value behind an option, and a password |
| A closed dialog and a folded group, marked as that | The props of an app's own component |
| What is highlighted | |

`within=` starts at one component and gives `None` when it is not on the
page. `rows=` is how many rows of a table, a chart or a chat are given,
and `chars=` is where a text is cut. A page with hundreds of components
is long as text, so an assistant on one reads a part of it.

A component that can be pointed at has a name on its line, `key=` or
`id=`, and a field of a form is named as `order/amount`. `s.focus` and
`s.highlight` take those names.

It is the page as it was last drawn, so a handler that changes state
reads the page from before the change. Only `hidden=True` keeps a
component out of it. What a class or a style of the app's takes off the
screen is still in it.
