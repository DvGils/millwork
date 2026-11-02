---
title: Testing
order: 4
---

# Testing

A page is a function of state, handlers change state, and the wire is a
list of messages. That lets a test run the real session, dispatcher, tasks
and render with no socket and no browser. `millwork.testing.TestApp` opens
a page, the test clicks and types through the real event path, and then
reads the state and the messages a tab would have received.

## A test

```python
from millwork import ui
from millwork.testing import TestApp


async def test_a_click_counts(app):
    async with TestApp(app).open("/") as page:
        assert page.find("count").props["content"] == "count 0"
        await page.click("more")
        assert page.state.n == 1
        assert page.find("count").props["content"] == "count 1"
        assert page.last_patch is not None
```

Tests are `async def`, run by pytest-asyncio in auto mode. `open(path)`
runs the page's `connect` and the first render and yields a `Page`.
Leaving the block closes the session, `close` hook included. `open(path,
user=User(...))` signs a person in. Without one, a gated page raises
`Forbidden`, which makes a test of its own. `open(path, state=State(...))`
starts from a prepared state and skips `connect`.

## Finding things

`page.find(ui.Table)` is the first node of a type, `page.find("more")` the
node with that key, and `find_all` every one of them. A found node has
`id`, `type`, `props` as they would go to the tab, `children` and, on a
table, `rows`. `page.text()` is every string on the page, for a quick "is
it there". `page.state` is the live state and `page.session` the session
itself.

## Acting

Each action is an event through the real dispatcher, followed by the real
render. There is `click(node)`, `change(node, value)`, `submit(form,
draft)` with a dict or a model instance, `select(table, keys)`,
`action(node, id, key)` for a row or menu action, `upload(node, path,
field=)`, which runs every check an upload gets and returns the `FileRef`,
`send(chat, text, files=)`, `stop(chat)`, `navigate(path)`, and `event(node,
name, payload)` for anything else. A draft that fails validation produces
the same `form_issues` command the tab would get, at the same pointers.

```python
async def test_the_form_rejects_a_short_name(app):
    async with TestApp(app).open("/") as page:
        form = page.find(ui.Form)
        await page.submit(form, {"project_name": "x"})
        assert page.commands[-1].name == "form_issues"
        assert page.commands[-1].args["issues"][0]["pointer"] == "/project_name"
        assert page.state.settings is None
```

## Questions and tasks

A handler that calls `s.confirm` or `s.ask` stops and waits. The test sees
the dialog on the page and answers it with `page.answer(value)`, `False`,
or `None` for a dismissal. A task started by a handler has run by the time
the action returns, and `page.session.tasks[-1]` has its `ok`, `result`
and `progress`. A chat turn's chunks are in `page.stream`, in order.

```python
async def test_wiping_asks_first(app):
    async with TestApp(app).open("/") as page:
        await page.click("wipe")
        assert page.find(ui.Dialog).props["title"] == "Wipe?"
        await page.answer(False)
        assert page.state.count == 0
        await page.click("wipe")
        await page.answer(True)
        assert page.state.count == -1
```

## What the tab would have seen

`page.messages` is every message the server sent. `patches`,
`last_patch`, `commands` (toasts, downloads, navigations, form issues),
`toasts` as plain text, `stream` and `errors` are views on it. `settle()`
waits until the session has nothing left to do. Running tasks and spawned
work are awaited, the coalesced render runs at once, and a handler waiting
on an open question is left for `answer`. Every action settles before it
returns, so a test can read the result on the next line.

What the app's own code raises, in a page function, a handler or a hook,
is raised in the test, with a note saying where, so the traceback points
at the cause rather than at an empty page or a toast. `TestApp(app,
strict=False)` leaves such failures in the log and in `page.failures`,
which is how a running app treats them.

## Running one here

The manual can run a test on itself. The button below builds a small app,
opens it through `TestApp`, clicks, and reports what the assertions said.

```python live
import millwork as mw
from pydantic import BaseModel
from millwork.testing import TestApp


class Count(BaseModel):
    n: int = 0


def tiny_app() -> mw.App:
    app = mw.App("tiny", state=Count, public=None)

    @app.page("/")
    def home(s):
        return ui.Page(
            ui.Text(f"count {s.state.n}", key="count"),
            ui.Button("more", key="more", on_click=lambda s, _: setattr(s.state, "n", s.state.n + 1)),
        )

    return app


class Outcome(BaseModel):
    text: str = "Not run yet."


async def run_test(s, _):
    try:
        async with TestApp(tiny_app()).open("/") as page:
            assert page.find("count").props["content"] == "count 0"
            await page.click("more")
            assert page.state.n == 1
            assert page.find("count").props["content"] == "count 1"
            ops = [op.op for op in page.last_patch.ops]
        state(Outcome).text = f"Passed. The click produced a patch with {ops}."
    except AssertionError as exc:
        state(Outcome).text = f"Failed: {exc}"


def example(s):
    return ui.Row(
        ui.Button("Run the test", icon="play", on_click=run_test),
        ui.Text(state(Outcome).text, variant="muted"),
        gap=4,
    )
```
