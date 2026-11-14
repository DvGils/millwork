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

`s.outline()` gives what the page holds for the person in front of it,
said by each of its components. It is a dict for the page with one for
each component under `children`: its `id`, its `type`, its `key` when it
has one, and what a person reads on it, such as a label, a text, a value,
a table's columns and first rows or a form's fields.
`s.outline(as_text=True)` gives it as text, a line for a component with
what it holds indented under it. An assistant in the app puts that in
its model's prompt to answer what is on the page and where. `within=`
names the component to start at.

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
            ui.Button("Export", key="export", disabled=True),
            title="Orders",
            key="outlined",
        ),
        ui.Button("Read the card", variant="outline", on_click=look),
        ui.Code(s.state.looked.text, language="text"),
        gap=3,
    )
```

It is made from what was sent to the tab, and holds less than that.
Each kind of component says what a person reads on it and nothing else
it was sent. A table gives the columns it shows and not the fields of a
row that have no column, as `margin` above, nor the keys its rows are
picked by. A number is given to the digits its column shows, in plain
digits with a point, and an amount of money with the theme's currency
after it. A date is given without its time of day. A chosen option is
said by its label. A hidden component is not in it, nor a password, nor
the props of an app's own component, though the components that one
holds are. A field whose value the browser keeps says so and gives
none, and so does a form, unless it is one that cannot be typed in.

What a press would bring up is in it, and says whether it shows now. A
closed dialog says that it is closed. A group, a sidebar or an accordion
says that it is folded where the page holds that with `open=` or
`value=`, and that it may be where the browser keeps it. A tab says the
same of being the open one. What a model should not read is kept out of
such a place too, or left out with `hidden=True`. Only `hidden=True` is
known here: what a class or a style of the app's takes off the screen
is in it.

It is the page as it was last drawn, so a handler that changes state
reads the page from before the change. A table's rows are the first it
was given, and it says how it shows them: sorted by a column, so many
to a page. What a form's last submit was turned down for is in it,
until the form is drawn anew. In a `connect` hook no page is drawn yet,
and there is nothing to give.

`rows=` is how many rows of a table or a chart are given, and how many
of a chat's last messages, and `chars=` is where a text is cut. A page
that has the assistant's own chat on it has that conversation in it as
well. `within=` reads the part of the page the question is about, and
gives `None`, or no text, for a name that finds nothing or only what is
hidden. No one component makes the text long, and a page with hundreds
of them does, so an assistant on such a page reads a part.

In the text, what the app gave stands in quotes, or bare where it is one
plain word, so that a label or a cell cannot be read as a line of the
outline. A component that can be pointed at has a name on its line:
`key=` when its key finds no other component on the page, and `id=`
otherwise. A field of a form is named by its form and where it is in it,
as `order/amount`. Each is a name `s.focus` and `s.highlight` take. What
is highlighted says so on its line. Keys and ids are in it as they are,
and so is whatever a key was made from.
