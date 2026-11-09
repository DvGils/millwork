"""Small things an app ran into: a custom component's class, a plain meter,
the tone of a toast in a test."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.testing import Notice, TestApp


def test_a_custom_prop_may_not_take_the_components_own_names() -> None:
    with pytest.raises(ValueError, match="named \\['cls'\\]"):
        ui.Custom("Pond", props={"cls": "x", "fish": 3})
    with pytest.raises(ValueError, match="on_event"):
        ui.Custom("Pond", props={"on_event": 1})
    ui.Custom("Pond", props={"name": "a prop of its own", "children": 2})
    pond = ui.Custom("Pond", props={"fish": 3}, cls="lg:col-span-2", hidden=False)
    node = mw.nodes.build(pond).nodes["root"]
    assert node.props["cls"] == "lg:col-span-2" and node.props["fish"] == 3


def test_a_progress_bar_can_be_a_plain_meter() -> None:
    meter = mw.nodes.build(ui.Progress(value=0.4, label="Energy", percent=False)).nodes["root"]
    assert meter.props["percent"] is False
    assert mw.nodes.build(ui.Progress(value=0.4)).nodes["root"].props["percent"] is True


async def test_the_harness_shows_each_toasts_tone(tmp_path: Path) -> None:
    app = mw.App("t", public=None, bundle_dir=tmp_path)

    async def warn(s: mw.Session, _: Any) -> None:
        s.toast("Careful.", tone="warning", title="Pond")
        s.toast("Fine.")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Button("go", key="go", on_click=warn))

    async with TestApp(app).open("/") as page:
        await page.click("go")
        assert page.toasts == ["Careful.", "Fine."]
        assert page.notices == [Notice("Careful.", "warning", "Pond"), Notice("Fine.", "default")]


def test_a_sidebar_group_has_one_owner_of_its_open_state() -> None:
    from millwork import ui

    group = ui.SidebarGroup(ui.Link(label="A", href="/a"), label="Part", default_open=False)
    assert group.default_open is False and group.label == "Part"
    with pytest.raises(ValueError):
        ui.SidebarGroup(label="Part", open=True, default_open=True)


def test_a_text_field_says_whether_the_browser_checks_its_spelling() -> None:
    assert ui.Input().spellcheck is None and ui.Textarea().spellcheck is None
    assert ui.Input(spellcheck=False).spellcheck is False
    assert ui.Textarea(spellcheck=True).spellcheck is True


def test_a_stat_takes_any_numbers_as_its_trend() -> None:
    whole: list[int] = [1, 2, 3]
    assert ui.Stat(label="Releases", value="3", trend=whole).trend == [1, 2, 3]
    assert ui.Stat(label="Releases", value="3", trend=(0.5, 1.5)).trend == [0.5, 1.5]
    # What is not a sequence is taken as well, and held as a list.
    assert ui.Stat(label="Releases", value="3", trend=(n for n in whole)).trend == [1, 2, 3]
    assert ui.Stat(label="Releases", value="3", trend={"a": 1, "b": 2}.values()).trend == [1, 2]


class _Shaky(BaseModel):
    broken: bool = True
    opened: int = 0


def _shaky_app(debug: bool = False) -> mw.App:
    app = mw.App("shaky", state=_Shaky, public=None, components=None, debug=debug)

    @app.page("/")
    def home(s: mw.Session[_Shaky]) -> ui.Component:
        return ui.Page(ui.Button("Open", key="open", on_click=lambda s, _: s.navigate("/shaky")))

    @app.page("/shaky")
    def shaky(s: mw.Session[_Shaky]) -> ui.Component:
        s.state.opened += 1
        if s.state.broken:
            raise RuntimeError("the database is away")
        return ui.Page(ui.Text("All is well", key="well"))

    return app


async def test_a_page_that_raises_before_anything_is_shown_gets_a_failure_page() -> None:
    async with TestApp(_shaky_app(), strict=False).open("/shaky") as page:
        assert [type(exc) for _, exc in page.failures] == [RuntimeError]
        assert "Something went wrong" in page.text() and "could not be shown" in page.text()
        # The exception is the author's to read, in debug mode only.
        assert "database" not in page.text()
        assert not any(getattr(m, "type", None) == "error" for m in page.messages)

        # Trying again while it still fails says so, and the page stays.
        await page.click("retry")
        assert getattr(page.messages[-1], "type", None) == "error"
        assert "Something went wrong" in page.text()

        # Once the page function works, its page takes the failure page's place.
        page.session.state.broken = False
        await page.click("retry")
        assert page.text() == "All is well"


async def test_a_navigation_to_a_page_that_raises_lands_on_the_failure_page() -> None:
    async with TestApp(_shaky_app(debug=True), strict=False).open("/") as page:
        await page.click("open")
        assert page.session.path == "/shaky"
        text = page.text()
        assert "Something went wrong" in text and "RuntimeError: the database is away" in text
        # From anywhere but the home page there is a way home.
        await page.click("home")
        assert page.session.path == "/" and page.find(ui.Button).props["label"] == "Open"


async def test_a_page_that_works_again_is_mounted_over_the_failure_page() -> None:
    app = mw.App("flat", state=_Shaky, public=None, components=None, debug=True)

    @app.page("/")
    def flat(s: mw.Session[_Shaky]) -> ui.Component:
        if s.state.broken:
            raise RuntimeError("away")
        return ui.Page(ui.Text("a"), ui.Text("b"), ui.Text("c"), ui.Text("d"))

    async with TestApp(app, strict=False).open("/") as page:
        page.session.state.broken = False
        seen = len(page.messages)
        await page.click("retry")
        kinds = [getattr(m, "type", None) for m in page.messages[seen:]]
        # A mount, so the tab starts the page as it starts any page, and
        # nothing is compared with the failure page's rows.
        assert "mount" in kinds and "patch" not in kinds
        assert not page.session._warned and not page.toasts


class _Mute(Exception):
    def __str__(self) -> str:
        raise RuntimeError("cannot say")


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (ValueError("cannot read caf\udce9.txt"), "ValueError: cannot read caf\\udce9.txt"),
        (_Mute(), "_Mute"),
        (RuntimeError("x" * 5000), "RuntimeError: " + "x" * 1986),
    ],
)
async def test_the_failure_page_shows_whatever_was_raised(error: Exception, shown: str) -> None:
    app = mw.App("odd", public=None, components=None, debug=True)

    @app.page("/")
    def odd(s: mw.Session[Any]) -> ui.Component:
        raise error

    async with TestApp(app, strict=False).open("/") as page:
        assert not page.session.over
        assert page.find(ui.Code).props["content"] == shown


async def test_a_failed_render_keeps_nothing_of_the_call_alive() -> None:
    import gc
    import logging
    import weakref

    class Rows:
        pass

    seen: list[weakref.ref[Rows]] = []
    app = _shaky_app()

    @app.page("/heavy")
    def heavy(s: mw.Session[_Shaky]) -> ui.Component:
        rows = Rows()
        seen.append(weakref.ref(rows))
        raise RuntimeError("away")

    async with TestApp(app, strict=False).open("/") as page:
        # The harness keeps what was raised, for the test to read, and the
        # test runner keeps the log record of it. A running app keeps neither.
        page.session.on_failure = None
        logging.disable(logging.CRITICAL)
        try:
            page.session.navigate("/heavy")
            await page.settle()
        finally:
            logging.disable(logging.NOTSET)
        assert "Something went wrong" in page.text()
        gc.collect()
        assert seen and seen[-1]() is None
