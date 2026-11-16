"""Highlights: marks the session holds for the tab to draw over components."""

import asyncio
import datetime
import json
from typing import Any

import pytest
from pydantic import BaseModel, Field

import millwork as mw
from millwork import marks, outline, ui
from millwork.testing import TestApp


class Address(BaseModel):
    street: str = ""


class Order(BaseModel):
    customer: str = ""
    amount: float = Field(0, ge=0)
    address: Address = Address()


class State(BaseModel):
    adding: bool = False
    extra: bool = False


def make_app() -> mw.App:
    app = mw.App("marks", state=State, public=None)
    app.gate = asyncio.Event()  # type: ignore[attr-defined]

    def do(what: Any) -> Any:
        def handler(s: mw.Session[State], _: Any) -> None:
            what(s)

        return handler

    def tour(s: mw.Session[State]) -> None:
        s.highlight("new", "blue", step=1)
        s.highlight("order/amount", "orange", step=2, style="trace")
        s.highlight("save", step=3)

    def more(s: mw.Session[State]) -> None:
        s.state.extra = True

    def away(s: mw.Session[State]) -> None:
        s.navigate("/settings")
        s.highlight("key", "green")

    async def answer(s: mw.Session[State]) -> None:
        # A reply that takes its time, and points at something when it
        # is done.
        await app.gate.wait()
        s.highlight("export", "red")
        s.highlight("key", "blue", page="/settings")

    def slow(s: mw.Session[State]) -> None:
        s.task(answer, s, label="answer")

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("New", key="new", on_click=do(lambda s: setattr(s.state, "adding", True))),
            ui.Button("Tour", key="tour", on_click=do(tour)),
            ui.Button("More", key="more", on_click=do(more)),
            ui.Button("Away", key="away", on_click=do(away)),
            ui.Button("Slow", key="slow", on_click=do(slow)),
            ui.Text("No field in it", key="plain"),
            ui.Button("Export", key="export"),
            ui.Button("Later", key="later") if s.state.extra else None,
            ui.Link(label="Settings", href="/settings", key="to-settings"),
            ui.Link(label="Shut", href="/shut", key="to-shut"),
            ui.Dialog(
                ui.Form(Order, key="order", submit="Place", on_submit=lambda s, o: None),
                open=s.state.adding,
                title="New order",
                footer=ui.Button("Save", key="save"),
                key="dlg",
            ),
        )

    @app.page("/settings")
    def settings(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Input(key="key"), ui.Button("Export", key="export"))

    @app.page("/other")
    def other(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("Another page"))

    @app.page("/shut")
    def shut(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("Never shown"))

    @shut.connect
    def refuse(s: mw.Session[State]) -> None:
        raise RuntimeError("no way in")

    return app


