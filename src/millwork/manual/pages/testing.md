---
title: Testing
order: 4
description: TestApp drives a session without a browser. Find, act, answer, and read what the tab would have seen.
related: /state/state-and-handlers, /running/development
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
Leaving the block closes the session, `close` hook included, and a hook
that raises fails the test there. `open(path,
user=User(...))` signs a person in. Without one, a gated page raises
`Forbidden`. So does a page whose `allow=` rule refuses that user, and a
`connect` that raises `NotFound` or `Forbidden` raises it from `open`
too, which makes a test of its own. `open(path,
state=State(...))` starts from a prepared state and skips `connect`.
`open(path, visitor="a")` opens the page from a browser with that visitor
id, in an app that [identifies its visitors](/pages/visitors).

## Finding things

`page.find(ui.Table)` is the first node of a type, `page.find("more")` the
node with that key, and `find_all` every one of them. `within=` looks
inside one node only, so `page.find("save", within="orders")` is the save
button of the card with the key `orders` when every card has one.
Any other keyword is a prop the node has to have, so
`page.find(ui.Button, label="Delete")` is the button that says Delete.
`page.find_all(ui.Custom)` finds the app's own components, and the `type`
of each is the name it goes by. Its `props` are the ones the component
was given in `props=`, side by side with the catalogue's own, so
`page.find(ui.Custom, chosen="5")` finds it by one of them, and each of
its events shows as `on_<name>: True`. A found node has `id`, `type`, `props` as
they would go to the tab, `children` and, on a table, `rows`. `page.text()` is every string on the page, for a quick "is
it there". `page.state` is the live state and `page.session` the session
itself.

A [lazy part](/components/layout#lazy-parts) in a tab that is not open is
found as it was last drawn, which is what a browser holds. A test opens
the tab first, with `change`.

## Acting

Each action is an event through the real dispatcher, followed by the real
render. There is `click(node)`, `change(node, value)`, `submit(form,
draft)` with a dict or a model instance, `select(table, keys)`,
`choose(menu, item)` for an item of a `DropdownMenu` by its id or label,
`action(node, id, key)` for a row or card action, `upload(node, path,
field=)`, which runs every check an upload gets and returns the `FileRef`,
`send(chat, text, files=)`, `stop(chat)`, `navigate(path)`, and `event(node,
name, payload)` for anything else. A draft that fails validation produces
the same `form_issues` command the tab would get, at the same pointers.
On `ui.Tabs`, `change(tabs, "history")` opens the tab with that id.

An event of a custom component is sent by its name, with the payload the
component would emit.

```python
async def test_picking_a_card_keeps_it(app):
    async with TestApp(app).open("/") as page:
        await page.event("deck", "pick", "5")
        assert page.state.picked == "5"
        assert page.find("deck").props["chosen"] == "5"
```

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

A click on a `Download` is the download its button starts. A handler that
calls `s.confirm` or `s.ask` stops and waits. The test sees
the dialog on the page and answers it with `page.answer(value)`, `False`,
or `None` for a dismissal. A task started by a handler has run by the time
the action returns, and `page.session.tasks[-1]` has its `ok`, `result`
and `progress`. A chat turn's chunks are in `page.stream`, in order, in
the AI SDK's UI message stream format, where each
`{"type": "text-delta", "delta": ...}` carries some of the reply's words.
The finished reply is easier to check on the thread, as
`page.session.chat(key).messages[-1].text`.

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
`toasts` as plain text, `notices` as toasts with their tone and title,
`stream` and `errors` are views on it.
`toast_action("Undo")` presses the button of the latest toast that has
one. `settle()` waits until the session has nothing left to do. Running
tasks and spawned work are awaited, the coalesced render runs at once,
and a handler waiting on an open question is left for `answer`. A quiet
task is not waited for, since it waits for something outside the session,
and after ten seconds `settle` gives up and names what still runs. Every
action settles before it returns, so a test can read the result on the
next line.

A test of what a page shows while a task runs starts the action as work
of its own and waits for the page to catch up, as a tab would.

```python
async def test_an_import_can_be_canceled(app, tmp_path):
    big = tmp_path / "big.csv"
    big.write_text(big_csv())
    async with TestApp(app).open("/import") as page:
        started = asyncio.create_task(page.upload("file", big))
        while not page.find_all("cancel"):
            await asyncio.sleep(0.01)
        await page.click("cancel")
        await started
        assert page.session.tasks[-1].status == "cancelled"
```

A task that fails and that no handler awaits is reported like a handler
that raised, so a strict harness raises it in the test, and `strict=False`
lists it in `page.failures` next to the toast a running app would show.

What the app's own code raises, in a page function, a handler or a hook,
is raised in the test, with a note saying where, so the traceback points
at the cause rather than at a failure page or a toast. `TestApp(app,
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
        s.state.outcome.text = f"Passed. The click produced a patch with {ops}."
    except AssertionError as exc:
        s.state.outcome.text = f"Failed: {exc}"


def example(s):
    return ui.Row(
        ui.Button("Run the test", icon="play", on_click=run_test),
        ui.Text(s.state.outcome.text, variant="muted"),
        gap=4,
    )
```
