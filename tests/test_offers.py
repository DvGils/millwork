"""A handler gets what its component could have sent, and a component that
is closed or hidden gets nothing at all."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.testing import TestApp


class State(BaseModel):
    got: list[Any] = []
    opened: bool = False
    veiled: bool = True


def take(s: mw.Session[State], value: Any) -> None:
    s.state.got = [*s.state.got, value]


def opened(s: mw.Session[State], _: object) -> None:
    s.state.opened = True


def shown(s: mw.Session[State], _: object) -> None:
    s.state.veiled = False


def found(s: mw.Session[State], text: str) -> list[str]:
    take(s, text)
    return ["found"]


def app_of(tmp_path: Path) -> mw.App:
    app = mw.App("offers", state=State, public=None, bundle_dir=tmp_path)
    (tmp_path / "components").mkdir(exist_ok=True)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        choices = ["a", ("b", "B"), ui.Option(value="c", disabled=True)]
        return ui.Page(
            ui.Button("Go", on_click=take, key="button"),
            ui.Button("Open the dialog", on_click=opened, key="open"),
            ui.Button("Show what is hidden", on_click=shown, key="show"),
            ui.Switch(on_change=take, key="switch"),
            ui.Collapsible(ui.Text("in"), title="More", on_toggle=take, key="fold"),
            ui.Select(options=choices, on_change=take, key="select"),
            ui.Select(options=choices, value="gone", on_change=take, key="select-held"),
            ui.RadioGroup(options=choices, on_change=take, key="radio"),
            ui.ToggleGroup(options=choices, on_change=take, key="toggle"),
            ui.ToggleGroup(options=choices, multiple=True, on_change=take, key="toggles"),
            ui.CheckboxGroup(options=choices, value=["gone"], on_change=take, key="checks"),
            ui.MultiSelect(options=["a", "b", "d"], max=2, on_change=take, key="multi"),
            ui.Combobox(options=["a"], on_change=take, key="combo"),
            ui.Combobox(options=["a"], on_change=take, on_search=found, key="combo-search"),
            ui.Combobox(options=["a"], allow_custom=True, on_change=take, key="combo-own"),
            ui.DropdownMenu(
                trigger=ui.Button("Menu"),
                items=[
                    ui.MenuItem(id="open", label="Open"),
                    ui.MenuItem(id="off", label="Off", disabled=True),
                ],
                on_select=take,
                key="menu",
            ),
            ui.Tabs(
                ui.Tab(ui.Text("1"), id="one", label="One"),
                ui.Tab(ui.Text("2"), id="two", label="Two", disabled=True),
                ui.Tab(ui.Text("3"), id="three", label="Three", hidden=True),
                on_change=take,
                key="tabs",
            ),
            ui.Accordion(
                ui.AccordionItem(ui.Text("1"), id="one", title="One"),
                ui.AccordionItem(ui.Text("2"), id="two", title="Two"),
                on_change=take,
                key="accordion",
            ),
            ui.Input(max_length=5, on_change=take, on_submit=take, key="input"),
            ui.Input(max_length=5, value="longer than five", on_change=take, key="input-held"),
            ui.Slider(min=10, max=20, on_change=take, key="slider"),
            ui.NumberInput(min=0, max=10, on_change=take, key="number"),
            ui.NumberInput(min=0, max=10, value=500, on_change=take, key="number-held"),
            ui.DatePicker(min="2026-01-01", max="2026-12-31", on_change=take, key="day"),
            ui.DatePicker(min="2026-01-01", range=True, on_change=take, key="days"),
            ui.DatePicker(min="2026-01-01T10:00", on_change=take, key="day-timed"),
            ui.ColorPicker(on_change=take, key="color"),
            ui.ColorPicker(clearable=True, on_change=take, key="color-or-none"),
            ui.Table(
                rows=[{"id": 1, "n": "a"}, {"id": 2, "n": "b"}],
                columns=[ui.Column(key="id"), ui.Column(key="n", sortable=False)],
                selection="rows",
                selected=[7],
                default_sort=[("n", "desc")],
                row_actions=[ui.MenuItem(id="open", label="Open")],
                on_select=take,
                on_row_click=take,
                on_action=take,
                on_sort=take,
                on_filter=take,
                key="table",
            ),
            ui.Table(rows=[{"id": 1}], selection="row", on_select=take, key="table-one"),
            ui.BarChart([{"x": "a", "n": 1}], x="x", y="n", on_click=take, key="chart"),
            ui.Custom("Button", events={"click": take}, key="own"),
            ui.Dialog(
                ui.Button("Save", on_click=take, key="save"),
                ui.Custom("Pond", events={"ping": take}, key="pond"),
                footer=ui.Button("Done", on_click=take, key="done"),
                open=s.state.opened,
                on_close=take,
                key="dialog",
            ),
            ui.Sheet(ui.Button("In", on_click=take, key="in-sheet"), key="sheet"),
            ui.Stack(
                ui.Button("Under", on_click=take, key="under"),
                ui.Custom("Pond", events={"ping": take}, key="running"),
                ui.FileUpload(on_upload=take, key="files"),
                hidden=s.state.veiled,
                key="veil",
            ),
        )

    return app


HEARD = [
    ("button", "click", "anything", None),
    ("switch", "change", True, True),
    ("fold", "toggle", False, False),
    ("select", "change", "b", "b"),
    ("select", "change", None, None),
    # What the page holds can be sent again, also when it is no choice now.
    ("select-held", "change", "gone", "gone"),
    ("radio", "change", "a", "a"),
    ("toggle", "change", None, None),
    ("toggles", "change", ["a", "b"], ["a", "b"]),
    ("toggles", "change", [], []),
    ("checks", "change", ["gone", "a"], ["gone", "a"]),
    ("multi", "change", ["b", "a"], ["b", "a"]),
    ("combo", "change", "a", "a"),
    ("combo-own", "change", "a word of my own", "a word of my own"),
    ("menu", "select", "open", "open"),
    ("tabs", "change", "one", "one"),
    ("accordion", "change", ["two"], ["two"]),
    ("accordion", "change", [], []),
    ("input", "change", "five5", "five5"),
    ("input", "submit", "", ""),
    ("input-held", "change", "longer than fiv", "longer than fiv"),
    ("slider", "change", 20, 20),
    ("slider", "change", 12.5, 12.5),
    ("number", "change", None, None),
    ("number", "change", 10, 10),
    ("number-held", "change", 500, 500),
    ("day", "change", "2026-06-01", "2026-06-01"),
    ("day", "change", None, None),
    ("days", "change", ["2026-06-01", None], ["2026-06-01", None]),
    ("table", "select", [1, 7], [1, 7]),
    # A row the tab still holds and the table has no more is left out.
    ("table", "select", [1, 99], [1]),
    ("toggles", "change", ["a", "zzz"], ["a"]),
    ("accordion", "change", ["nope", "two"], ["two"]),
    # The table's own key comes back, however the tab wrote the number.
    ("table", "row_click", 2.0, 2),
    ("table", "sort", [["nope", "asc"], ["id", "asc"]], [["id", "asc"]]),
    # The order the page starts from can be by a column that is not sorted by hand.
    ("table", "sort", [["n", "desc"], ["id", "asc"]], [["n", "desc"], ["id", "asc"]]),
    (
        "table",
        "filter",
        {"columns": {"nope": "x", "n": "a"}, "search": ""},
        {"columns": {"n": "a"}, "search": ""},
    ),
    ("day-timed", "change", "2026-01-01", "2026-01-01"),
    ("color", "change", "#3b82f6", "#3b82f6"),
    ("color-or-none", "change", None, None),
    ("table", "select", [], []),
    ("table", "row_click", 2, 2),
    ("table", "action", ["open", 1], ["open", 1]),
    ("table", "sort", [["id", "desc"]], [["id", "desc"]]),
    ("table", "sort", [], []),
    (
        "table",
        "filter",
        {"columns": {"n": "a", "id": [1, None]}, "search": "x"},
        {"columns": {"n": "a", "id": [1, None]}, "search": "x"},
    ),
    ("table-one", "select", [1], [1]),
    ("chart", "click", {"x": "a", "series": None}, {"x": "a", "series": None}),
    # A component of the app's own is its handler's to read, whatever it
    # is called.
    ("own", "click", {"any": ["thing"]}, {"any": ["thing"]}),
]


@pytest.mark.parametrize(("node", "name", "sent", "got"), HEARD)
async def test_what_a_component_can_send_reaches_its_handler(
    tmp_path: Path, node: str, name: str, sent: Any, got: Any
) -> None:
    async with TestApp(app_of(tmp_path)).open("/") as page:
        await page.event(node, name, sent)
        assert page.state.got == [got]


REFUSED = [
    ("switch", "change", "yes", "not true or false"),
    ("switch", "change", 1, "not true or false"),
    ("fold", "toggle", None, "not true or false"),
    ("select", "change", "zzz", "not one of its choices"),
    ("select", "change", "c", "not one of its choices"),
    ("select", "change", ["a"], "not text"),
    ("radio", "change", None, "always has a choice"),
    ("toggle", "change", ["a"], "not text"),
    ("toggles", "change", "a", "not a list"),
    ("toggles", "change", ["a", "a"], "a choice twice"),
    ("checks", "change", ["a", 3], "not text"),
    ("multi", "change", ["a", "b", "d"], "it takes 2"),
    ("combo", "change", "zzz", "not one of its choices"),
    ("combo-search", "change", 3, "not text"),
    ("menu", "select", "off", "not one of its choices"),
    ("menu", "select", "nope", "not one of its choices"),
    ("menu", "select", None, "always has a choice"),
    ("tabs", "change", "two", "not a tab that can be chosen"),
    ("tabs", "change", "three", "not a tab that can be chosen"),
    ("accordion", "change", ["one", "two"], "one open at a time"),
    ("input", "change", "six666", "it takes 5"),
    ("input", "change", None, "not text"),
    ("input", "submit", ["x"], "not text"),
    ("input-held", "change", "longer than five!", "it takes 5"),
    ("slider", "change", 21, "outside 10 to 20"),
    ("slider", "change", "12", "not a number"),
    ("slider", "change", True, "not a number"),
    ("slider", "change", None, "not a number"),
    ("slider", "change", float("nan"), "not a number"),
    ("number", "change", 11, "outside 0 to 10"),
    ("number", "change", "3", "not a number"),
    ("day", "change", "2027-01-01", "outside the days it offers"),
    ("day", "change", "tomorrow", "not a day"),
    ("color", "change", "red", "not a color"),
    ("color", "change", "#3B82F6", "not a color"),
    ("color", "change", "#abc", "not a color"),
    ("color", "change", "#3b82f6\n", "not a color"),
    ("color", "change", 255, "not text"),
    ("color", "change", None, "not one to clear"),
    ("day", "change", ["2026-06-01", None], "not text"),
    ("days", "change", "2026-06-01", "not a first and a last day"),
    ("days", "change", ["2025-06-01", None], "outside the days it offers"),
    ("table", "select", [{"id": 1}], "which is no key of a row"),
    ("combo-search", "change", "found", "not one of its choices"),
    ("table", "select", "1", "not a list of rows"),
    ("table", "row_click", None, "which it does not have"),
    ("table", "row_click", {"id": 1}, "which it does not have"),
    ("table", "action", ["nothing", 1], "not one of its actions"),
    ("table", "action", ["open", 99], "which it does not have"),
    ("table", "action", "open", "not an action and a row"),
    ("table", "sort", [["id", "up"]], "not a column and a direction"),
    ("table", "sort", ["id"], "not a column and a direction"),
    ("table", "filter", {"columns": {"n": {"a": 1}}, "search": ""}, "which is no filter"),
    ("table", "filter", ["x"], "not a filter"),
    ("table-one", "select", [1, 1], "one selected at a time"),
    ("chart", "click", "a", "not a place in a chart"),
]


@pytest.mark.parametrize(("node", "name", "sent", "why"), REFUSED)
async def test_what_a_component_cannot_send_is_not_heard(
    tmp_path: Path, node: str, name: str, sent: Any, why: str
) -> None:
    async with TestApp(app_of(tmp_path)).open("/") as page:
        with pytest.raises(LookupError, match=why):
            await page.event(node, name, sent)
        assert page.state.got == []


async def test_what_is_in_a_closed_dialog_takes_nothing(tmp_path: Path) -> None:
    async with TestApp(app_of(tmp_path)).open("/") as page:
        for node in ("save", "dialog/@footer", "in-sheet"):
            with pytest.raises(LookupError, match="is in something closed"):
                await page.click(node)
        # A custom component in it is not drawn either.
        with pytest.raises(LookupError, match="is in something closed"):
            await page.event("pond", "ping")
        with pytest.raises(LookupError, match="is closed"):
            await page.event("dialog", "close")
        assert page.state.got == []
        await page.click("open")
        await page.click("save")
        await page.click("dialog/@footer")
        await page.event("pond", "ping", 3)
        assert page.state.got == [None, None, 3]


async def test_what_is_in_something_hidden_takes_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    async with TestApp(app_of(tmp_path)).open("/") as page:
        with pytest.raises(LookupError, match="is in something hidden"):
            await page.click("under")
        with pytest.raises(LookupError, match="is in something hidden"):
            await page.upload("files", tmp_path / "a.txt")
        assert not list(page.session.files.all())
        # A custom component goes on running where it is not shown.
        await page.event("running", "ping", "still here")
        assert page.state.got == ["still here"]
        await page.click("show")
        await page.click("under")
        await page.upload("files", tmp_path / "a.txt")
        assert len(page.state.got) == 3


async def test_what_a_search_found_is_on_offer(tmp_path: Path) -> None:
    async with TestApp(app_of(tmp_path)).open("/") as page:
        with pytest.raises(LookupError, match="not one of its choices"):
            await page.change("combo-search", "found")
        assert [o["value"] for o in await page.request("combo-search", "search", "fo")] == ["found"]
        await page.change("combo-search", "found")
        assert page.state.got == ["fo", "found"]
        # The same word is no choice of a field whose search did not find it.
        with pytest.raises(LookupError, match="not one of its choices"):
            await page.change("combo", "found")


async def test_a_request_is_held_to_the_same(tmp_path: Path) -> None:
    async with TestApp(app_of(tmp_path)).open("/") as page:
        assert [o["value"] for o in await page.request("combo-search", "search", "fo")] == ["found"]
        with pytest.raises(LookupError, match="takes no 'search' request"):
            await page.request("combo-search", "search", {"not": "text"})
        assert page.state.got == ["fo"]


async def test_a_question_in_a_dialog_is_still_answered(tmp_path: Path) -> None:
    app = mw.App("asks", state=State, public=None, bundle_dir=tmp_path)

    async def ask(s: mw.Session[State], _: object) -> None:
        take(s, await s.confirm("Sure?"))

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("Ask", on_click=ask, key="ask"))

    async with TestApp(app).open("/") as page:
        await page.click("ask")
        await page.answer(True)
        assert page.state.got == [True]


async def test_what_cannot_be_dismissed_takes_no_close(tmp_path: Path) -> None:
    class Name(BaseModel):
        name: str

    app = mw.App("held", state=State, public=None, bundle_dir=tmp_path)

    async def sure(s: mw.Session[State], _: object) -> None:
        take(s, await s.confirm("Sure?", dismissable=False))

    async def name(s: mw.Session[State], _: object) -> None:
        take(s, await s.ask(ui.Dialog(ui.Form(Name), title="Name it", dismissable=False)))

    async def leave(s: mw.Session[State], _: object) -> None:
        form = ui.Form(Name, cancel="Not now")
        take(s, await s.ask(ui.Sheet(form, title="Name it", dismissable=False)))

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("Sure", on_click=sure, key="sure"),
            ui.Button("Name", on_click=name, key="name"),
            ui.Button("Leave", on_click=leave, key="leave"),
            ui.Dialog(ui.Text("Held"), open=True, dismissable=False, on_close=take, key="dialog"),
            ui.Sheet(ui.Text("Held"), open=True, dismissable=False, on_close=take, key="sheet"),
            ui.Dialog(ui.Text("Easy"), open=True, on_close=take, key="easy"),
        )

    async with TestApp(app).open("/") as page:
        # A tab shows no cross on these and sends nothing for Escape.
        for held in ("dialog", "sheet"):
            assert page.find(held).props["dismissable"] is False
            with pytest.raises(LookupError, match="cannot be dismissed"):
                await page.event(held, "close")
        await page.event("easy", "close")
        assert page.state.got == [None]

        # A yes or no that has to be given: only its two buttons answer.
        await page.click("sure")
        with pytest.raises(LookupError, match="cannot be dismissed"):
            await page.answer(None)
        await page.answer(False)
        assert page.state.got == [None, False]

        # A form that has to be filled in: it shows no Cancel, so none is taken.
        await page.click("name")
        with pytest.raises(LookupError, match="cannot be dismissed"):
            await page.answer(None)
        with pytest.raises(LookupError, match="shows no Cancel"):
            await page.event(page.find(ui.Form), "cancel")
        await page.answer({"name": "Kestrel"})
        assert page.state.got[-1] == Name(name="Kestrel")

        # The way out a form was given still is one.
        await page.click("leave")
        await page.event(page.find(ui.Form), "cancel")
        assert page.state.got[-1] is None and len(page.state.got) == 4


async def test_a_form_without_a_cancel_takes_none_in_a_question_either(tmp_path: Path) -> None:
    class Name(BaseModel):
        name: str

    app = mw.App("asks", state=State, public=None, bundle_dir=tmp_path)

    async def ask(s: mw.Session[State], _: object) -> None:
        take(s, await s.ask(ui.Form(Name, cancel="")))

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("Ask", on_click=ask, key="ask"))

    async with TestApp(app).open("/") as page:
        await page.click("ask")
        with pytest.raises(LookupError, match="shows no Cancel"):
            await page.event(page.find(ui.Form), "cancel")
        # The cross of the dialog around it is still a way out.
        await page.answer(None)
        assert page.state.got == [None]


async def test_a_key_past_what_a_tab_can_count_comes_back_whole(tmp_path: Path) -> None:
    big = 2**53 + 1
    got: list[Any] = []
    app = mw.App("big", public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Table(
                rows=[{"id": big}, {"id": 3}],
                selection="rows",
                on_select=lambda s, keys: got.append(keys),
                on_row_click=lambda s, key: got.append(key),
                key="table",
            )
        )

    async with TestApp(app).open("/") as page:
        # A tab reads the key as the float nearest to it and sends that.
        await page.event("table", "row_click", float(big))
        await page.event("table", "select", [float(big), 3.0])
        assert got == [big, [big, 3]]
        assert all(type(key) is int for key in got[1])
