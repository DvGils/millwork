"""The manual: every page loads, every live block runs, state survives events."""

from pathlib import Path

import pytest

from millwork import ui
from millwork.manual import load, make_app, parse
from millwork.testing import TestApp


def test_pages_parse_into_prose_and_live_blocks() -> None:
    pages = load()
    assert [p.slug for p in pages][:3] == ["/", "/app/pages", "/app/state"]
    index = pages[0]
    assert index.title == "Welcome" and index.chapter == ""
    live = [s for s in index.segments if not isinstance(s, str)]
    assert len(live) == 2 and live[0].tail is not None and live[1].tail is None
    with pytest.raises(ValueError, match="neither defines"):
        parse("```python live\nx = 1\n```\n", "/t")


@pytest.mark.parametrize("slug", [p.slug for p in load()])
async def test_every_page_renders_without_a_failed_example(slug: str, tmp_path: Path) -> None:
    app = make_app()
    app.bundle_dir = tmp_path
    async with TestApp(app).open(slug) as page:
        assert "This example failed" not in page.text()
        assert page.find_all(ui.Code)  # each page shows at least one source block


async def test_a_live_block_keeps_its_state_across_events(tmp_path: Path) -> None:
    app = make_app()
    app.bundle_dir = tmp_path
    async with TestApp(app).open("/") as page:
        assert "Clicked 0 times." in page.text()
        buttons = page.find_all(ui.Button)
        add = next(b for b in buttons if b.props.get("label") == "Add one")
        await page.click(add)
        await page.click(add)
        assert "Clicked 2 times." in page.text()
        hello = next(b for b in buttons if b.props.get("label") == "Say hello")
        await page.click(hello)
        assert page.toasts[-1] == "Hello from Python."


def test_every_catalogue_component_has_a_live_example() -> None:
    """The manual is the gallery: a component without a live block is a gap."""
    import re

    from millwork.nodes import Component

    exempt = {"Page", "Sidebar", "Header", "Component"}  # the manual's own frame
    live = "\n".join(
        seg.source for page in load() for seg in page.segments if not isinstance(seg, str)
    )
    used = set(re.findall(r"ui\.([A-Z]\w+)\(", live))
    names = {
        n
        for n in ui.__all__
        if isinstance(getattr(ui, n), type)
        and issubclass(getattr(ui, n), Component)
        and n not in exempt
    }
    assert names - used == set()


def test_search_finds_the_section_a_reader_means() -> None:
    from millwork.manual import index, search, slugify

    sections = index(load())
    assert (
        slugify("RadioGroup, CheckboxGroup and ToggleGroup")
        == "radiogroup-checkboxgroup-and-togglegroup"
    )
    top = search(sections, "combobox")[0].section
    assert top.heading == "Combobox" and top.page.slug == "/components/inputs"
    assert top.anchor == "combobox"
    # Every word must match; a heading beats prose; code counts last.
    hits = search(sections, "upload reject")
    assert hits and hits[0].section.heading == "FileUpload"
    assert search(sections, "zzqx") == []
    confirm = search(sections, "confirm dialog")[0].section
    assert confirm.heading == "Confirm and ask"


async def test_the_search_box_lists_hits_and_enter_opens_the_first(tmp_path: Path) -> None:
    app = make_app()
    app.bundle_dir = tmp_path
    async with TestApp(app).open("/") as page:
        box = page.find(ui.Input)
        await page.change(box, "datepicker")
        links = [n.props["href"] for n in page.find_all(ui.Link) if n.props["href"].startswith("/")]
        assert links[0] == "/components/inputs#datepicker"
        await page.event(box, "submit", "datepicker")
        await page.settle()
        nav = [c for c in page.commands if c.name == "navigate"]
        assert nav and nav[-1].args["path"] == "/components/inputs"
        assert nav[-1].args["hash"] == "datepicker"


async def test_block_state_belongs_to_the_session_that_acts(tmp_path: Path) -> None:
    """Two tabs on the same page share the block's namespace, not its state."""
    from millwork.manual import make_app
    from millwork.testing import TestApp

    app = make_app()
    async with (
        TestApp(app).open("/components/chat") as one,
        TestApp(app).open("/components/chat") as two,
    ):
        await one.event("rated", "message", {"text": "mine", "files": [], "command": None})
        reply = one.session.chat("rated").messages[-1]
        await one.event("rated", "feedback", {"id": reply.id, "value": "up", "comment": None})
        assert "up: You said: mine" in one.text()
        assert "up: You said: mine" not in two.text()
