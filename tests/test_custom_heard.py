"""A component of the app's own is told when the session is done with an
event it sent, so it can show what was done until then and no longer."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.testing import TestApp


class Lineup(BaseModel):
    order: list[str] = ["a", "b", "c"]
    seen: list[str] = []


def make() -> mw.App:
    app = mw.App("lineup", state=Lineup, public=None, components=None)

    def move(s: mw.Session[Lineup], asked: Any) -> None:
        s.state.seen.append("move")
        if asked == "refuse":
            return
        s.state.order.reverse()

    def crash(s: mw.Session[Lineup], asked: Any) -> None:
        raise RuntimeError("no")

    @app.page("/")
    def home(s: mw.Session[Lineup]) -> ui.Component:
        return ui.Page(
            ui.Custom(
                "Lineup", key="lineup", props={"order": s.state.order}, events={"move": move}
            ),
            ui.Custom("Other", key="other", events={"crash": crash}),
            ui.Sortable(ui.Text("one", key="one"), key="list", on_move=lambda s, m: None),
        )

    return app


def heard(page: Any) -> list[str]:
    return [c.args["node"].rsplit("/", 1)[-1] for c in page.commands if c.name == "heard"]


def tags(page: Any) -> list[str]:
    return [c.args["tag"] for c in page.commands if c.name == "heard"]


async def test_the_tab_is_told_once_for_each_event_of_a_custom_component() -> None:
    async with TestApp(make()).open("/") as page:
        assert heard(page) == []
        # Taken: said behind the drawing that has the new order.
        await page.event("lineup", "move", "go")
        assert page.state.order == ["c", "b", "a"] and heard(page) == ["lineup"]
        assert page.find("lineup").props["order"] == ["c", "b", "a"]
        # Left as it was: said all the same, which is how the tab knows.
        await page.event("lineup", "move", "refuse")
        assert page.state.seen == ["move", "move"] and heard(page) == ["lineup", "lineup"]
        # An event that no handler takes is said at once.
        with pytest.raises(LookupError):
            await page.event("lineup", "rename", "x")
        assert heard(page) == ["lineup", "lineup", "lineup"]
        # Each by the tag its event came with, which is how the tab tells
        # them apart whatever order they are done in.
        assert len(set(tags(page))) == 3
        # An event that came without a tag is waited for by nobody.
        await page.event("list", "move", {"key": "root/list/one", "source": "root/list", "to": 0})
        assert heard(page) == ["lineup", "lineup", "lineup"]


async def test_an_event_no_handler_takes_is_heard_by_its_own_tag_and_not_anothers() -> None:
    """A handler that takes its time, and behind it an event that nothing
    takes: the second is said at once, by its own tag, and the first when
    its handler is done."""
    import asyncio

    from millwork.protocol import Event

    app = mw.App("slow", state=Lineup, public=None, components=None)
    go = asyncio.Event()

    async def move(s: mw.Session[Lineup], asked: Any) -> None:
        await go.wait()
        s.state.order.reverse()

    @app.page("/")
    def home(s: mw.Session[Lineup]) -> ui.Component:
        return ui.Page(ui.Custom("Lineup", key="lineup", events={"move": move}))

    async with TestApp(app, strict=False).open("/") as page:
        node = page.find("lineup").id
        page.session.event(Event(node=node, name="move", payload=None, tag="first"))
        page.session.event(Event(node=node, name="rename", payload=None, tag="second"))
        for _ in range(1000):
            if tags(page):
                break
            await asyncio.sleep(0)
        assert tags(page) == ["second"]
        go.set()
        await page.settle()
        assert tags(page) == ["second", "first"] and page.state.order == ["c", "b", "a"]


async def test_a_handler_that_raises_is_heard_as_well() -> None:
    async with TestApp(make(), strict=False).open("/") as page:
        await page.event("other", "crash", None)
        assert [where for where, _ in page.failures] and heard(page) == ["other"]
