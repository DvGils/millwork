---
title: Accessing the session
order: 3
description: mw.session() for code that is not a handler, and s.refresh() for changes made outside one.
related: /components/tasks, /pages/sessions
---

# Accessing the session

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

## A render from outside a handler

`s.refresh()` asks for a render from code that is not a handler, such as
work spawned on the loop that changes state on its own. Many calls in one
tick become one render.

Data that several visitors share lives in a database, not in the session,
and a page that should follow changes made elsewhere runs a task that
waits for them and calls `s.refresh()` when one arrives. The task is
started in `connect` and dies with the session.

```python
@board.connect
async def follow(s: mw.Session[State]) -> None:
    s.state.notices = await db.notices()
    s.task(watch_notices(s), label="Following notices", quiet=True)


async def watch_notices(s: mw.Session[State]) -> None:
    async for notice in db.listen("notices"):
        s.state.notices.append(notice)
        s.refresh()
```

The [Tasks](/components/tasks) page has the task itself, its progress
and its cancel.
