"""The floating button and the assistant: the models, and the manual's examples."""

from pathlib import Path

import pytest

from millwork import ui
from millwork.manual import make_app
from millwork.testing import TestApp


def test_the_assistant_and_floating_models() -> None:
    a = ui.Assistant(ui.Text("hi"), label="Ask", side="left")
    assert a.side == "left" and a.draggable is True and a.open is None
    with pytest.raises(ValueError):
        ui.Assistant(open=True, default_open=False)
    with pytest.raises(ValueError, match="no icon named"):
        ui.Assistant(icon="no-such-icon")
    f = ui.Floating(ui.Badge("x"), draggable=True)
    assert f.draggable is True and f.side == "right"
    assert a.pinned is False
    assert ui.Assistant(pinned=True).pinned is True


async def test_the_manual_adds_an_assistant_that_searches_it(tmp_path: Path) -> None:
    app = make_app()
    app.bundle_dir = tmp_path
    async with TestApp(app).open("/components/chat") as page:
        assert not page.find_all(ui.Assistant)
        add = next(
            b
            for b in page.find_all(ui.Button)
            if b.props.get("label") == "Add an assistant to this page"
        )
        await page.click(add)
        assistant = page.find(ui.Assistant)
        assert assistant.props["label"] == "Ask the manual"
        chat = next(c for c in page.find_all(ui.Chat) if "helper" in c.id)
        assert chat.id.startswith(assistant.id)
        await page.event(
            "helper", "message", {"text": "sidebar group", "files": [], "command": None}
        )
        reply = page.session.chat("helper").messages[-1].text
        assert "Sidebar" in reply and "/components/layout#sidebar" in reply
        gone = next(
            b for b in page.find_all(ui.Button) if b.props.get("label") == "Take the assistant away"
        )
        await page.click(gone)
        assert not page.find_all(ui.Assistant)


async def test_the_manual_pins_a_badge(tmp_path: Path) -> None:
    app = make_app()
    app.bundle_dir = tmp_path
    async with TestApp(app).open("/components/layout") as page:
        pin = next(
            b
            for b in page.find_all(ui.Button)
            if b.props.get("label") == "Pin a badge to this page"
        )
        await page.click(pin)
        floating = page.find(ui.Floating)
        assert floating.props["draggable"] is True and floating.props["side"] == "left"


async def test_the_notes_example_has_a_bound(tmp_path: Path) -> None:
    """A visitor cannot grow the manual's list without end."""
    app = make_app()
    app.bundle_dir = tmp_path
    async with TestApp(app).open("/state/lists-and-keys") as page:
        add = next(b for b in page.find_all(ui.Button) if b.props.get("label") == "Add a note")
        while len(page.session.state.board.notes) < 12:
            await page.click(add)
        add = next(b for b in page.find_all(ui.Button) if b.props.get("label") == "Add a note")
        assert add.props.get("disabled") is True
        # The button is off, and a click a tab could not send adds nothing.
        with pytest.raises(LookupError, match="is disabled"):
            await page.click(add)
        assert len(page.session.state.board.notes) == 12
        title = next(c for c in page.find_all(ui.Input) if c.props.get("placeholder") == "Title")
        assert title.props["max_length"] == 80


async def test_the_assistant_says_when_a_chat_in_it_is_making_a_reply(tmp_path: Path) -> None:
    import asyncio

    import millwork as mw
    from millwork.nodes import build

    app = mw.App("busy", public=None, bundle_dir=tmp_path)
    release = asyncio.Event()
    drawn_busy = asyncio.Event()

    async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
        await release.wait()
        async with turn.reply() as reply:
            await reply.text("done")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        if s.chat("inside").busy or s.chat("beside").busy:
            drawn_busy.set()
        return ui.Page(
            # However deep in the window the chat is.
            ui.Assistant(ui.Stack(ui.Chat(key="inside", on_message=answer)), key="helper"),
            ui.Chat(key="beside", on_message=answer),
        )

    async with TestApp(app).open("/") as page:
        assert page.find("helper").props["busy"] is False
        for chat, busy in (("inside", True), ("beside", False)):
            sent = asyncio.ensure_future(page.send(chat, "hello"))
            await asyncio.wait_for(drawn_busy.wait(), 5)
            # A chat beside the assistant is none of its business.
            assert page.find("helper").props["busy"] is busy
            release.set()
            await sent
            assert page.find("helper").props["busy"] is False
            release.clear()
            drawn_busy.clear()

    # Outside a session there is no chat to ask.
    assert build(ui.Assistant(ui.Chat(key="c"))).nodes["root"].props["busy"] is False


def test_a_chat_says_how_it_waits() -> None:
    from millwork.nodes import build

    assert build(ui.Chat(key="c", waiting="dots")).nodes["root"].props["waiting"] == "dots"
    with pytest.raises(ValueError):
        ui.Chat(key="c", waiting="spinner")
