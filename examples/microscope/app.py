"""A microscope over a drop of water in which cells eat, are eaten and
divide, and change over the generations. The lamp shines on what is in
view and algae grow in its light, so life gathers where you look.

    uv run millwork run examples/microscope/app.py

The drop is in ``world.py`` and what the microscope shows is drawn by
``components/Scope.jsx``. This file is the page around them: the
controls of the microscope, the record of the drop and the notebook.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Literal

from pydantic import BaseModel
from world import GRAZER, HUNTER, LINES, OBJECTIVES, RADIUS, World, clock

import millwork as mw
from millwork import ui

log = logging.getLogger("microscope")


class State(BaseModel):
    # How the view is drawn, which the drop knows nothing of.
    field: Literal["bright", "dark"] = "bright"
    stain: str = "natural"


app = mw.App("Specimen", state=State)

# Each session's drop, from when the page is opened until it is closed.
WORLDS: dict[str, World] = {}
# The seconds between two steps of every drop, and how much of the drop's
# own time goes by in one. A drop runs slower than a clock, so that there
# is time to look.
TICK, STEP = 0.2, 0.12


@app.on_startup
def start_clock() -> None:
    app.spawn(run(), "the drops' clock")


async def run() -> None:
    """The one clock every drop is moved on by. A drop says that it
    changed, and the session that follows it draws its page again."""
    while True:
        await asyncio.sleep(TICK)
        for world in list(WORLDS.values()):
            try:
                world.tick(STEP)
            except Exception:
                # One drop that fails is not the end of the others.
                log.exception("a drop could not be moved on")


# -------------------------------------------------------------- handlers
#
# The scope is a component of the app's own, so what it emits is read
# here before it is used: a place is two numbers, or the handler does
# nothing. The controls are the framework's, and a handler of theirs gets
# a value its control could have sent.


def number(value: Any) -> float | None:
    real = isinstance(value, int | float) and not isinstance(value, bool)
    return float(value) if real and math.isfinite(value) else None


def place(at: Any) -> tuple[float, float] | None:
    if isinstance(at, dict):
        x, y = number(at.get("x")), number(at.get("y"))
        if x is not None and y is not None:
            return x, y
    return None


def pan(s: mw.Session[State], at: Any) -> None:
    if (to := place(at)) is not None:
        WORLDS[s.id].pan(*to)


def pick(s: mw.Session[State], at: Any) -> None:
    if (to := place(at)) is not None:
        WORLDS[s.id].pick(*to)


def zoom(s: mw.Session[State], by: Any) -> None:
    """The wheel turns to the next objective, or the one before."""
    view, steps = WORLDS[s.id].view, list(OBJECTIVES)
    at = steps.index(view.objective) + (1 if by == 1 else -1)
    view.objective = steps[min(len(steps) - 1, max(0, at))]


# A group of toggles says nothing when the one that is on is pressed
# again, which leaves the setting as it is.


def turn_to(s: mw.Session[State], objective: str | None) -> None:
    if objective is not None:
        WORLDS[s.id].view.objective = int(objective)


def focus(s: mw.Session[State], depth: float) -> None:
    world = WORLDS[s.id]
    world.view.focus = depth / 100
    # The focus is the person's again, and not the followed cell's.
    world.followed = None


def lamp(s: mw.Session[State], light: float) -> None:
    WORLDS[s.id].view.lamp = light / 100


def field(s: mw.Session[State], kind: Literal["bright", "dark"] | None) -> None:
    if kind is not None:
        s.state.field = kind


def stain(s: mw.Session[State], by: str | None) -> None:
    if by is not None:
        s.state.stain = by


def pace(s: mw.Session[State], times: str | None) -> None:
    if times is not None:
        WORLDS[s.id].pace = int(times)


def pipette(s: mw.Session[State], what: str) -> None:
    world = WORLDS[s.id]
    if what == "grazers":
        world.add(GRAZER, 12)
        world.note("Twelve grazers were added from the pipette.")
    else:
        world.add(HUNTER, 3)
        world.note("Three hunters were added from the pipette.")


def new_slide(s: mw.Session[State], _: object) -> None:
    # The new drop says that it changed through the signal of the old
    # one, which is the one this session follows.
    WORLDS[s.id] = World(changed=WORLDS[s.id].changed)


def let_go(s: mw.Session[State], _: object) -> None:
    WORLDS[s.id].followed = None


# ------------------------------------------------------------------ page

# What the cells can be colored by, and how each reads.
STAINS = {
    "natural": ("None", "Each line in its own color"),
    "speed": ("Speed", "Blue is slow, red is fast"),
    "generation": ("Generation", "Violet is early, orange is late"),
    "energy": ("How well fed", "Red is starving, green is fed"),
}


@app.page("/", title="Specimen")
def bench(s: mw.Session[State]) -> ui.Component:
    world = WORLDS[s.id]
    return ui.Page(
        ui.Grid(
            ui.Stack(scope(s, world), controls(s, world), gap=2),
            ui.Stack(counts(world), record(world), followed(world), notebook(world), gap=3),
            cols={"sm": 1, "lg": 2},
            gap=6,
        ),
        header=ui.Header(
            ui.ToggleGroup(
                options=[("0", "Pause"), ("1", "1×"), ("4", "4×")],
                value=str(world.pace),
                size="sm",
                on_change=pace,
                key="pace",
            ),
            ui.DropdownMenu(
                trigger=ui.Button("Pipette", icon="plus", variant="outline", size="sm"),
                items=[
                    ui.MenuItem(id="grazers", label="Add twelve grazers"),
                    ui.MenuItem(id="hunters", label="Add three hunters"),
                ],
                align="end",
                on_select=pipette,
                key="pipette",
            ),
            ui.Button(
                "New slide", icon="rotate-ccw", variant="ghost", size="sm", on_click=new_slide
            ),
            title="Specimen",
        ),
    )


@bench.connect
def put_on_a_slide(s: mw.Session[State]) -> None:
    WORLDS[s.id] = World()
    s.follow(WORLDS[s.id].changed)


@bench.close
def take_it_off(s: mw.Session[State]) -> None:
    WORLDS.pop(s.id, None)


def cells(world: World) -> list[list[int]]:
    """The cells in view and a little around it, as the canvas is given
    them: id, kind, place in tenths, depth, heading, radius in tenths,
    hue, speed, generation, and how full it is, each a whole number."""
    v, far = world.view, world.view.radius * 1.3 + 40
    return [
        [
            c.id,
            c.kind,
            round(c.x * 10),
            round(c.y * 10),
            round(c.z * 100),
            round(math.degrees(c.heading)) % 360,
            round(c.radius * 10),
            round(c.hue) % 360,
            round(c.speed * 100),
            c.generation,
            round(100 * max(0.0, min(1.0, c.energy / c.full))),
        ]
        for c in world.cells.values()
        if math.hypot(c.x - v.x, c.y - v.y) < far
    ]


def scope(s: mw.Session[State], world: World) -> ui.Component:
    view = world.view
    return ui.Custom(
        "Scope",
        props={
            "cells": cells(world),
            # Every alga keeps its place in this list for as long as it
            # lives, so only the ones that came and went are sent.
            "algae": [a and [round(a[0]), round(a[1]), round(a[2] * 100)] for a in world.algae],
            "view": {
                "x": round(view.x, 1),
                "y": round(view.y, 1),
                "radius": view.radius,
                "objective": view.objective,
                "focus": round(view.focus, 3),
                "lamp": view.lamp,
                "field": s.state.field,
                "stain": s.state.stain,
            },
            "drop": RADIUS,
            "followed": world.followed,
            "every": TICK,
        },
        events={"pan": pan, "pick": pick, "zoom": zoom},
        key="scope",
    )


def controls(s: mw.Session[State], world: World) -> ui.Component:
    view = world.view
    return ui.Card(
        ui.Grid(
            ui.Field(
                ui.ToggleGroup(
                    options=[(str(n), f"{n}×") for n in OBJECTIVES],
                    value=str(view.objective),
                    on_change=turn_to,
                    key="objective",
                ),
                label="Objective",
            ),
            ui.Field(
                ui.ToggleGroup(
                    options=[("bright", "Bright"), ("dark", "Dark")],
                    value=s.state.field,
                    on_change=field,
                    key="field",
                ),
                label="Field",
            ),
            ui.Field(
                ui.Select(
                    options=[(key, name) for key, (name, _) in STAINS.items()],
                    value=s.state.stain,
                    on_change=stain,
                    key="stain",
                ),
                label="Stain by",
                help=STAINS[s.state.stain][1],
            ),
            ui.Field(
                ui.Slider(
                    value=round(view.focus * 100), show_value=False, on_change=focus, key="focus"
                ),
                label="Focus",
            ),
            ui.Field(
                ui.Slider(
                    min=10,
                    value=round(view.lamp * 100),
                    show_value=False,
                    on_change=lamp,
                    key="lamp",
                ),
                label="Lamp",
            ),
            ui.Field(
                ui.Text(f"{world.temperature:.1f} °C", cls="tabular-nums leading-9"),
                label="Water",
            ),
            cols={"sm": 2, "md": 3},
            gap=4,
        ),
        key="controls",
    )


def counts(world: World) -> ui.Component:
    history = list(world.history)
    return ui.Grid(
        ui.Stat(label="Generation", value=str(world.generation()), hint=f"at {clock(world.time)}"),
        ui.Stat(
            label="Grazers",
            value=str(len(world.of(GRAZER))),
            trend=[row["grazers"] for row in history],
        ),
        ui.Stat(
            label="Hunters",
            value=str(len(world.of(HUNTER))),
            trend=[row["hunters"] for row in history],
        ),
        cols=3,
        gap=3,
    )


def record(world: World) -> ui.Component:
    """The drop over time: how many grazers each line has, and what the
    grazers have become, with a founder's speed, size and senses as 1."""
    history = list(world.history)
    return ui.Grid(
        ui.Card(
            ui.AreaChart(
                history,
                x="at",
                y={line: line.capitalize() for line in LINES},
                stacked=True,
                height=150,
                key="lines",
            ),
            title="The four lines",
        ),
        ui.Card(
            ui.LineChart(
                history,
                x="at",
                y={"speed": "Speed", "size": "Size", "sense": "Senses"},
                colors={"speed": 5, "size": 1, "sense": 2},
                format="percent",
                height=150,
                key="traits",
            ),
            title="Against the founders",
        ),
        cols={"sm": 1, "md": 2},
        gap=3,
    )


