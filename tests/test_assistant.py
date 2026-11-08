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
        for _ in range(20):
            await page.click(add)
        assert len(page.session.state.board.notes) == 12
        add = next(b for b in page.find_all(ui.Button) if b.props.get("label") == "Add a note")
        assert add.props.get("disabled") is True
        title = next(c for c in page.find_all(ui.Input) if c.props.get("placeholder") == "Title")
        assert title.props["max_length"] == 80
