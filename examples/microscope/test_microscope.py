"""The microscope, driven without a browser. The first tests are of the
drop alone, moved on by hand, and the rest of the page around it."""

import asyncio
import math
import sys
from collections.abc import AsyncIterator
from functools import partial
from types import ModuleType
from typing import Any

import pytest

from millwork import ui
from millwork.testing import Page, TestApp


@pytest.fixture
def world(example: ModuleType) -> ModuleType:
    """The module the drop is in."""
    return sys.modules["world"]


@pytest.fixture
async def page(example: ModuleType, world: ModuleType) -> AsyncIterator[Page]:
    # The same drop every time, and a clock that leaves it to the test.
    example.World = partial(world.World, seed=7)
    example.TICK = 3600
    async with TestApp(example.app).open("/") as page:
        yield page


def empty(world: ModuleType) -> Any:
    """A drop with nothing alive in it."""
    drop = world.World(seed=3)
    drop.cells.clear()
    return drop


def put(world: ModuleType, drop: Any, kind: int, x: float, y: float, **how: Any) -> Any:
    drop._made += 1
    cell = world.Cell(drop._made, kind, x, y, 0.5, how.pop("heading", 0.0), **how)
    drop.cells[cell.id] = cell
    return cell


# --------------------------------------------------------------- the drop


def test_algae_grow_where_the_lamp_shines(world: ModuleType) -> None:
    drop = empty(world)
    drop.algae = [None] * world.ALGAE
    drop._squares, drop._free = {}, list(range(world.ALGAE))
    drop.view.objective, drop.view.lamp = 40, 1.0
    drop.pan(300, 0)
    for _ in range(40):
        drop._step(0.2)
    lit = [a for a in drop.algae if a and math.hypot(a[0] - 300, a[1]) <= 60]
    # The view is a hundredth of the drop, and holds a good part of what grew.
    assert len(lit) > 25 and len(lit) > 0.2 * sum(a is not None for a in drop.algae)
    # No square of the drop is crowded, whatever the light.
    assert max(len(square) for square in drop._squares.values()) <= world.CROWD


def test_a_cell_that_is_fed_divides_into_two_that_are_a_little_unlike_it(
    world: ModuleType,
) -> None:
    drop = empty(world)
    parent = put(world, drop, world.GRAZER, 0, 0, line=2, hue=40.0, energy=5.5, generation=4)
    drop._step(0.2)
    one, two = drop.cells.values()
    assert one is parent and (one.generation, two.generation) == (5, 5)
    assert (two.line, one.divided) == (2, 1) and one.energy == two.energy < 2.8
    for daughter in (one, two):
        traits = (daughter.speed, daughter.size, daughter.sense)
        assert all(0.7 < t < 1.4 and t != 1.0 for t in traits)
    # Over many generations the traits stay within what a cell can be.
    for _ in range(300):
        drop._divide(one)
    assert all(world.LEAST <= c.speed <= world.UTMOST for c in drop.cells.values())
    # A drop that is full of a kind has no room for a division.
    everyone = len(drop.cells)
    assert everyone > world.MOST[world.GRAZER]
    one.energy = one.full + 1
    drop._step(0.2)
    assert len(drop.cells) <= everyone


def test_a_hungry_hunter_eats_the_grazer_it_reaches(world: ModuleType) -> None:
    drop = empty(world)
    hunter = put(world, drop, world.HUNTER, 0, 0, energy=3.0)
    put(world, drop, world.GRAZER, 5, 0)
    drop._step(0.2)
    assert [c.kind for c in drop.cells.values()] == [world.HUNTER] and hunter.eaten == 1
    assert hunter.energy == pytest.approx(3.0 + world.MEAL, abs=0.1)
    # Fed, it leaves the next one be, and does not turn to it.
    hunter.energy = 0.8 * hunter.full
    prey = put(world, drop, world.GRAZER, 5, 0, heading=math.pi)
    drop._step(0.2)
    assert prey.id in drop.cells and not hunter.hungry
    assert drop._aim(hunter, [prey], [hunter]) is None
    hunter.energy = 0.3 * hunter.full
    assert drop._aim(hunter, [prey], [hunter]) is not None
    # A grazer turns away from a hunter that is near it, also from food.
    drop._sprout(prey.x - 20, prey.y, 0.5)
    away = math.atan2(prey.y - hunter.y, prey.x - hunter.x)
    assert drop._aim(prey, [prey], [hunter]) == pytest.approx(away)
    assert drop._aim(prey, [prey], []) != pytest.approx(away)