def brief(found: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Each mark by where it is and how it stands."""
    return [
        (m["id"], m.get("field"), m["color"], m.get("step"), bool(m.get("waits"))) for m in found
    ]


async def test_a_mark_is_given_to_the_tab_with_how_it_looks() -> None:
    async with TestApp(make_app()).open("/") as page:
        assert page.marks == []
        s = page.session
        # Without a color it is blue.
        s.highlight("export")
        await page.settle()
        assert page.marks == [{"n": 1, "id": "root/export", "color": "blue", "style": "solid"}]
        s.highlight("new", "#0A7D5C", style="pulse", seconds=10, label="Here", scroll=True)
        await page.settle()
        assert page.marks[1] == {
            "n": 2,
            "id": "root/new",
            "color": "#0a7d5c",
            "style": "pulse",
            "label": "Here",
            "seconds": 10.0,
            "scroll": True,
        }
        # One mark for a name: a new one takes the old one's place.
        s.highlight("export", "red")
        await page.settle()
        assert brief(page.marks) == [
            ("root/new", None, "#0a7d5c", None, False),
            ("root/export", None, "red", None, False),
        ]
        # Off by name, and all off.
        s.highlight("new", None)
        await page.settle()
        assert [m["id"] for m in page.marks] == ["root/export"]
        s.highlight(None)
        await page.settle()
        assert page.marks == []
        # Nothing is sent that the tab already has.
        sent = len([c for c in page.commands if c.name == "marks"])
        s.highlight("nothing-there", None)
        s.refresh()
        await page.settle()
        assert len([c for c in page.commands if c.name == "marks"]) == sent


@pytest.mark.parametrize(
    "how",
    [
        {"color": "crimson"},
        {"color": "#12"},
        {"color": "red; background: url(x)"},
        {"color": 3},
        {"style": "glow"},
        {"step": 0},
        {"step": True},
        {"step": "1"},
        {"seconds": 0},
        {"seconds": float("nan")},
        {"seconds": "5"},
        {"seconds": 86401},
        {"color": "#0a7d5c; x"},
        {"color": "#0a7d5cff00"},
        {"color": "red "},
        {"label": 5},
        {"page": "settings"},
    ],
)
async def test_what_is_no_mark_is_refused(how: dict[str, Any]) -> None:
    async with TestApp(make_app()).open("/") as page:
        with pytest.raises((ValueError, TypeError)):
            page.session.highlight("export", **how)
        with pytest.raises(TypeError):
            page.session.highlight("")
        assert page.session._marks == []
    for color in marks.PRESETS:
        assert marks.checked(color, "solid", None, None, None, None)[0] == color


async def test_steps_show_one_after_the_other() -> None:
    async with TestApp(make_app()).open("/") as page:
        await page.click("tour")
        form = "root/dlg/order"
        assert brief(page.marks) == [
            ("root/new", None, "blue", 1, False),
            (form, "/amount", "orange", 2, True),
            ("root/dlg/@footer", None, "blue", 3, True),
        ]
        assert page.marks[1]["style"] == "trace"
        # Getting to the first shows the second.
        await page.touch("new")
        assert brief(page.marks) == [
            (form, "/amount", "orange", 2, False),
            ("root/dlg/@footer", None, "blue", 3, True),
        ]
        # Using the component of a later step ends the ones before it.
        await page.click("tour")
        assert [m.get("step") for m in page.marks] == [1, 2, 3]
        await page.touch("save")
        assert page.marks == []
        # A mark without a step shows beside them, and is not ended by them.
        await page.click("tour")
        page.session.highlight("export", "pink")
        await page.settle()
        await page.touch("order/amount")
        assert brief(page.marks) == [
            ("root/dlg/@footer", None, "blue", 3, False),
            ("root/export", None, "pink", None, False),
        ]
        # What the tab says of a mark that is gone changes nothing, nor
        # does what is no number of a mark.
        for said in ({"n": 1, "what": "touched"}, "odd", {"n": True}, {"n": "9"}, {}):
            page.session.event(mw.protocol.Event(node="root/new", name="mark", payload=said))
        await page.settle()
        assert len(page.marks) == 2


async def test_a_step_that_is_nowhere_yet_keeps_the_later_ones_waiting() -> None:
    async with TestApp(make_app()).open("/") as page:
        s = page.session
        s.highlight("later", "blue", step=1)
        s.highlight("export", "red", step=2, label="not shown on a step")
        s.highlight("tour", label="x" * 40)
        await page.settle()
        # The first step has no component yet. The second waits for it all
        # the same, and shows its number, not a label.
        assert page.marks == [
            {
                "n": 2,
                "id": "root/export",
                "color": "red",
                "style": "solid",
                "step": 2,
                "waits": True,
            },
            {"n": 3, "id": "root/tour", "color": "blue", "style": "solid", "label": "x" * 24},
        ]
        await page.click("more")
        assert brief(page.marks)[0] == ("root/later", None, "blue", 1, False)


async def test_a_mark_with_a_time_goes_when_it_runs_out() -> None:
    async with TestApp(make_app()).open("/") as page:
        s = page.session
        s.highlight("new", "blue", step=1, seconds=5)
        s.highlight("export", "red", step=1)
        s.highlight("tour", step=2)
        await page.settle()
        # The one whose time ran out, and not the others of its step.
        await page.time_out("new")
        assert brief(page.marks) == [
            ("root/export", None, "red", 1, False),
            ("root/tour", None, "blue", 2, True),
        ]
        with pytest.raises(LookupError):
            await page.time_out("export")
        with pytest.raises(LookupError):
            await page.touch("new")
        # A time that runs out on a later step ends that mark alone.
        s.highlight("tour", step=2, seconds=5)
        s.highlight("new", "blue", step=1)
        await page.settle()
        late = next(m for m in page.marks if m["id"] == "root/tour")
        said = {"n": late["n"], "what": "timed out"}
        s.event(mw.protocol.Event(node="root/tour", name="mark", payload=said))
        await page.settle()
        assert sorted(m["id"] for m in page.marks) == ["root/export", "root/new"]


async def test_a_mark_waits_for_a_component_that_is_not_there_yet() -> None:
    async with TestApp(make_app()).open("/") as page:
        page.session.highlight("later", "green")
        await page.settle()
        assert page.marks == []
        assert page.outline()["marks_nowhere"] == ["later"]
        await page.click("more")
        assert brief(page.marks) == [("root/later", None, "green", None, False)]
        assert "marks_nowhere" not in page.outline()


async def test_a_mark_is_for_one_visit_of_a_page() -> None:
    async with TestApp(make_app(), strict=False).open("/") as page:
        s = page.session
        s.highlight("export", "red")
        s.highlight("key", "blue", page="/settings?tab=api")
        await page.settle()
        assert brief(page.marks) == [("root/export", None, "red", None, False)]
        # A page that does not come gives the page its marks back.
        await page.click("to-shut")
        assert s.path == "/" and len(s._marks) == 2
        assert brief(page.marks) == [("root/export", None, "red", None, False)]
        # What the tab says of a mark that waits for another page changes
        # nothing.
        waiting = next(m for m in s._marks if m.page == "/settings")
        said = {"n": waiting.n, "what": "touched"}
        s.event(mw.protocol.Event(node="root/export", name="mark", payload=said))
        await page.settle()
        assert len(s._marks) == 2
        # It waits through other pages, the one that refuses included.
        await page.navigate("/other")
        assert page.marks == [] and [m.page for m in s._marks] == ["/settings"]
        await page.navigate("/nowhere-at-all")
        assert [m.page for m in s._marks] == ["/settings"]
        await page.navigate("/")
        assert page.marks == []
        # The page that comes has the mark that waited for it, and not the
        # one for a component of the same name on the page before.
        await page.click("to-settings")
        assert brief(page.marks) == [("root/key", None, "blue", None, False)]
        await page.navigate("/")
        assert page.marks == [] and s._marks == []
        # One for the page the session is on is one of this page.
        s.highlight("export", "red", page="/?tab=1")
        await page.settle()
        assert brief(page.marks) == [("root/export", None, "red", None, False)]
        s.highlight(None)
        await page.settle()
        # A mark set behind a navigation is for the page that was asked for.
        await page.click("away")
        assert s.path == "/settings"
        assert brief(page.marks) == [("root/key", None, "green", None, False)]


async def test_work_that_outlives_its_page_points_at_nothing_on_the_next() -> None:
    app = make_app()
    async with TestApp(app, strict=False).open("/") as page:
        s = page.session

        async def until(done: Any) -> None:
            for _ in range(200):
                if done():
                    return
                await asyncio.sleep(0.005)
            raise AssertionError("it did not come")

        def press(key: str) -> None:
            s.event(mw.protocol.Event(node=f"root/{key}", name="click"))

        press("slow")
        await until(lambda: len(s.tasks) == 1)
        # The person goes on before the reply is done. Both pages have an
        # "export", and the reply meant the one of the page it was asked on.
        s.want("/settings")
        await until(lambda: s.path == "/settings" and s.ready)
        app.gate.set()  # type: ignore[attr-defined]
        await page.settle()
        # Nothing is on this page's "export". What the reply set for a page
        # by name is that page's, and shows there.
        assert brief(page.marks) == [("root/key", None, "blue", None, False)]
        assert [(m.name, m.page) for m in s._marks] == [("key", None)]
        s.highlight(None)
        await page.navigate("/")
        app.gate.clear()  # type: ignore[attr-defined]
        press("slow")
        await until(lambda: len(s.tasks) == 2)
        app.gate.set()  # type: ignore[attr-defined]
        await page.settle()
        # Asked and answered on one page: the mark is set, and the one for
        # another page waits.
        assert brief(page.marks) == [("root/export", None, "red", None, False)]
        assert [(m.name, m.page) for m in s._marks] == [("export", None), ("key", "/settings")]


async def test_the_failure_page_has_no_marks() -> None:
    app = mw.App("fails", public=None)

    @app.page("/")
    def home(s: mw.Session[Any]) -> ui.Component:
        if s.params.get("boom"):
            raise RuntimeError("no page")
        return ui.Page(ui.Button("Export", key="export"))

    @app.page("/broken")
    def broken(s: mw.Session[Any]) -> ui.Component:
        raise RuntimeError("no page")

    async with TestApp(app, strict=False).open("/") as page:
        page.session.highlight("retry", "red", page="/broken")
        await page.navigate("/broken")
        # The page that says what went wrong has a button of that name,
        # and it is not what the mark was for.
        assert page.session.tree is page.session._failure
        assert page.marks == []


async def test_a_page_that_is_put_on_a_tab_brings_its_marks() -> None:
    async with TestApp(make_app()).open("/") as page:
        s = page.session
        s.highlight("export", "red")
        await page.settle()
        # A tab that loads the page again is given them with the page, and
        # is not sent them once more behind it.
        again = json.loads(s.mounted() or "{}")
        assert brief(again["msg"]["marks"]) == [("root/export", None, "red", None, False)]
        sent = len([c for c in page.commands if c.name == "marks"])
        s.refresh()
        await page.settle()
        assert len([c for c in page.commands if c.name == "marks"]) == sent
        # And so is a tab that is taken to another page.
        s.highlight("key", "blue", page="/settings")
        await page.navigate("/settings")
        assert brief(page.marks) == [("root/key", None, "blue", None, False)]
        assert len([c for c in page.commands if c.name == "marks"]) == sent


async def test_a_session_holds_so_many_marks() -> None:
    async with TestApp(make_app()).open("/") as page:
        for n in range(marks.KEPT + 5):
            page.session.highlight(f"name-{n}")
        held = page.session._marks
        assert len(held) == marks.KEPT and held[0].name == "name-5"


async def test_a_field_of_a_form_has_a_name() -> None:
    async with TestApp(make_app()).open("/") as page:
        s = page.session
        form = "root/dlg/order"
        assert s.place("order") == (form, None)
        assert s.place("order/amount") == (form, "/amount")
        assert s.place("order/address/street") == (form, "/address/street")
        assert s.place(f"{form}/address") == (form, "/address")
        assert s.place("order/nope") is None and s.place("nope/amount") is None
        # Only a form has fields, and only the ones it draws.
        assert s.place("dlg/amount") is None and s.place("plain/amount") is None
        assert outline.has_field(
            {"schema": {"fields": [{"pointer": "/a", "widget": "input"}]}}, "/a"
        )
        assert not outline.has_field(
            {"schema": {"fields": [{"pointer": "/a", "widget": "hidden"}]}}, "/a"
        )
        # What a name stands for is kept while the page has the same
        # components, and looked up anew when it has others.
        assert s.place("later") is None
        await page.click("more")
        assert s.place("later") == ("root/later", None)
        # The keyboard goes to a field by the same name.
        await page.click("new")
        s.focus("order/amount")
        s.refresh()
        await page.settle()
        focus = [c.args for c in page.commands if c.name == "focus"]
        assert focus == [{"id": form, "field": "/amount"}]


async def test_the_page_as_data_says_what_is_highlighted() -> None:
    async with TestApp(make_app()).open("/") as page:
        await page.click("tour")
        page.session.highlight("export", "#0a7d5c", label="Here")
        page.session.highlight("gone", "red")
        await page.settle()
        lines = [line.strip() for line in page.outline(as_text=True).splitlines()]
        assert 'button  "New"  key=new  highlighted blue, step 1' in lines
        assert 'button  "Export"  key=export  highlighted #0a7d5c, labeled "Here"' in lines
        amount = next(line for line in lines if "order/amount" in line)
        assert amount.strip() == (
            'field order/amount  "Amount"  number'
            "  highlighted orange, step 2, waits for the steps before it"
        )
        assert lines[:2] == ["page  id=root", 'highlighted and not on the page: "gone"']
        whole = page.outline()
        assert whole["marks_nowhere"] == ["gone"]
        new = next(c for c in whole["children"] if c.get("key") == "new")
        assert new["marked"] == {"color": "blue", "step": 1}


class Shop(BaseModel):
    orders: list[dict[str, Any]] = [
        {"id": 1041, "customer": "Kestrel", "amount": 120.0},
        {"id": 1042, "customer": "Alder", "amount": 80.0},
    ]
    sales: list[dict[str, Any]] = [
        {"month": "2026-02", "units": 4},
        {"month": "2026-03", "units": 9},
    ]


def shop_app() -> mw.App:
    app = mw.App("shop", state=Shop, public=None)

    @app.page("/")
    def home(s: mw.Session[Shop]) -> ui.Component:
        return ui.Page(
            ui.Table(rows=s.state.orders, key="orders"),
            # Rows without the key column go by their place, from 0.
            ui.Table(rows=[{"n": "a"}, {"n": "b"}], key="plain"),
            ui.BarChart(s.state.sales, x="month", y="units", key="sales"),
            ui.PieChart(s.state.sales, x="month", y="units", key="share"),
            ui.Form(Order, key="order"),
        )

    return app


async def test_a_row_of_a_table_and_a_value_of_a_chart_have_names() -> None:
    async with TestApp(shop_app()).open("/") as page:
        s = page.session
        s.highlight("orders/1042", "blue")
        s.highlight("plain/1", "green")
        s.highlight("sales/2026-03", "orange", style="trace")
        s.highlight("share/2026-02", "pink")
        await page.settle()
        by_id = {(mark["id"], mark.get("part")): mark for mark in page.marks}
        # The part is the key or the value itself, as the tab has it, so
        # a number is a number there.
        assert set(by_id) == {
            (page.find("orders").id, 1042),
            (page.find("plain").id, 1),
            (page.find("sales").id, "2026-03"),
            (page.find("share").id, "2026-02"),
        }
        assert all("field" not in mark for mark in page.marks)
        # A row is a place for a highlight only: the keyboard is put in
        # a component or a field.
        assert s.place("orders/1042") is None and s.place("orders") is not None
        # A whole table can be marked beside one of its rows.
        s.highlight("orders", "red")
        await page.settle()
        assert len(page.marks) == 5
        # Getting to a row takes its mark off, and leaves the others.
        await page.touch("orders/1042")
        assert (page.find("orders").id, 1042) not in {
            (mark["id"], mark.get("part")) for mark in page.marks
        }
        assert len(page.marks) == 4
        # A form's field is still a field, and a name that is neither is nowhere.
        s.highlight("order/amount")
        s.highlight("orders/customer")
        await page.settle()
        assert any(mark.get("field") == "/amount" for mark in page.marks)
        with pytest.raises(LookupError):
            page._mark("orders/customer")


async def test_a_mark_on_a_row_follows_the_rows() -> None:
    async with TestApp(shop_app()).open("/") as page:
        s = page.session
        # A row that is not there yet: the mark waits for it.
        s.highlight("orders/1043", "blue")
        s.highlight("sales/2026-04", "blue")
        await page.settle()
        assert page.marks == []
        s.state.orders = [*s.state.orders, {"id": 1043, "customer": "Rowan", "amount": 5.0}]
        s.state.sales = [*s.state.sales, {"month": "2026-04", "units": 2}]
        s.refresh()
        await page.settle()
        assert {mark["part"] for mark in page.marks} == {1043, "2026-04"}
        # And it goes from the tab when the row does, while the session
        # holds it for a row that comes back.
        s.state.orders = s.state.orders[:1]
        s.refresh()
        await page.settle()
        assert {mark["part"] for mark in page.marks} == {"2026-04"}
        s.state.orders = [*s.state.orders, {"id": 1043, "customer": "Rowan", "amount": 5.0}]
        s.refresh()
        await page.settle()
        assert {mark["part"] for mark in page.marks} == {1043, "2026-04"}


async def test_the_page_as_data_says_which_row_is_highlighted() -> None:
    async with TestApp(shop_app()).open("/") as page:
        s = page.session
        s.highlight("orders/1042", "blue", label="Late")
        s.highlight("sales/2026-03", "orange")
        s.highlight("orders/9999")
        await page.settle()
        table = s.outline(within="orders")
        assert table is not None and "marked" not in table
        assert table["marked_parts"] == [{"at": "1042", "color": "blue", "label": "Late"}]
        text = s.outline(as_text=True)
        assert '"1042" highlighted blue, labeled "Late"' in text
        assert '"2026-03" highlighted orange' in text
        # What stands for no row is said as a mark that is nowhere.
        assert s.outline()["marks_nowhere"] == ["orders/9999"]  # type: ignore[index]


class Loading(BaseModel):
    loaded: bool = False
    rows: list[dict[str, Any]] = [{"id": 7, "d": "x"}, {"id": 7, "d": "y"}, {"id": 9, "d": "z"}]


async def test_a_mark_waits_for_a_table_that_is_a_placeholder_yet() -> None:
    app = mw.App("loading", state=Loading, public=None)

    @app.page("/")
    def home(s: mw.Session[Loading]) -> ui.Component:
        days = [{"day": datetime.datetime(2026, 3, 1, 9), "n": 1}]
        orders: ui.Component = ui.Skeleton(key="orders")
        if s.state.loaded:
            orders = ui.Table(rows=[{"id": 1042}], key="orders")
        return ui.Page(
            orders,
            # Two rows share a key, so the tab has these by their places.
            ui.Table(rows=s.state.rows, key="shared"),
            ui.LineChart(days, x="day", y="n", key="days"),
        )

    async with TestApp(app).open("/") as page:
        s = page.session
        s.highlight("orders/1042")
        # A place is not a name for a row of a table that has keys.
        s.highlight("shared/2")
        s.highlight("shared/9")
        # A time is named as the tab is given it, which is its ISO form.
        s.highlight("days/2026-03-01 09:00:00")
        s.highlight("days/2026-03-01T09:00:00")
        await page.settle()
        assert [mark["part"] for mark in page.marks] == ["2026-03-01T09:00:00"]
        # The same key is a table now, and has the row.
        s.state.loaded = True
        s.refresh()
        await page.settle()
        assert {mark["part"] for mark in page.marks} == {1042, "2026-03-01T09:00:00"}
        # And rows that are told apart again are named by their keys.
        s.state.rows = [{"id": 7, "d": "x"}, {"id": 9, "d": "z"}]
        s.refresh()
        await page.settle()
        assert {mark["part"] for mark in page.marks} == {1042, 9, "2026-03-01T09:00:00"}
