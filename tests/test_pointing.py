"""Naming a component by its key or its id, and what is asked of one by
name: the keyboard, a reset."""

import logging
from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.testing import TestApp


class State(BaseModel):
    adding: bool = False
    n: int = 0


def make_app() -> mw.App:
    app = mw.App("orders", state=State, public=None)

    def open_dialog(s: mw.Session[State], _: Any) -> None:
        s.state.adding = True
        s.focus("amount")

    def stay(s: mw.Session[State], _: Any) -> None:
        s.focus("scan")

    def twice(s: mw.Session[State], _: Any) -> None:
        s.focus("first")
        s.focus("scan")

    def card(s: mw.Session[State], _: Any) -> None:
        s.focus("open")

    def nowhere(s: mw.Session[State], _: Any) -> None:
        s.focus("scna")

    def leave(s: mw.Session[State], _: Any) -> None:
        s.focus("scan")
        s.print()
        s.navigate("/other")

    def go(s: mw.Session[State], _: Any) -> None:
        s.navigate("/other")
        s.focus("scan")

    def try_the_door(s: mw.Session[State], _: Any) -> None:
        s.navigate("/shut")
        s.focus("scan")

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Input(key="first"),
            ui.Input(key="scan"),
            ui.Button("Open", key="new", on_click=open_dialog),
            ui.Button("Stay", key="stay", on_click=stay),
            ui.Button("Twice", key="twice", on_click=twice),
            ui.Button("Card", key="card", on_click=card),
            ui.Button("Nowhere", key="nowhere", on_click=nowhere),
            ui.Button("Leave", key="leave", on_click=leave),
            ui.Button("Go", key="go", on_click=go),
            ui.Button("Try", key="try", on_click=try_the_door),
            ui.Card(ui.Button("Open", key="open"), key="one"),
            ui.Card(ui.Button("Open", key="open"), key="two"),
            ui.Dialog(
                ui.Input(key="amount"),
                open=s.state.adding,
                footer=ui.Button("Save", key="save"),
                key="dlg",
            ),
        )

    @home.connect
    def start(s: mw.Session[State]) -> None:
        s.focus("scan")
        s.print()

    @app.page("/other")
    def other(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Input(key="scan"))

    @app.page("/shut")
    def shut(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Input(key="scan"))

    @shut.connect
    def no_way_in(s: mw.Session[State]) -> None:
        s.focus("scan")
        raise RuntimeError("the door is shut")

    return app


def sent(page: Any) -> list[tuple[str, Any]]:
    """What went to the tab, in order: each drawing, and each command that
    is for a component or for the page."""
    out: list[tuple[str, Any]] = []
    for message in page.messages:
        if message.type in ("mount", "patch"):
            out.append((message.type, None))
        elif message.type == "command" and message.name in ("focus", "print", "reset"):
            out.append((message.name, message.args.get("id") or message.args.get("ids")))
    return out


async def test_a_name_is_a_key_or_an_id_and_a_key_names_all_that_have_it() -> None:
    async with TestApp(make_app()).open("/") as page:
        s = page.session
        assert s.named("scan") == ["root/scan"]
        assert s.named("root/scan") == ["root/scan"]
        assert s.named("open") == ["root/one/open", "root/two/open"]
        assert s.named("nope") == []
        # The end of an id, from a slash on, picks one of several.
        assert s.named("two/open") == ["root/two/open"]
        assert page.find("two/open").id == "root/two/open"
        # A component in a slot has the slot's name at the end of its id,
        # and is found by its key all the same.
        assert s.named("save") == ["root/dlg/@footer"]


async def test_a_reset_reaches_a_component_in_a_slot() -> None:
    async with TestApp(make_app()).open("/") as page:
        page.session.reset("save")
        page.session.reset("open")
        page.session.reset("nope")
        await page.settle()
        assert [ids for name, ids in sent(page) if name == "reset"] == [
            ["root/dlg/@footer"],
            ["root/one/open", "root/two/open"],
            [],
        ]


async def test_what_a_connect_hook_asks_for_follows_the_page() -> None:
    async with TestApp(make_app()).open("/") as page:
        assert sent(page) == [("mount", None), ("focus", "root/scan"), ("print", None)]


async def test_the_keyboard_goes_to_a_field_of_the_dialog_the_handler_opened() -> None:
    async with TestApp(make_app()).open("/") as page:
        before = len(sent(page))
        await page.click("new")
        # The field is on the page with the patch, and the order follows it.
        assert sent(page)[before:] == [("patch", None), ("focus", "root/dlg/amount")]


async def test_the_keyboard_is_asked_for_also_when_nothing_was_drawn() -> None:
    async with TestApp(make_app()).open("/") as page:
        before = len(sent(page))
        await page.click("stay")
        assert sent(page)[before:] == [("focus", "root/scan")]


async def test_the_last_one_asked_for_gets_the_keyboard_and_the_first_of_several() -> None:
    async with TestApp(make_app()).open("/") as page:
        before = len(sent(page))
        await page.click("twice")
        await page.click("card")
        assert sent(page)[before:] == [("focus", "root/scan"), ("focus", "root/one/open")]


async def test_a_name_that_is_nothing_on_the_page_is_said_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with TestApp(make_app()).open("/") as page:
        before = len(sent(page))
        with caplog.at_level(logging.WARNING, logger="millwork"):
            await page.click("nowhere")
            await page.click("nowhere")
        assert sent(page)[before:] == []
        said = [r.getMessage() for r in caplog.records if "s.focus('scna')" in r.getMessage()]
        assert len(said) == 1 and "names nothing on the page" in said[0]


async def test_what_was_asked_of_a_page_is_not_asked_of_the_next() -> None:
    async with TestApp(make_app()).open("/") as page:
        before = len(sent(page))
        await page.click("leave")
        assert page.session.path == "/other"
        # The other page has a field with the same key. It was not meant.
        assert sent(page)[before:] == [("mount", None)]


async def test_the_keyboard_asked_for_after_another_page_is_for_that_page() -> None:
    async with TestApp(make_app()).open("/") as page:
        before = len(sent(page))
        await page.click("go")
        assert page.session.path == "/other"
        assert sent(page)[before:] == [("mount", None), ("focus", "root/scan")]


async def test_the_keyboard_asked_for_in_a_page_that_does_not_come_is_dropped() -> None:
    async with TestApp(make_app(), strict=False).open("/") as page:
        before = len(sent(page))
        await page.click("try")
        # The handler asked for it in the other page, and so did that
        # page's connect hook before it failed. The page the session stays
        # on has a field of that name, which was not meant.
        assert page.session.path == "/"
        await page.click("nowhere")
        assert [name for name, _ in sent(page)[before:]] == []


async def test_a_field_says_that_the_keyboard_starts_in_it() -> None:
    app = mw.App("t", public=None)

    @app.page("/")
    def home(s: mw.Session[Any]) -> ui.Component:
        return ui.Page(
            ui.Input(key="code", autofocus=True),
            ui.Textarea(key="note", autofocus=True),
            ui.NumberInput(key="amount", autofocus=True),
            ui.Input(key="plain"),
        )

    async with TestApp(app).open("/") as page:
        assert [page.find(k).props["autofocus"] for k in ("code", "note", "amount", "plain")] == [
            True,
            True,
            True,
            False,
        ]