def test_a_kind_that_is_gone_comes_back_from_its_cysts(world: ModuleType) -> None:
    drop = empty(world)
    starving = put(world, drop, world.HUNTER, 0, 0, energy=0.01, speed=1.3, generation=6)
    drop._step(0.2)
    assert not drop.cells and list(drop.cysts[world.HUNTER]) == [starving]
    # A hunter's cyst waits for grazers to live on.
    drop.cysts[world.GRAZER].append(world.Cell(0, world.GRAZER, 0, 0, 0, 0, size=0.8, line=3))
    for _ in range(40):
        drop._step(0.2)
    assert drop.of(world.GRAZER) and not drop.of(world.HUNTER)
    assert all(c.line == 3 for c in drop.of(world.GRAZER))
    for _ in range(world.PREY):
        put(world, drop, world.GRAZER, 200, 200)
    for _ in range(100):
        drop._step(0.2)
    back = drop.of(world.HUNTER)
    assert back and back[0].speed == pytest.approx(1.3, rel=0.4) and back[0].generation >= 7
    assert any("cysts of them are hatching" in text for *_, text in drop.notes)


def test_the_slide_goes_with_the_cell_that_is_followed(world: ModuleType) -> None:
    drop = empty(world)
    cell = put(world, drop, world.GRAZER, 150, -80)
    assert drop.pick(400, 400) is None and drop.followed is None
    assert drop.pick(153, -78) is cell and drop.followed == cell.id
    for _ in range(20):
        drop._step(0.2)
    assert math.hypot(drop.view.x - cell.x, drop.view.y - cell.y) < 10
    assert drop.view.focus == pytest.approx(cell.z, abs=0.05)
    # Moving the slide by hand lets the cell go, and stays inside the drop.
    drop.pan(5000, 0)
    assert drop.followed is None and (drop.view.x, drop.view.y) == (world.RADIUS, 0)
    # A followed cell that dies is written down.
    drop.pick(cell.x, cell.y)
    cell.energy = -5.0
    drop._step(0.2)
    assert drop.followed is None
    assert any("that was followed starved" in text for *_, text in drop.notes)


def test_only_what_is_in_view_is_sent(example: ModuleType, world: ModuleType) -> None:
    drop = world.World(seed=5)
    everything = len(drop.cells)
    drop.view.objective = 4
    assert len(example.cells(drop)) == everything
    drop.view.objective = 40
    near = example.cells(drop)
    assert 0 < len(near) < everything
    assert all(len(row) == 11 and all(type(n) is int for n in row) for row in near)


def test_the_notebook_says_what_the_generations_brought(world: ModuleType) -> None:
    drop = world.World(seed=5)
    for cell in drop.of(world.GRAZER):
        cell.generation, cell.speed = 5, 1.2
        if cell.line == 0:
            del drop.cells[cell.id]
    drop._step(0.2)
    said = [text for *_, text in drop.notes]
    assert any(t.startswith("Generation 5. The grazers are 20% faster") for t in said)
    assert "The last of the teal line is gone." in said
    # Each is said once.
    drop._step(0.2)
    assert [text for *_, text in drop.notes] == said
    # Each has a number of its own, which the page knows its row by.
    assert len({n for n, *_ in drop.notes}) == len(drop.notes)


# --------------------------------------------------------------- the page


async def test_the_page_shows_the_drop_through_the_microscope(
    page: Page, example: ModuleType
) -> None:
    drop = example.WORLDS[page.session.id]
    scope = page.find("scope")
    assert scope.type == "Scope" and scope.props["on_pan"] and scope.props["on_pick"]
    assert scope.props["view"]["objective"] == 10 and scope.props["view"]["radius"] == 200
    assert len(scope.props["algae"]) == sys.modules["world"].ALGAE
    assert len(scope.props["cells"]) == len(example.cells(drop)) > 0
    assert page.find(ui.Stat, label="Grazers").props["value"] == "24"
    assert "A drop of water, with four lines of grazers and three hunters." in page.text()


async def test_the_controls_set_the_microscope(page: Page, example: ModuleType) -> None:
    view = example.WORLDS[page.session.id].view
    await page.change("objective", "40")
    await page.change("field", "dark")
    await page.change("stain", "speed")
    await page.change("focus", 80)
    await page.change("lamp", 30)
    assert (view.objective, page.state.field, page.state.stain) == (40, "dark", "speed")
    assert (view.focus, view.lamp) == (0.8, 0.3)
    sent = page.find("scope").props["view"]
    assert (sent["radius"], sent["field"], sent["focus"], sent["lamp"]) == (60.0, "dark", 0.8, 0.3)
    # The wheel goes one objective at a time and stops at the last.
    for by, objective in ((1, 40), (-1, 10), (-1, 4), (-1, 4)):
        await page.event("scope", "zoom", by)
        assert view.objective == objective
    # What is no setting of a microscope is not heard by a control.
    for node, payload in (
        ("objective", "7"),
        ("objective", [10]),
        ("field", "x-ray"),
        ("stain", ["speed"]),
        ("stain", {"by": "speed"}),
        ("focus", "deep"),
        ("focus", None),
        ("lamp", [100]),
        ("lamp", float("nan")),
        ("pace", 4),
    ):
        with pytest.raises(LookupError):
            await page.event(node, "change", payload)
    # The scope's own events are the app's to read, and it fails on none.
    await page.event("scope", "pan", {"x": "left", "y": None})
    await page.event("scope", "pan", [1, 2])
    await page.event("scope", "pick", {"x": float("nan"), "y": 0})
    await page.event("scope", "zoom", "in")
    assert (view.objective, page.state.field, page.state.stain) == (4, "dark", "speed")
    assert (view.focus, view.lamp, view.x, view.y) == (0.8, 0.3, 0.0, 0.0)


