---
title: Tasks
order: 8
description: Work that runs beyond a handler, with progress, steps and cancel.
---

# Tasks

Work that takes longer than a click goes in a task. The session owns it, the
page shows its progress, and the user can cancel it. A handler that awaits a
task lends the handler's turn, so the page stays live meanwhile.

## Starting one

`s.task(work, *args, label=)` runs a coroutine or a plain function, and a
plain function runs in a thread. It returns a `mw.Task` whose `done`,
`status`, `progress`, `steps` and `result` the page can read. The status
is `pending`, `running`, `done`, `failed` or `cancelled`, spelled that
way on the wire. `ui.Progress(task=)` and `ui.Steps(task=)` draw it, a
canceled or failed task included, and `task.cancel()` stops it. A state
model may hold one as `mw.Task | None`.

```python live
import time

from pydantic import BaseModel


def crunch(n: int) -> str:
    p = mw.progress()
    p.plan(["Read", "Analyze", "Write"])
    with p.step("Read"):
        time.sleep(0.4)
    with p.step("Analyze") as step:
        for i in range(n):
            p.check()
            p.set((i + 1) / n, f"row {i + 1} of {n}")
            time.sleep(0.15)
        step.note(f"{n} rows")
    with p.step("Write"):
        time.sleep(0.3)
    return f"{n} rows analyzed"


class Job(BaseModel):
    run: mw.Task | None = None


def example(s):
    st = s.state.job
    running = st.run is not None and not st.run.done
    return ui.Stack(
        ui.Row(
            ui.Button(
                "Start",
                disabled=running,
                on_click=lambda s, _: setattr(st, "run", s.task(crunch, 12, label="Crunching")),
            ),
            ui.Button(
                "Cancel",
                variant="outline",
                disabled=not running,
                on_click=lambda s, _: st.run.cancel(),
            ),
            gap=2,
        ),
        ui.Progress(task=st.run) if st.run else ui.Text("No job yet.", variant="muted"),
        ui.Steps(task=st.run) if st.run else None,
        ui.Text(f"Result: {st.run.result}" if st.run and st.run.ok else "", variant="muted"),
        gap=4,
    )
```

## Reporting from the work

Inside the work, `mw.progress()` is the reporter. `set(value, message)`
moves the bar, `plan([...])` declares steps up front, `step(label)` opens
one as a context manager, and `note(text)` leaves a short result on it.
`log(line)` adds a line of output to the step that is open, or replaces
the line under the bar when no step is.

Canceling stops work that is a coroutine at once, at the `await` it is
waiting on. Work in a thread cannot be stopped from outside. There,
`check()` raises `mw.Cancelled` when the task was canceled, so a loop
stops at its next check.

## Waiting for a result

A handler can `await` the task to use its result, and lends its turn
while it waits. `on_done=` names a handler to run when the task
ends, with the task as its argument. `timeout=` cancels a task that runs
too long.

```python live
import asyncio

from pydantic import BaseModel


async def slow_sum(a: int, b: int) -> int:
    await asyncio.sleep(0.8)
    return a + b


class Sum(BaseModel):
    text: str = "not computed"


async def compute(s, _):
    st = s.state.sum
    st.text = "computing"
    result = await s.task(slow_sum, 2, 3, label="Adding")
    st.text = f"2 + 3 = {result}"


def example(s):
    return ui.Row(
        ui.Button("Compute", on_click=compute),
        ui.Text(s.state.sum.text, variant="muted"),
        gap=3,
    )
```

## Later and threads

`s.later(seconds, work)` runs work after a delay. `s.thread(fn, *args)`
runs a blocking function in the thread pool, which is what `s.task` does
for a plain function.

```python live
from pydantic import BaseModel


class Tick(BaseModel):
    text: str = "waiting"


def example(s):
    st = s.state.tick

    def arm(s, _):
        st.text = "armed"
        s.later(1.5, lambda: setattr(st, "text", "fired"))

    return ui.Row(
        ui.Button("Arm a timer", variant="outline", on_click=arm),
        ui.Text(st.text, variant="muted"),
        gap=3,
    )
```