def followed(world: World) -> ui.Component | None:
    cell = world.cells.get(world.followed) if world.followed is not None else None
    if cell is None:
        return None
    kind = "A hunter" if cell.kind == HUNTER else f"A grazer of the {LINES[cell.line]} line"
    return ui.Card(
        ui.Row(
            ui.Stack(
                ui.Text(
                    f"Generation {cell.generation}, {cell.age:.0f} seconds old.", variant="muted"
                ),
                ui.Text(
                    f"Speed {cell.speed:.0%}, size {cell.size:.0%} and senses {cell.sense:.0%}"
                    f" of a founder's. It has eaten {cell.eaten} times and divided {cell.divided}."
                ),
                ui.Progress(value=min(1.0, cell.energy / cell.full), label="Fed enough to divide"),
                gap=2,
                cls="min-w-0 grow",
            ),
            ui.Button("Let it go", variant="outline", size="sm", on_click=let_go, key="let-go"),
            align="start",
            gap=4,
        ),
        title=kind,
        key="followed",
    )


def notebook(world: World) -> ui.Component:
    return ui.Card(
        ui.ScrollArea(
            ui.Stack(
                *(
                    ui.Row(
                        ui.Text(clock(at), variant="muted", cls="w-10 shrink-0 tabular-nums"),
                        ui.Text(text),
                        gap=3,
                        align="start",
                        key=f"note-{n}",
                    )
                    for n, at, text in world.notes
                ),
                gap=2,
            ),
            height="12rem",
        ),
        title="Notebook",
        key="notebook",
    )
