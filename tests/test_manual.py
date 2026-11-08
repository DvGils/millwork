"""The manual: every page loads, every live block runs, state survives events."""

from pathlib import Path

import pytest

from millwork import ui
from millwork.manual import load, make_app, parse
from millwork.testing import TestApp


def test_pages_parse_into_prose_and_live_blocks() -> None:
    from millwork.manual import Cards, Live

    pages = load()
    assert [p.slug for p in pages][:3] == ["/", "/quickstart", "/pages/pages-and-routes"]
    index = pages[0]
    assert index.title == "Welcome" and index.chapter == "" and index.group == ""
    live = [s for s in index.segments if isinstance(s, Live)]
    assert len(live) == 2 and live[0].tail is not None and live[1].tail is None
    cards = [s for s in index.segments if isinstance(s, Cards)]
    assert cards and cards[0].slugs[0] == "/quickstart"
    assert cards[0].titles["/components/layout"] == "Components"
    sessions = next(p for p in pages if p.slug == "/pages/sessions")
    assert sessions.group == "pages" and sessions.chapter == "Pages"
    assert sessions.description and "/state/state-and-the-loop" in sessions.related
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


async def test_the_sidebar_folds_groups_and_the_pages_lead_on(tmp_path: Path) -> None:
    """Groups fold to their label, the current one open; a page ends with its
    neighbors and its related pages as cards that navigate."""
    app = make_app()
    app.bundle_dir = tmp_path
    async with TestApp(app).open("/pages/sessions") as page:
        groups = page.find_all(ui.SidebarGroup)
        by_label = {g.props["label"]: g for g in groups}
        assert set(by_label) == {"Pages", "State", "Sign-in", "Running", "Components"}
        assert by_label["Pages"].props["open"] is True
        assert by_label["State"].props["open"] is False
        titles = [page.tree[c].props["label"] for c in by_label["Pages"].children]
        assert titles[0] == "Pages and routes" and "Sessions" in titles and len(titles) == 6
        # the reader folds Pages and opens State; the choice is kept in the session
        await page.event(by_label["Pages"], "toggle", False)
        await page.event(page.find_all(ui.SidebarGroup)[1], "toggle", True)
        groups = {g.props["label"]: g for g in page.find_all(ui.SidebarGroup)}
        assert groups["Pages"].props["open"] is False and groups["State"].props["open"] is True
        # the way on: the next page of the group, and the related cards
        links = [n.props for n in page.find_all(ui.Link)]
        assert any(
            x["label"] == "Beyond pages" and x["href"] == "/pages/beyond-pages" for x in links
        )
        assert any(x["label"] == "Missing and forbidden pages" for x in links)
        cards = [c for c in page.find_all(ui.Card) if c.props.get("on_click")]
        assert "State and the loop" in [c.props["title"] for c in cards]
        await page.click(next(c for c in cards if c.props["title"] == "Tasks"))
        await page.settle()
        nav = [c for c in page.commands if c.name == "navigate"]
        assert nav[-1].args["path"] == "/components/tasks"
        # arriving in a folded group opens it
        assert {g.props["label"]: g.props["open"] for g in page.find_all(ui.SidebarGroup)}[
            "Components"
        ] is True


def test_old_chapter_addresses_redirect(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    app = make_app()
    app.bundle_dir = tmp_path
    with TestClient(app.asgi) as client:
        r = client.get("/app/auth", follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == "/sign-in/turning-it-on"


def test_a_card_or_relation_to_a_page_that_is_not_there_is_refused(tmp_path: Path) -> None:
    (tmp_path / "index.md").write_text("---\ntitle: Home\n---\n\n```cards\n/nowhere\n```\n")
    with pytest.raises(ValueError, match="card for /nowhere"):
        load(tmp_path)
    (tmp_path / "index.md").write_text("---\ntitle: Home\nrelated: /gone\n---\n\nText.\n")
    with pytest.raises(ValueError, match="relates to /gone"):
        load(tmp_path)


def test_every_catalogue_component_has_a_live_example() -> None:
    """The manual is the gallery: a component without a live block is a gap."""
    import re

    from millwork.nodes import Component

    # The manual's own frame, and SignIn, which needs an app with auth to draw.
    exempt = {"Page", "Sidebar", "Header", "Component", "SignIn"}
    from millwork.manual import Live

    live = "\n".join(
        seg.source for page in load() for seg in page.segments if isinstance(seg, Live)
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
