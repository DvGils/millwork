"""The Sortable: what a list is given, and what a move the tab sends comes to."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.nodes import build
from millwork.testing import TestApp


class Board(BaseModel):
    lists: dict[str, list[str]] = {"todo": ["a", "b", "c"], "done": ["x"], "kept": ["k1", "k2"]}
    moves: list[ui.Move] = []
    closed: bool = False


def make_app(tmp_path: Path) -> mw.App:
    app = mw.App("board", state=Board, public=None, bundle_dir=tmp_path)

    def moved(s: mw.Session[Board], move: ui.Move) -> None:
        s.state.moves.append(move)
        lists = s.state.lists
        lists[move.source].remove(move.key)
        lists[move.target].insert(move.to, move.key)

    def rows(name: str, **how: Any) -> ui.Component:
        return ui.Sortable(
            *[ui.Text(key, key=key) for key in s_lists()[name]],
            key=name,
            group="tasks",
            on_move=moved,
            **how,
        )

    def s_lists() -> dict[str, list[str]]:
        return mw.session().state.lists

    @app.page("/")
    def home(s: mw.Session[Board]) -> ui.Component:
        return ui.Page(
            rows("todo"),
            rows("done", disabled=s.state.closed),
            # Its own rows keep their order, and it takes none of another list.
            rows("kept", reorder=False, takes=False),
            ui.Sortable(ui.Text("lone", key="lone"), ui.Text("other", key="other"), key="alone"),
            ui.Sortable(ui.Text("far", key="far"), key="elsewhere", group="others", on_move=moved),
        )

    return app


def test_a_row_has_a_key_and_a_list_of_a_group_has_one() -> None:
    with pytest.raises(ValueError, match="each row of a Sortable is a component with a key"):
        ui.Sortable(ui.Text("no key"))
    with pytest.raises(ValueError, match="each row of a Sortable is a component with a key"):
        ui.Sortable("just words")
    with pytest.raises(ValueError, match="two rows of a Sortable have the key 'a'"):
        ui.Sortable(ui.Text("one", key="a"), ui.Text("two", key="a"))
    with pytest.raises(ValueError, match="in the group 'tasks' has a key"):
        ui.Sortable(ui.Text("one", key="a"), group="tasks")
    props = (
        build(ui.Sortable(ui.Text("one", key="a"), key="rows", empty="None yet"))
        .nodes["root"]
        .props
    )
    assert props["reorder"] is True and props["takes"] is True and props["handle"] is True
    assert props["empty"] == "None yet" and props.get("group") is None


async def test_a_move_names_the_row_its_lists_and_its_place(tmp_path: Path) -> None:
    async with TestApp(make_app(tmp_path)).open("/") as page:
        await page.move("c", 0)
        await page.move("a", 1, into="done")
        assert page.state.lists["todo"] == ["c", "b"] and page.state.lists["done"] == ["x", "a"]
        assert page.state.moves == [
            ui.Move(key="c", source="todo", target="todo", to=0),
            ui.Move(key="a", source="todo", target="done", to=1),
        ]
        # A place past the end is the end, with the row itself left out
        # where it stays in its list.
        await page.move("c", 99)
        await page.move("x", 99, into="todo")
        assert page.state.moves[-2].to == 1 and page.state.moves[-1].to == 2
        assert page.state.lists["todo"] == ["b", "c", "x"]
        # A row out of a list that keeps its order may still leave it.
        await page.move("k1", 0, into="done")
        assert page.state.lists["kept"] == ["k2"] and page.state.lists["done"][0] == "k1"


async def test_a_move_the_page_does_not_offer_is_refused(tmp_path: Path) -> None:
    async with TestApp(make_app(tmp_path)).open("/") as page:
        todo, done, kept = (page.find(name).id for name in ("todo", "done", "kept"))
        refused = [
            # The rows of this list keep their order, and it takes no others.
            ("kept", {"key": f"{kept}/k2", "source": kept, "to": 0}),
            ("kept", {"key": f"{todo}/a", "source": todo, "to": 0}),
            # A row that is not in the list it is said to come from.
            ("done", {"key": f"{todo}/a", "source": done, "to": 0}),
            ("done", {"key": f"{todo}/nope", "source": todo, "to": 0}),
            ("done", {"key": f"{todo}/a", "source": "root/nowhere", "to": 0}),
            # Lists of two groups, and a list of none.
            (
                "done",
                {
                    "key": f"{page.find('elsewhere').id}/far",
                    "source": page.find("elsewhere").id,
                    "to": 0,
                },
            ),
            (
                "todo",
                {"key": f"{page.find('alone').id}/lone", "source": page.find("alone").id, "to": 0},
            ),
            # Not a move at all.
            ("done", {"key": f"{todo}/a", "source": todo, "to": "first"}),
            ("done", {"key": f"{todo}/a", "source": todo, "to": True}),
            ("done", [f"{todo}/a", todo, 0]),
            ("done", None),
        ]
        for target, payload in refused:
            with pytest.raises(LookupError):
                await page.event(target, "move", payload)
        assert page.state.moves == []
        # The list is told of each all the same, so the row goes back at once.
        told = [c.args["node"] for c in page.commands if c.name == "moved"]
        assert len(told) == len(refused) and set(told) == {todo, done, kept}
        # A list that is disabled takes none and gives none.
        page.state.closed = True
        page.session.refresh()
        await page.settle()
        with pytest.raises(LookupError):
            await page.move("a", 0, into="done")
        with pytest.raises(LookupError):
            await page.move("x", 0, into="todo")
        assert page.state.moves == []


async def test_a_list_is_told_when_its_move_was_dealt_with(tmp_path: Path) -> None:
    app = mw.App("told", public=None, bundle_dir=tmp_path)
    order = ["a", "b"]

    def stays(s: mw.Session, move: ui.Move) -> None:
        if move.key == "b":
            raise RuntimeError("no")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Sortable(*[ui.Text(k, key=k) for k in order], key="rows", on_move=stays))

    async with TestApp(app, strict=False).open("/") as page:
        rows = page.find("rows").id
        # A handler that leaves the rows as they are, and one that fails:
        # the list hears of either, so the row can go back at once.
        await page.move("a", 1)
        await page.move("b", 0)
        told = [c.args["node"] for c in page.commands if c.name == "moved"]
        assert told == [rows, rows]


async def test_a_row_is_not_moved_into_a_list_it_holds(tmp_path: Path) -> None:
    app = mw.App("nested", public=None, bundle_dir=tmp_path)
    moves: list[ui.Move] = []

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        inner = ui.Sortable(
            ui.Text("leaf", key="leaf"),
            key="inner",
            group="all",
            on_move=lambda s, m: moves.append(m),
        )
        return ui.Page(
            ui.Sortable(
                ui.Card(inner, key="branch"),
                ui.Text("twig", key="twig"),
                key="outer",
                group="all",
                on_move=lambda s, m: moves.append(m),
            )
        )

    async with TestApp(app).open("/") as page:
        with pytest.raises(LookupError, match="the list is in the row that is moved"):
            await page.move("branch", 0, into="inner")
        await page.move("twig", 1, into="inner")
        assert moves == [ui.Move(key="twig", source="outer", target="inner", to=1)]