async def test_a_press_on_a_cell_follows_it(page: Page, example: ModuleType) -> None:
    drop = example.WORLDS[page.session.id]
    cell = drop.of(0)[0]
    await page.event("scope", "pick", {"x": cell.x + 2, "y": cell.y})
    assert page.find("scope").props["followed"] == cell.id
    card = page.find("followed")
    assert card.props["title"].startswith("A grazer of the ")
    assert "Generation 1, 0 seconds old." in page.text()
    await page.click("let-go")
    assert drop.followed is None and not page.find_all("followed")
    # Dragging the slide lets a cell go as well, and so does the focus.
    await page.event("scope", "pick", {"x": cell.x, "y": cell.y})
    await page.event("scope", "pan", {"x": 120.5, "y": -40})
    assert drop.followed is None and (drop.view.x, drop.view.y) == (120.5, -40.0)
    await page.event("scope", "pick", {"x": cell.x, "y": cell.y})
    assert drop.followed == cell.id
    await page.change("focus", 20)
    assert drop.followed is None


async def test_the_clock_moves_the_drop_and_the_page_goes_with_it(
    page: Page, example: ModuleType
) -> None:
    drop = example.WORLDS[page.session.id]
    before = page.find("scope").props["cells"]
    drop.tick(0.2)
    await page.settle()
    assert drop.time == pytest.approx(0.2) and page.find("scope").props["cells"] != before
    # Four times as fast is four steps to a tick, and a pause is none.
    await page.change("pace", "4")
    drop.tick(0.2)
    assert drop.time == pytest.approx(1.0)
    await page.change("pace", "0")
    patches = len(page.patches)
    drop.tick(0.2)
    await page.settle()
    assert drop.time == pytest.approx(1.0) and len(page.patches) == patches


async def test_the_pipette_adds_cells_and_a_new_slide_starts_over(
    page: Page, example: ModuleType
) -> None:
    drop = example.WORLDS[page.session.id]
    await page.choose("pipette", "hunters")
    await page.choose("pipette", "grazers")
    # No more hunters than the drop holds, which is five.
    assert (len(drop.of(1)), len(drop.of(0))) == (sys.modules["world"].MOST[1], 36)
    assert "Three hunters were added from the pipette." in page.text()
    drop.tick(0.2)
    await page.click(page.find(ui.Button, label="New slide"))
    fresh = example.WORLDS[page.session.id]
    assert fresh is not drop and fresh.time == 0 and len(fresh.of(1)) == 3
    # The page goes with the new drop, through the signal it followed.
    assert fresh.changed is drop.changed
    patches = len(page.patches)
    fresh.tick(0.2)
    await page.settle()
    assert len(page.patches) == patches + 1


async def test_everyone_has_a_drop_of_their_own(example: ModuleType, world: ModuleType) -> None:
    example.TICK = 3600
    harness = TestApp(example.app)
    async with harness.open("/") as one, harness.open("/") as two:
        await one.change("objective", "40")
        mine, theirs = (example.WORLDS[p.session.id] for p in (one, two))
        assert mine is not theirs and (mine.view.objective, theirs.view.objective) == (40, 10)
    assert example.WORLDS == {}


async def test_a_drop_that_fails_does_not_stop_the_clock_for_the_others(
    example: ModuleType, world: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    example.World = partial(world.World, seed=7)
    example.TICK = 0.01
    harness = TestApp(example.app)
    async with harness.open("/") as one, harness.open("/") as two:
        broken, sound = (example.WORLDS[p.session.id] for p in (one, two))
        broken.cells[0] = None  # what no drop holds, and no step gets past
        await asyncio.sleep(0.2)
        # The broken one is first in line, and the other still gets its turn.
        assert "a drop could not be moved on" in caplog.text
        assert sound.time > 0.5 and sound.cells
        broken.cells.clear()
