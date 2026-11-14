"""A signal: the app's way to say "this changed" to every session that
shows it."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.testing import TestApp


class State(BaseModel):
    mine: int = 0


def make_app() -> tuple[mw.App, mw.Signal, list[str], dict[str, int]]:
    """A list of orders that every session sees, a signal for it, and two
    more pages: one that does not follow it and one whose door is shut.
    ``drawn`` counts how often each page was drawn."""
    app = mw.App("orders", state=State, public=None)
    changed = mw.Signal()
    orders: list[str] = []
    drawn = {"/": 0, "/other": 0}

    def add(s: mw.Session[State], _: Any) -> None:
        orders.append(f"order {len(orders) + 1}")
        changed.fire()

    def add_many(s: mw.Session[State], _: Any) -> None:
        for _i in range(10):
            add(s, None)

    async def add_in_a_thread(s: mw.Session[State], _: Any) -> None:
        await asyncio.to_thread(add, s, None)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        drawn["/"] += 1
        return ui.Page(
            ui.Text(", ".join(orders) or "no orders", key="orders"),
            ui.Button("add", key="add", on_click=add),
            ui.Button("add many", key="many", on_click=add_many),
            ui.Button("add in a thread", key="thread", on_click=add_in_a_thread),
            ui.Button("go", key="go", on_click=lambda s, _: s.navigate("/other")),
            ui.Button("try", key="try", on_click=lambda s, _: s.navigate("/shut")),
        )

    @home.connect
    def follow(s: mw.Session[State]) -> None:
        s.follow(changed)

    @app.page("/other")
    def other(s: mw.Session[State]) -> ui.Component:
        drawn["/other"] += 1
        return ui.Page(ui.Text("elsewhere", key="t"))

    @app.page("/shut")
    def shut(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("never", key="t"))

    @shut.connect
    def no_way_in(s: mw.Session[State]) -> None:
        s.follow(changed)
        raise RuntimeError("the door is shut")

    return app, changed, orders, drawn


def shown(page: Any) -> str:
    return str(page.find("orders").props["content"])


async def test_a_change_one_session_makes_is_drawn_for_the_others() -> None:
    app, _, _, _ = make_app()
    t = TestApp(app)
    async with t.open("/") as ada, t.open("/") as cy:
        await ada.click("add")
        assert shown(ada) == "order 1"
        await cy.settle()
        assert shown(cy) == "order 1"
        await cy.click("add")
        await ada.settle()
        assert shown(ada) == shown(cy) == "order 1, order 2"


async def test_many_fires_are_one_drawing_and_the_one_who_fired_is_drawn_once() -> None:
    app, _, _, drawn = make_app()
    t = TestApp(app)
    async with t.open("/") as ada, t.open("/") as cy:
        before = dict(drawn), len(ada.patches), len(cy.patches)
        await ada.click("many")
        await cy.settle()
        assert drawn["/"] == before[0]["/"] + 2
        assert (len(ada.patches), len(cy.patches)) == (before[1] + 1, before[2] + 1)


async def test_a_signal_fired_from_a_thread_reaches_its_followers() -> None:
    app, _, _, _ = make_app()
    t = TestApp(app)
    async with t.open("/") as ada, t.open("/") as cy:
        await ada.click("thread")
        await cy.settle()
        assert shown(cy) == "order 1"


async def test_only_who_follows_is_drawn_and_leaving_the_page_ends_it() -> None:
    app, changed, _, drawn = make_app()
    t = TestApp(app)
    async with t.open("/") as ada, t.open("/") as cy:
        await cy.click("go")
        assert cy.session.path == "/other"
        before = drawn["/other"]
        await ada.click("add")
        await cy.settle()
        # The page left does not follow any more, and the one it went to
        # never did.
        assert drawn["/other"] == before
        assert set(changed._followers) == {ada.session}


async def test_a_page_the_session_stays_on_goes_on_following() -> None:
    app, changed, _, _ = make_app()
    t = TestApp(app, strict=False)
    async with t.open("/") as ada, t.open("/") as cy:
        # The page asked for does not come. What it followed before it
        # failed is dropped, and the page the session is back on follows as
        # it did.
        await cy.click("try")
        assert cy.session.path == "/"
        assert set(changed._followers) == {ada.session, cy.session}
        await ada.click("add")
        await cy.settle()
        assert shown(cy) == "order 1"


async def test_a_session_that_ends_follows_nothing() -> None:
    app, changed, _, _ = make_app()
    t = TestApp(app)
    async with t.open("/") as ada:
        assert set(changed._followers) == {ada.session}
        session = ada.session
    assert set(changed._followers) == set()
    # Fired with nobody there, and followed by a session that is over.
    changed.fire()
    session.follow(changed)
    assert set(changed._followers) == set()


async def test_only_a_signal_can_be_followed() -> None:
    app, _, _, _ = make_app()
    async with TestApp(app).open("/") as ada:
        with pytest.raises(TypeError, match=r"s\.follow\(\) takes a millwork\.Signal"):
            ada.session.follow("orders")


async def test_work_spawned_for_the_app_runs_until_the_app_stops() -> None:
    app, changed, orders, _ = make_app()
    arrived: asyncio.Queue[str] = asyncio.Queue()
    listening: list[asyncio.Task[Any] | None] = []

    async def listen() -> None:
        # What a database that tells of its changes looks like from here.
        while True:
            orders.append(await arrived.get())
            changed.fire()

    @app.on_startup
    def start() -> None:
        listening.append(app.spawn(listen(), "listening for orders"))

    t = TestApp(app)
    async with t.open("/") as ada:
        arrived.put_nowait("an order from elsewhere")
        await asyncio.sleep(0)
        await ada.settle()
        assert shown(ada) == "an order from elsewhere"
    task = listening[0]
    assert task is not None and not task.done()
    await t.shutdown()
    assert task.cancelled()


async def test_spawned_work_has_stopped_when_the_shutdown_hooks_run() -> None:
    app, _, _, _ = make_app()
    said: list[str] = []

    async def listen() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            said.append("the listener let go of the pool")

    @app.on_startup
    def start() -> None:
        app.spawn(listen(), "listening")

    @app.on_shutdown
    def close_pool() -> None:
        said.append("the pool is closed")

    t = TestApp(app)
    async with t.open("/"):
        pass
    await t.shutdown()
    assert said == ["the listener let go of the pool", "the pool is closed"]


def test_work_is_spawned_once_the_app_runs() -> None:
    app, _, _, _ = make_app()

    async def listen() -> None:
        pass

    with pytest.raises(RuntimeError, match=r"@app\.on_startup"):
        app.spawn(listen())


async def test_what_fired_while_a_page_did_not_come_is_drawn_when_the_session_is_back() -> None:
    app = mw.App("orders", state=State, public=None)
    changed = mw.Signal()
    orders: list[str] = []
    door = asyncio.Event()

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text(", ".join(orders) or "no orders", key="orders"))

    @home.connect
    def follow(s: mw.Session[State]) -> None:
        s.follow(changed)

    @app.page("/shut")
    def shut(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("never", key="t"))

    @shut.connect
    async def no_way_in(s: mw.Session[State]) -> None:
        await door.wait()
        raise RuntimeError("the door is shut")

    async with TestApp(app, strict=False).open("/") as cy:
        # The tab asks for the other page itself, so no handler's end draws
        # the page it comes back to.
        cy.session.navigate("/shut")
        for _ in range(20):
            await asyncio.sleep(0)
        assert not cy.session.ready
        orders.append("order 1")
        changed.fire()
        door.set()
        await cy.settle()
        assert cy.session.path == "/" and shown(cy) == "order 1"
