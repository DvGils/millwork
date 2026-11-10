"""Lazy parts: a part of a page that is kept up to date only while it shows."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.nodes import build, diff
from millwork.protocol import Event, Request
from millwork.testing import TestApp


class State(BaseModel):
    count: int = 0
    tab: str = "a"
    allowed: bool = True
    calls: dict[str, int] = {}
    got: list[str] = []


def called(s: mw.Session[State], name: str) -> None:
    s.state.calls[name] = s.state.calls.get(name, 0) + 1


@ui.lazy
def first(s: mw.Session[State]) -> ui.Component:
    called(s, "first")
    return ui.Text(f"first {s.state.count}", key="first")


@ui.lazy
def second(s: mw.Session[State]) -> ui.Component:
    called(s, "second")
    return ui.Text(f"second {s.state.count}", key="second")


def bump(s: mw.Session[State], _: Any) -> None:
    s.state.count += 1


def make(tmp_path: Path, tabs: Any) -> mw.App:
    app = mw.App("t", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("bump", key="bump", on_click=bump), tabs(s))

    return app


def own_tabs(s: mw.Session[State]) -> ui.Component:
    return ui.Tabs(
        ui.Tab(first(s), id="a", label="A"),
        ui.Tab(second(s), id="b", label="B"),
        key="tabs",
    )


# ------------------------------------------------------------ in the tree


def test_a_lazy_part_leaves_no_node_of_its_own() -> None:
    @ui.lazy
    def part(n: int) -> ui.Component:
        return ui.Text(f"n {n}")

    tree = build(ui.Stack(part(1), part(2)))
    assert tree.nodes["root"].children == ["root/0:Text", "root/1:Text"]
    assert all(node.type != "Lazy" for node in tree.nodes.values())
    assert tree.nodes["root/1:Text"].props["content"] == "n 2"


def test_what_a_lazy_part_returns_keeps_its_key() -> None:
    @ui.lazy
    def row(name: str) -> ui.Component:
        return ui.Text(name, key=name)

    tree = build(ui.Stack(row("x"), row("y")))
    assert tree.nodes["root"].children == ["root/x", "root/y"]
    with pytest.raises(ValueError, match="duplicate key 'x'"):
        build(ui.Stack(row("x"), row("x")))


def test_a_lazy_function_returns_a_component_a_string_or_nothing() -> None:
    @ui.lazy
    def nothing() -> None:
        return None

    @ui.lazy
    def words() -> Any:
        return "plain"

    @ui.lazy
    def number() -> Any:
        return 3

    @ui.lazy
    def outer() -> ui.Component:
        return words()

    tree = build(ui.Stack(nothing(), words(), outer()))
    assert tree.nodes["root"].children == ["root/1:Text", "root/2:Text"]
    with pytest.raises(TypeError, match="number returned int"):
        build(ui.Stack(number()))


def test_a_lazy_function_is_not_async() -> None:
    with pytest.raises(TypeError, match="is async"):

        @ui.lazy
        async def part() -> ui.Component:
            return ui.Text("x")

    async def later() -> ui.Component:
        return ui.Text("x")

    with pytest.raises(TypeError, match="is async"):
        build(ui.Stack(ui.lazy(lambda: later())()))  # type: ignore[arg-type, return-value]


def test_a_lazy_part_works_as_a_method_and_in_a_slot() -> None:
    class Views:
        def __init__(self, name: str) -> None:
            self.name = name

        @ui.lazy
        def title(self, size: str) -> ui.Component:
            return ui.Text(f"{self.name} {size}")

    views = Views("ada")
    tree = build(ui.Card(views.title("big"), footer=views.title("small")))
    assert tree.nodes["root/0:Text"].props["content"] == "ada big"
    assert tree.nodes["root/@footer"].props["content"] == "ada small"


def test_a_tab_is_not_lazy_itself() -> None:
    @ui.lazy
    def tab() -> ui.Component:
        return ui.Tab("x", id="a", label="A")

    with pytest.raises(ValueError, match="goes inside a ui.Tab"):
        ui.Tabs(tab())


def test_only_tabs_that_own_their_choice_ask_the_browser_for_it() -> None:
    @ui.lazy
    def part() -> ui.Component:
        return ui.Text("x")

    def tabs(**props: Any) -> dict[str, Any]:
        page = ui.Tabs(ui.Tab(part(), id="a", label="A"), ui.Tab("b", id="b", label="B"), **props)
        return build(page).nodes["root"].props

    assert tabs()["track"] is True and tabs(default="b")["track"] is True
    assert "track" not in tabs(value="a")
    plain = ui.Tabs(ui.Tab("a", id="a", label="A"), ui.Tab("b", id="b", label="B"))
    assert "track" not in build(plain).nodes["root"].props


def test_the_open_tab_is_the_one_the_browser_opens_on_until_it_says_otherwise() -> None:
    def tabs(**props: Any) -> ui.Tabs:
        return ui.Tabs(
            ui.Tab("a", id="a", label="A", disabled=True),
            ui.Tab("b", id="b", label="B"),
            ui.Tab("c", id="c", label="C"),
            **props,
        )

    # Not told yet: the default, or the first tab, as the browser opens.
    assert tabs().shown(None) == "a"
    assert tabs(default="c").shown(None) == "c"
    assert tabs(default="gone").shown(None) == "b"  # then the first that can be chosen
    # Told: the browser's word, whatever tab it is.
    assert tabs(default="c").shown("b") == "b"
    assert tabs(default="c").shown("a") == "a"
    assert tabs(default="c").shown("gone") == "c"
    # With a value the page's word is final.
    assert tabs(value="a").shown("b") == "a"
    assert tabs(value=None).shown("b") is None


def test_a_part_that_does_not_show_is_the_one_from_the_tree_before() -> None:
    calls: list[str] = []

    @ui.lazy
    def part(name: str, n: int) -> ui.Component:
        calls.append(name)
        return ui.Stack(ui.Text(f"{name} {n}"), ui.Button("go", on_click=lambda s, _: None))

    def page(n: int) -> ui.Component:
        return ui.Tabs(
            ui.Tab(part("a", n), id="a", label="A"), ui.Tab(part("b", n), id="b", label="B")
        )

    one = build(page(1))
    assert calls == ["a", "b"]  # the first time, every part is built
    two = build(page(2), last=one)
    assert calls == ["a", "b", "a"]
    assert two.nodes["root/0:Tab/0:Stack/0:Text"].props["content"] == "a 2"
    kept = "root/1:Tab/0:Stack"
    assert two.nodes[f"{kept}/0:Text"].props["content"] == "b 1"
    assert two.nodes[kept] is one.nodes[kept]
    assert two.handler(f"{kept}/1:Button", "click") is one.handler(f"{kept}/1:Button", "click")
    assert two.kept_part(f"{kept}/1:Button") == "root/1:Tab/0"
    assert two.kept_part("root/0:Tab/0:Stack") is None
    assert [type(op).__name__ for op in diff(one, two)] == ["SetOp"]
    # The tab says B is open. B is built, and A once more, as it is left.
    del calls[:]
    three = build(page(3), last=two, showing={"root": "b"})
    assert calls == ["a", "b"] and three.kept == []
    assert three.nodes[f"{kept}/0:Text"].props["content"] == "b 3"
    assert three.nodes["root/0:Tab/0:Stack/0:Text"].props["content"] == "a 3"
    # From the render after, A is the one it was when it was left.
    del calls[:]
    four = build(page(4), last=three, showing={"root": "b"})
    assert calls == ["b"]
    assert four.nodes["root/0:Tab/0:Stack/0:Text"].props["content"] == "a 3"
    # Asked for by name, a part is built though it does not show.
    five = build(page(5), last=four, showing={"root": "b"}, wanted={"root/0:Tab/0"})
    assert five.nodes["root/0:Tab/0:Stack/0:Text"].props["content"] == "a 5"
    assert five.kept == []
    assert build(page(6), last=five, showing={"root": "b"}).kept_part("root/0:Tab/0:Stack")


def test_a_part_of_another_function_in_the_same_place_is_built() -> None:
    @ui.lazy
    def old() -> ui.Component:
        return ui.Text("old")

    @ui.lazy
    def new() -> ui.Component:
        return ui.Text("new")

    def page(part: Any) -> ui.Component:
        return ui.Tabs(ui.Tab("a", id="a", label="A"), ui.Tab(part(), id="b", label="B"))

    one = build(page(old))
    two = build(page(new), last=one)
    assert two.nodes["root/1:Tab/0:Text"].props["content"] == "new"


def test_parts_inside_a_part_and_tabs_inside_a_tab() -> None:
    calls: list[str] = []

    @ui.lazy
    def leaf(name: str) -> ui.Component:
        calls.append(name)
        return ui.Text(name)

    @ui.lazy
    def inner() -> ui.Component:
        calls.append("inner")
        return ui.Tabs(
            ui.Tab(leaf("x"), id="x", label="X"), ui.Tab(leaf("y"), id="y", label="Y"), key="in"
        )

    def page() -> ui.Component:
        return ui.Tabs(ui.Tab(inner(), id="a", label="A"), ui.Tab(leaf("b"), id="b", label="B"))

    x, y = "root/0:Tab/in/0:Tab/0:Text", "root/0:Tab/in/1:Tab/0:Text"
    one = build(page())
    assert sorted(calls) == ["b", "inner", "x", "y"]
    calls.clear()
    two = build(page(), last=one)
    # The open tab's part, and inside it the open inner tab's.
    assert calls == ["inner", "x"]
    assert {p.key for p in two.kept} == {"root/0:Tab/in/1:Tab/0", "root/1:Tab/0"}
    # Over to B: what was open under A is built once more, as it is left.
    calls.clear()
    three = build(page(), last=two, showing={"root": "b"})
    assert calls == ["inner", "x", "b"]
    assert [p.key for p in three.kept] == ["root/0:Tab/in/1:Tab/0"]
    # And is one kept part from then on, with all it holds.
    calls.clear()
    four = build(page(), last=three, showing={"root": "b"})
    assert calls == ["b"]
    assert [p.key for p in four.kept] == ["root/0:Tab/0"]
    assert four.kept_part(x) == four.kept_part(y) == "root/0:Tab/0"
    # Back on A with the inner tabs on Y: X is as it was left, Y is built.
    calls.clear()
    five = build(page(), last=four, showing={"root/0:Tab/in": "y"})
    assert calls == ["inner", "y", "b"]
    assert five.nodes[x] is three.nodes[x] and five.nodes[y] is not one.nodes[y]


def test_a_kept_part_that_holds_a_key_taken_since_gives_way() -> None:
    @ui.lazy
    def row(name: str) -> ui.Component:
        return ui.Text(name, key=name)

    def page(names: list[str]) -> ui.Component:
        return ui.Tabs(
            ui.Tab("a", id="a", label="A"),
            ui.Tab(*(row(n) for n in names), id="b", label="B"),
        )

    one = build(page(["x", "y"]))
    # A row in front: the kept rows hold x and y, and the third row is y now.
    two = build(page(["w", "x", "y"]), last=one)
    assert two.nodes["root/1:Tab"].children == ["root/1:Tab/w", "root/1:Tab/x", "root/1:Tab/y"]
    assert two.kept == []
    # Two rows that really are the same are refused once their tab is built.
    with pytest.raises(ValueError, match="duplicate key 'x'"):
        build(page(["x", "x"]), last=two, showing={"root": "b"})


def test_lazy_rows_are_a_list_without_keys_when_what_they_return_has_none() -> None:
    @ui.lazy
    def row(n: int, keyed: bool) -> ui.Component:
        return ui.Text(str(n), key=f"r{n}" if keyed else None)

    assert build(ui.Stack(*(row(n, True) for n in range(6)))).keyless_runs == {}
    assert build(ui.Stack(*(row(n, False) for n in range(6)))).keyless_runs == {"root": "Text"}

    # Kept rows count as they did when they were built.
    def page(count: int) -> ui.Component:
        return ui.Tabs(
            ui.Tab("a", id="a", label="A"),
            ui.Tab(*(row(n, False) for n in range(count)), id="b", label="B"),
        )

    one = build(page(5))
    assert build(page(4), last=one).keyless_runs == {"root/1:Tab": "Text"}
    # Strings take no key, so a run of them is not a list of rows.
    assert build(ui.Stack("a", "b", "c", "d", "e")).keyless_runs == {}


def test_a_key_that_reaches_into_a_lazy_part_is_a_duplicate() -> None:
    @ui.lazy
    def part() -> ui.Component:
        return ui.Stack(ui.Text("inside", key="b"), key="a")

    def page() -> ui.Component:
        return ui.Tabs(
            ui.Tab("a", id="a", label="A"),
            ui.Tab(ui.Text("outside", key="a/b"), part(), id="b", label="B"),
        )

    with pytest.raises(ValueError, match="duplicate key"):
        build(page())


# ---------------------------------------------------------- in a session


async def test_a_part_is_drawn_first_and_then_only_while_its_tab_is_open(tmp_path: Path) -> None:
    async with TestApp(make(tmp_path, own_tabs)).open("/") as page:
        s = page.session
        assert s.state.calls == {"first": 1, "second": 1}
        assert "first 0" in page.text() and "second 0" in page.text()
        await page.click("bump")
        await page.click("bump")
        assert s.state.calls == {"first": 3, "second": 1}
        # The part of the other tab is in the browser as it was.
        assert page.find("first").props["content"] == "first 2"
        assert page.find("second").props["content"] == "second 0"
        await page.change("tabs", "b")
        assert page.find("second").props["content"] == "second 2"
        # The part that was left is drawn once more as it is left.
        assert s.state.calls == {"first": 4, "second": 2}
        await page.click("bump")
        assert page.find("second").props["content"] == "second 3"
        assert page.find("first").props["content"] == "first 2"
        assert s.state.calls == {"first": 4, "second": 3}


async def test_tabs_the_page_owns_need_no_word_from_the_browser(tmp_path: Path) -> None:
    def to(s: mw.Session[State], tab: str) -> None:
        s.state.tab = tab

    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Tabs(
            ui.Tab(first(s), id="a", label="A"),
            ui.Tab(second(s), id="b", label="B"),
            key="tabs",
            value=s.state.tab,
            on_change=to,
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        await page.click("bump")
        assert page.find("second").props["content"] == "second 0"
        await page.change("tabs", "b")
        assert page.find("second").props["content"] == "second 1"
        await page.click("bump")
        assert page.find("first").props["content"] == "first 1"
        assert page.find("second").props["content"] == "second 2"


async def test_saying_which_tab_is_open_runs_no_handler_and_is_checked(tmp_path: Path) -> None:
    def note(s: mw.Session[State], tab: str) -> None:
        s.state.got.append(tab)

    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Tabs(
            ui.Tab(first(s), id="a", label="A"),
            ui.Tab(second(s), id="b", label="B"),
            ui.Tab("c", id="c", label="C", disabled=True),
            key="tabs",
            on_change=note,
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        s = page.session
        for said in ("b", "b", "nowhere", 7, None):
            await page.event("tabs", "show", said)
        assert s.state.got == []
        assert s._showing == {"root/tabs": "b"}
        # A tab that cannot be chosen is still one the browser can be on,
        # opened on as the default, and then the browser's word goes.
        await page.event("tabs", "show", "c")
        assert s._showing == {"root/tabs": "c"} and s.state.got == []
        # A person choosing a tab is a change, which the handler hears once.
        await page.change("tabs", "a")
        assert s.state.got == ["a"] and s._showing == {"root/tabs": "a"}
        with pytest.raises(LookupError, match="no tab 'c'"):
            await page.change("tabs", "c")


async def test_a_message_from_a_kept_part_is_answered_by_the_page_as_it_is_now(
    tmp_path: Path,
) -> None:
    def note(s: mw.Session[State], _: Any) -> None:
        s.state.got.append(f"count {s.state.count}")

    def revoke(s: mw.Session[State], _: Any) -> None:
        s.state.allowed = False

    @ui.lazy
    def admin(s: mw.Session[State]) -> ui.Component:
        count = s.state.count
        return ui.Stack(
            ui.Button("stays", key="stays", on_click=lambda s, _: s.state.got.append(str(count))),
            ui.Button("danger", key="danger", on_click=note) if s.state.allowed else None,
        )

    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Tabs(
            ui.Tab(ui.Button("revoke", key="revoke", on_click=revoke), id="a", label="A"),
            ui.Tab(admin(s), id="b", label="B"),
            key="tabs",
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        s = page.session
        danger, stays = page.find("danger").id, page.find("stays").id
        await page.click("bump")
        await page.click("revoke")
        # Tab B was never opened, so the browser still holds both buttons.
        assert danger in page.tree and s.kept_part(danger) == "root/tabs/1:Tab/0"
        s.event(Event(node=danger, name="click"))
        await page.settle()
        assert s.state.got == []  # the page no longer offers it
        assert danger not in page.tree
        await page.click("bump")
        s.event(Event(node=stays, name="click"))
        await page.settle()
        assert s.state.got == ["2"]  # and what it does offer is as it is now


async def test_a_kept_part_that_cannot_be_built_is_not_called(tmp_path: Path) -> None:
    @ui.lazy
    def fragile(s: mw.Session[State]) -> ui.Component:
        if s.state.count:
            raise RuntimeError("no")
        return ui.Button("go", key="go", on_click=lambda s, _: s.state.got.append("went"))

    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Tabs(
            ui.Tab("a", id="a", label="A"), ui.Tab(fragile(s), id="b", label="B"), key="tabs"
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        s = page.session
        go = page.find("go").id
        await page.click("bump")
        s.event(Event(node=go, name="click"))
        with pytest.raises(RuntimeError, match="no"):
            await page.settle()
        page.failures.clear()
        assert s.state.got == []
        # The page stands as it was.
        assert go in page.tree


async def test_what_the_tab_said_holds_on_a_page_whose_tabs_go_by_the_same_id(
    tmp_path: Path,
) -> None:
    app = make(tmp_path, own_tabs)

    @app.page("/other")
    def other(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("bump", key="bump", on_click=bump), own_tabs(s))

    @app.page("/plain")
    def plain(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("no tabs here"))

    async with TestApp(app).open("/") as page:
        s = page.session
        await page.change("tabs", "b")
        # The browser keeps its tabs through the move and stays on B.
        await page.navigate("/other")
        assert s._showing == {"root/tabs": "b"}
        await page.click("bump")
        await page.click("bump")
        assert page.find("second").props["content"] == "second 2"
        assert page.find("first").props["content"] == "first 0"
        # Where the tabs are gone, so is what was said about them.
        await page.navigate("/plain")
        assert s._showing == {}


async def test_a_tab_opened_while_a_move_to_another_page_fails_is_the_open_one(
    tmp_path: Path,
) -> None:
    app = make(tmp_path, own_tabs)
    gate = asyncio.Event()

    @app.page("/report")
    def report(s: mw.Session[State]) -> ui.Component:
        return ui.Page("never")

    @report.connect
    async def load(s: mw.Session[State]) -> None:
        await gate.wait()
        raise RuntimeError("database is down")

    async with TestApp(app, strict=False).open("/") as page:
        s = page.session
        tabs = page.find("tabs").id
        s.navigate("/report")
        await asyncio.sleep(0.01)
        s.event(Event(node=tabs, name="show", payload="b"))
        await asyncio.sleep(0.01)
        gate.set()
        await page.settle()
        assert s.path == "/" and s._showing == {tabs: "b"}
        await page.click("bump")
        assert page.find("second").props["content"] == "second 1"


async def test_an_event_from_a_kept_part_does_not_reach_the_next_page(tmp_path: Path) -> None:
    app = mw.App("t", state=State, public=None, bundle_dir=tmp_path)
    gate = asyncio.Event()

    async def go(s: mw.Session[State], _: Any) -> None:
        s.navigate("/p/2")
        await gate.wait()

    @ui.lazy
    def danger(s: mw.Session[State]) -> ui.Component:
        item = s.params["n"]
        return ui.Button(
            "delete", key="delete", on_click=lambda s, _: s.state.got.append(f"delete {item}")
        )

    @app.page("/p/{n}")
    def project(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("go", key="go", on_click=go),
            ui.Tabs(ui.Tab("a", id="a", label="A"), ui.Tab(danger(s), id="b", label="B")),
        )

    async with TestApp(app).open("/p/1") as page:
        s = page.session
        s.refresh()
        await page.settle()
        delete = page.find("delete").id
        assert s.kept_part(delete) is not None
        # A handler holds the turn and has asked for the next page. The tab,
        # still on the first one, sends a click from the kept part.
        s.event(Event(node=page.find("go").id, name="click"))
        await asyncio.sleep(0.01)
        s.event(Event(node=delete, name="click"))
        await asyncio.sleep(0.01)
        gate.set()
        await page.settle()
        assert s.path == "/p/2" and s.state.got == []


async def test_an_event_from_a_kept_part_keeps_its_place_in_line(tmp_path: Path) -> None:
    gate = asyncio.Event()
    order: list[str] = []

    async def slow(s: mw.Session[State], _: Any) -> None:
        await gate.wait()

    def typed(s: mw.Session[State], value: str) -> None:
        order.append(f"typed {value}")

    def save(s: mw.Session[State], _: Any) -> None:
        order.append("save")

    @ui.lazy
    def editor(s: mw.Session[State]) -> ui.Component:
        return ui.Input(key="name", value="", on_change=typed)

    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Stack(
            ui.Button("slow", key="slow", on_click=slow),
            ui.Button("save", key="save", on_click=save),
            ui.Tabs(ui.Tab("a", id="a", label="A"), ui.Tab(editor(s), id="b", label="B"), key="t"),
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        s = page.session
        s.refresh()
        await page.settle()
        name = page.find("name").id
        s.event(Event(node=page.find("slow").id, name="click"))
        await asyncio.sleep(0.01)
        # With something slow running, the person opens tab B, types and
        # presses save, in that order.
        s.event(Event(node=page.find("t").id, name="show", payload="b"))
        s.event(Event(node=name, name="change", payload="new"))
        s.event(Event(node=page.find("save").id, name="click"))
        await asyncio.sleep(0.01)
        gate.set()
        await page.settle()
        assert order == ["typed new", "save"]


async def test_a_search_in_a_kept_part_that_is_cancelled_leaves_the_turn_free(
    tmp_path: Path,
) -> None:
    gate = asyncio.Event()

    async def slow(s: mw.Session[State], _: Any) -> None:
        await gate.wait()

    @ui.lazy
    def finder(s: mw.Session[State]) -> ui.Component:
        return ui.Combobox(key="who", on_search=lambda s, q: [q.upper()])

    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Stack(
            ui.Button("slow", key="slow", on_click=slow),
            ui.Tabs(ui.Tab("a", id="a", label="A"), ui.Tab(finder(s), id="b", label="B")),
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        s, conn = page.session, page.session.conn
        assert conn is not None
        s.refresh()
        await page.settle()
        who = page.find("who").id
        assert s.kept_part(who) is not None
        s.event(Event(node=page.find("slow").id, name="click"))
        await asyncio.sleep(0.01)
        # The search waits for the turn, to have its part built first.
        s.request(conn, Request(node=who, name="search", request="r1", payload="a"), None)
        await asyncio.sleep(0.01)
        child = s._requests["r1"][0]
        assert s.turn.waiting == 1
        # The handler ends and the turn is passed to the search, which is
        # cancelled before it runs a line with it.
        gate.set()
        for _ in range(10):
            await asyncio.sleep(0)
            if s.turn.holder is child:
                break
        assert s.turn.holder is child
        s.cancel("r1")
        await asyncio.sleep(0.05)
        assert s.turn.free
        await page.click("bump")
        assert s.state.count == 1
        # One that is not cancelled is answered by the part as it is now.
        s.request(conn, Request(node=who, name="search", request="r2", payload="b"), None)
        await page.settle()
        assert s.turn.free and s.kept_part(who) is None


async def test_a_dialog_closed_by_the_handler_that_leaves_its_tab_is_closed(
    tmp_path: Path,
) -> None:
    def save(s: mw.Session[State], _: Any) -> None:
        s.state.allowed = False
        s.state.tab = "a"

    @ui.lazy
    def editor(s: mw.Session[State]) -> ui.Component:
        return ui.Dialog(
            ui.Button("save", key="save", on_click=save),
            open=s.state.allowed,
            title="Edit",
            key="dialog",
        )

    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Tabs(
            ui.Tab("a", id="a", label="A"),
            ui.Tab(editor(s), id="b", label="B"),
            value=s.state.tab,
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        page.state.tab = "b"
        page.session.refresh()
        await page.settle()
        assert page.find("dialog").props["open"] is True
        await page.click("save")
        # Its part was drawn once more as its tab was left.
        assert page.find("dialog").props["open"] is False
        assert page.session.kept_part(page.find("dialog").id) is None
        await page.click("bump")
        assert page.session.kept_part(page.find("dialog").id) is not None


async def test_a_page_that_is_one_lazy_part_and_a_question_that_is_one(tmp_path: Path) -> None:
    app = mw.App("t", state=State, public=None, bundle_dir=tmp_path)

    @ui.lazy
    def sure() -> ui.Component:
        return ui.Dialog(ui.Button("yes", key="yes", on_click=lambda s, _: None), title="Sure?")

    async def ask(s: mw.Session[State], _: Any) -> None:
        s.state.got.append(str(await s.ask(sure())))

    @ui.lazy
    def whole(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("ask", key="ask", on_click=ask), title="Whole")

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return whole(s)

    async with TestApp(app).open("/") as page:
        assert page.tree["root"].type == "Page"
        await page.click("ask")
        dialog = page.find(ui.Dialog)
        assert dialog.props["open"] is True and dialog.props["title"] == "Sure?"


async def test_a_change_drawn_only_in_a_kept_part_is_not_called_a_handler_for_nothing(
    tmp_path: Path,
) -> None:
    def tabs(s: mw.Session[State]) -> ui.Component:
        return ui.Tabs(
            ui.Tab("nothing that changes", id="a", label="A"),
            ui.Tab(second(s), id="b", label="B"),
            key="tabs",
        )

    async with TestApp(make(tmp_path, tabs)).open("/") as page:
        await page.click("bump")
        assert not any(key.startswith("noop:") for key in page.session._warned)
        await page.change("tabs", "b")
        assert page.find("second").props["content"] == "second 1"
