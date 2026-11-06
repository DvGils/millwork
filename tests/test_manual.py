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

    # The manual's own frame, and SignIn, which needs an app with auth to draw.
    exempt = {"Page", "Sidebar", "Header", "Component", "SignIn"}
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
        # Each session's blocks live in a module of their own, dropped on close.
        import sys

        from millwork.manual import live_module_name

        names = [live_module_name("/components/chat", s.id) for s in (one.session, two.session)]
        assert all(n in sys.modules for n in names)
    assert not any(n in sys.modules for n in names)


async def test_every_live_block_renders(tmp_path: Path) -> None:
    """Every example on every page runs, and none shows the failure alert."""
    app = make_app()
    app.bundle_dir = tmp_path
    for page_def in load():
        async with TestApp(app).open(page_def.slug) as page:
            failed = [
                a for a in page.find_all(ui.Alert) if a.props.get("title") == "This example failed"
            ]
            assert not failed, (page_def.slug, [a.props.get("description") for a in failed])


def test_the_manuals_state_is_composed_from_its_examples() -> None:
    from millwork.manual import field_name, state_model

    State = state_model(load())  # noqa: N806
    assert {"query", "counter", "clicks", "todo", "board"} <= set(State.model_fields)
    assert "signup" not in State.model_fields  # a form model with required fields is not state
    assert field_name("EditorState") == "editor_state"
    one, two = State(), State()
    one.counter.n = 3
    assert two.counter.n == 0


def test_load_skips_a_broken_block_and_refuses_a_renamed_model(tmp_path: Path) -> None:
    from millwork.manual import Page, parse, state_model

    def page(slug: str, *blocks: str) -> Page:
        text = "\n\n".join(f"```python live\n{b}\n```" for b in blocks) + "\n"
        _, segments = parse(text, slug)
        return Page(slug=slug, title=slug, chapter="", order=1, segments=segments)

    model = "from pydantic import BaseModel\n\nclass Held(BaseModel):\n    n: int = 0\n"
    broken = page("/a", "raise RuntimeError('needs the network')\n\nui.Text('never')")
    fine = page("/b", model + "\nui.Text(str(s.state.held.n))")
    State = state_model([broken, fine])  # noqa: N806
    assert "held" in State.model_fields
    twice = page(
        "/c", model + "\nui.Text('x')", "class Held(BaseModel):\n    other: int = 0\n\nui.Text('y')"
    )
    with pytest.raises(ValueError, match="Held is defined with different fields"):
        state_model([twice])
    query = (
        "from pydantic import BaseModel\n\nclass Query(BaseModel):\n    q: str = ''\n\nui.Text('z')"
    )
    with pytest.raises(ValueError, match="may not be named Query"):
        state_model([page("/d", query)])
