"""A drop of water on a slide, and what lives in it.

Algae grow where the lamp of the microscope shines, which is where the
person is looking. Grazers eat the algae, hunters eat the grazers, and a
cell that has eaten enough divides in two. A daughter has the speed, the
size, the senses and the color of its parent, each a little changed, so
over the generations the cells become what the drop asks of them.

Nothing here knows of a page. The world is moved on by ``tick``, with
the seconds that went by, and says through its signal that it changed.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import millwork as mw

# The drop is round, this many micrometers from its middle to its edge.
RADIUS = 600.0
# How far from the middle of the view each objective shows.
OBJECTIVES = {4: 600.0, 10: 200.0, 40: 60.0}
# Algae are counted by the square they are in, so many to a square, and
# the drop holds so many in all.
SQUARE, CROWD, ALGAE = 30.0, 2, 420
# The most there can be of each kind of cell.
GRAZER, HUNTER = 0, 1
MOST = (64, 5)
# The lines the first grazers founded, by the color they have.
LINES = ("teal", "violet", "amber", "rose")
HUES = (176.0, 272.0, 40.0, 334.0)
# The algae that grow in a second: under the lamp at its brightest, and
# in the whole drop by the light of the room.
LIT, DAYLIGHT = 22.0, 7.0
# What a daughter's traits may be, as a share of a founder's.
LEAST, UTMOST = 0.45, 2.4
# What a founder of each kind is: how large and how fast, how far it
# notices things, what it costs a second to be one, the energy it divides
# at, and how old it gets. A hunter gets MEAL from a grazer of that size.
SIZE, PACE, REACH = (7.0, 15.0), (26.0, 34.0), (70.0, 170.0)
UPKEEP, FULL, SPAN, MEAL = (0.4, 0.15), (5.0, 14.0), (80.0, 240.0), 6.0
# A hunter hunts while it has less than this share of the energy it divides at.
HUNGRY = 0.6
# A cell that starves or dies of age may leave a cyst, which keeps what it was. Cysts
# hatch when there are fewer cells of their kind than this, and for the
# hunters only when there are this many grazers to live on.
SCARCE, PREY = (8, 2), 24


@dataclass
class Cell:
    id: int
    kind: int
    x: float
    y: float
    z: float
    heading: float
    # What a daughter gets from its parent. A founder's speed, size and
    # sense are 1.
    speed: float = 1.0
    size: float = 1.0
    sense: float = 1.0
    hue: float = 0.0
    line: int = 0
    energy: float = 2.5
    age: float = 0.0
    generation: int = 1
    divided: int = 0
    eaten: int = 0

    @property
    def radius(self) -> float:
        return SIZE[self.kind] * self.size

    @property
    def reach(self) -> float:
        """How far it notices food, and what hunts it."""
        return REACH[self.kind] * self.sense

    @property
    def pace(self) -> float:
        return PACE[self.kind] * self.speed

    @property
    def upkeep(self) -> float:
        """The energy a second it takes to be this cell. Being large,
        fast or sharp of sense each costs."""
        cost = 0.5 * self.size**2 + 0.35 * self.speed**2 + 0.15 * self.sense
        return UPKEEP[self.kind] * cost

    @property
    def full(self) -> float:
        """The energy at which it divides."""
        return FULL[self.kind] * self.size

    @property
    def hungry(self) -> bool:
        return self.energy < HUNGRY * self.full

    @property
    def span(self) -> float:
        """How old it gets, in seconds."""
        return SPAN[self.kind]


@dataclass
class View:
    """What the microscope is set to. The lamp shines on what is in view."""

    x: float = 0.0
    y: float = 0.0
    objective: int = 10
    # The depth that is sharp, from 0 at the glass to 1 at the top.
    focus: float = 0.5
    lamp: float = 0.6

    @property
    def radius(self) -> float:
        return OBJECTIVES[self.objective]


@dataclass
class World:
    seed: int | None = None
    changed: mw.Signal = field(default_factory=mw.Signal)
    view: View = field(default_factory=View)
    cells: dict[int, Cell] = field(default_factory=dict)
    # Each alga has a place in this list for as long as it lives, so the
    # tab is sent the ones that came and went and not the whole list.
    algae: list[tuple[float, float, float] | None] = field(default_factory=lambda: [None] * ALGAE)
    time: float = 0.0
    temperature: float = 22.0
    # How many times faster than a clock the drop runs. 0 is paused.
    pace: int = 1
    followed: int | None = None
    # The cysts of each kind, as the cells that left them.
    cysts: tuple[deque[Cell], deque[Cell]] = field(
        default_factory=lambda: (deque(maxlen=24), deque(maxlen=6))
    )
    # What was written down, the newest first: its number, when, and what.
    notes: deque[tuple[int, float, str]] = field(default_factory=lambda: deque(maxlen=40))
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=90))

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._made = self._noted = 0
        self._squares: dict[tuple[int, int], list[int]] = {}
        self._free = list(range(ALGAE - 1, -1, -1))
        self._sampled = 0.0
        self._told: set[str] = set()
        for line in range(len(LINES)):
            self.add(GRAZER, 6, line=line)
        self.add(HUNTER, 3)
        for _ in range(170):
            self._sprout(*self._within(0.0, 0.0, 300.0), self._rng.random())
        self.note("A drop of water, with four lines of grazers and three hunters.")
        self._sample()

    # ------------------------------------------------------ the microscope

    def pan(self, x: float, y: float) -> None:
        """Move the slide so that this place is in the middle."""
        far = math.hypot(x, y)
        scale = min(1.0, RADIUS / far) if far else 1.0
        self.view.x, self.view.y = x * scale, y * scale
        self.followed = None

    def pick(self, x: float, y: float) -> Cell | None:
        """Follow the cell at this place, or none when there is none."""
        near = min(self.cells.values(), key=lambda c: math.hypot(c.x - x, c.y - y), default=None)
        # A little beside it counts, and more so the weaker the objective.
        room = self.view.radius / 40 + 6
        hit = near is not None and math.hypot(near.x - x, near.y - y) < near.radius * 1.8 + room
        self.followed = near.id if near is not None and hit else None
        return near if hit else None

    def add(self, kind: int, count: int, line: int | None = None) -> None:
        """Put cells in from a pipette, around the middle of the view."""
        for _ in range(count):
            if sum(c.kind == kind for c in self.cells.values()) >= MOST[kind]:
                return
            spread = 150.0 if kind == GRAZER else 380.0
            x, y = self._within(self.view.x, self.view.y, spread)
            own = self._rng.randrange(len(LINES)) if line is None else line
            self._made += 1
            self.cells[self._made] = Cell(
                self._made,
                kind,
                x,
                y,
                self._rng.random(),
                self._rng.uniform(0, math.tau),
                hue=HUES[own] if kind == GRAZER else 12.0,
                line=own if kind == GRAZER else -1,
                energy=2.5 if kind == GRAZER else 6.0,
            )

    def note(self, text: str) -> None:
        self._noted += 1
        self.notes.appendleft((self._noted, self.time, text))

    @property
    def warmth(self) -> float:
        """How much faster everything goes for the warmth of the water."""
        return 1.0 + 0.045 * (self.temperature - 22.0)

    def of(self, kind: int) -> list[Cell]:
        return [c for c in self.cells.values() if c.kind == kind]

    # ------------------------------------------------------------ the clock

    def tick(self, seconds: float) -> None:
        """Move the drop on by a step of that much time, or by four of
        them when it runs fast. A step is short enough that a cell does
        not jump over its food."""
        if not self.pace:
            return
        for _ in range(self.pace):
            self._step(seconds)
        if self.time - self._sampled >= 2.0:
            self._sample()
        self.changed.fire()

    def _step(self, dt: float) -> None:
        self.time += dt
        self.temperature += (16.0 + 14.0 * self.view.lamp - self.temperature) * min(1.0, dt / 20)
        warm = self.warmth
        self._grow(dt)
        grazers, hunters = self.of(GRAZER), self.of(HUNTER)
        for cell in (*grazers, *hunters):
            cell.age += dt * warm
            cell.energy -= cell.upkeep * warm * dt
            self._move(cell, self._aim(cell, grazers, hunters), warm, dt)
        self._apart(grazers)
        self._apart(hunters)
        for hunter in hunters:
            for prey in grazers if hunter.hungry else ():
                near = math.hypot(prey.x - hunter.x, prey.y - hunter.y)
                if prey.id in self.cells and near < hunter.radius + prey.radius * 0.5:
                    hunter.energy += MEAL * prey.size
                    hunter.eaten += 1
                    self._gone(prey, "was eaten by a hunter")
                    break
        for cell in list(self.cells.values()):
            if cell.energy <= 0 or cell.age > cell.span:
                self._gone(cell, "starved" if cell.energy <= 0 else "died of old age")
                # Half the grazers that die so leave a cyst, and every hunter.
                if cell.kind == HUNTER or self._rng.random() < 0.5:
                    self.cysts[cell.kind].append(cell)
            elif cell.energy >= cell.full and len(self.of(cell.kind)) < MOST[cell.kind]:
                self._divide(cell)
        self._hatch(dt)
        if self.followed in self.cells:
            # The slide and the focus go with the cell that is followed.
            one = self.cells[self.followed]
            self.view.x += (one.x - self.view.x) * 0.4
            self.view.y += (one.y - self.view.y) * 0.4
            self.view.focus += (one.z - self.view.focus) * 0.4
        self._milestones()

    def _aim(self, cell: Cell, grazers: list[Cell], hunters: list[Cell]) -> float | None:
        """Where a cell wants to go, as a heading: back into the drop, away
        from a hunter, to food, or nowhere in particular."""
        if math.hypot(cell.x, cell.y) > RADIUS - cell.radius - 8:
            return math.atan2(-cell.y, -cell.x)
        if cell.kind == HUNTER:
            # A hunter that has eaten its fill leaves the grazers be.
            prey = self._nearest(cell, grazers, cell.reach) if cell.hungry else None
            if prey is not None:
                cell.z += (prey.z - cell.z) * 0.04
                return math.atan2(prey.y - cell.y, prey.x - cell.x)
            return None
        threat = self._nearest(cell, hunters, cell.reach * 0.9)
        if threat is not None:
            return math.atan2(cell.y - threat.y, cell.x - threat.x)
        best, at = cell.reach, None
        i, j, n = int(cell.x // SQUARE), int(cell.y // SQUARE), int(cell.reach // SQUARE) + 1
        for a in range(i - n, i + n + 1):
            for b in range(j - n, j + n + 1):
                for slot in self._squares.get((a, b), ()):
                    x, y, z = self.algae[slot]  # type: ignore[misc]
                    far = math.hypot(x - cell.x, y - cell.y)
                    if far < best:
                        best, at = far, (slot, x, y, z)
        if at is None:
            return None
        slot, x, y, z = at
        cell.z += (z - cell.z) * 0.04
        if best < cell.radius + 3:
            self._eat(slot)
            cell.energy += 1.0
            cell.eaten += 1
        return math.atan2(y - cell.y, x - cell.x)

    @staticmethod
    def _nearest(cell: Cell, others: list[Cell], within: float) -> Cell | None:
        best, found = within, None
        for other in others:
            far = math.hypot(other.x - cell.x, other.y - cell.y) - other.radius
            if far < best:
                best, found = far, other
        return found

    def _move(self, cell: Cell, aim: float | None, warm: float, dt: float) -> None:
        if aim is None:
            cell.heading += self._rng.gauss(0, 0.6) * math.sqrt(dt)
            cell.z = min(1.0, max(0.0, cell.z + self._rng.gauss(0, 0.02) * math.sqrt(dt)))
        else:
            # A hunter is the larger cell and comes about more slowly.
            turn = (4.5, 2.4)[cell.kind] * dt
            off = (aim - cell.heading + math.pi) % math.tau - math.pi
            cell.heading += max(-turn, min(turn, off))
        cell.x += math.cos(cell.heading) * cell.pace * warm * dt
        cell.y += math.sin(cell.heading) * cell.pace * warm * dt

    @staticmethod
    def _apart(cells: list[Cell]) -> None:
        """Cells of a kind do not lie on top of each other. Two that
        touch push each other away."""
        for n, a in enumerate(cells):
            for b in cells[n + 1 :]:
                dx, dy, room = b.x - a.x, b.y - a.y, a.radius + b.radius
                if abs(dx) < room and abs(dy) < room and (far := math.hypot(dx, dy)) < room:
                    push = (room - far) / 2 / (far or 0.01)
                    a.x, a.y = a.x - dx * push, a.y - dy * push
                    b.x, b.y = b.x + dx * push, b.y + dy * push

    def _grow(self, dt: float) -> None:
        """New algae. The lamp gives the same light whatever the objective,
        so a view that is small is a bright one, and thick with algae."""
        v = self.view
        for rate, (x, y, r) in (
            (LIT * v.lamp, (v.x, v.y, v.radius)),
            (DAYLIGHT, (0.0, 0.0, RADIUS)),
        ):
            due = rate * dt
            for _ in range(int(due) + (self._rng.random() < due % 1)):
                depth = min(1.0, max(0.0, self._rng.gauss(v.focus, 0.14)))
                self._sprout(*self._within(x, y, r), depth)

    def _hatch(self, dt: float) -> None:
        """A kind that has become scarce is added to from its cysts, with
        the traits of the cells that left them."""
        for kind in (GRAZER, HUNTER):
            few = len(self.of(kind)) < SCARCE[kind]
            fed = kind == GRAZER or len(self.of(GRAZER)) >= PREY
            if few and fed and self.cysts[kind] and self._rng.random() < 0.5 * dt:
                was = self.cysts[kind].popleft()
                self._made += 1
                x, y = self._within(self.view.x, self.view.y, 260.0)
                self.cells[self._made] = Cell(
                    self._made,
                    kind,
                    x,
                    y,
                    self._rng.random(),
                    self._rng.uniform(0, math.tau),
                    was.speed,
                    was.size,
                    was.sense,
                    was.hue,
                    was.line,
                    FULL[kind] * was.size / 2,
                    generation=was.generation + 1,
                )
                if f"hatched-{kind}" not in self._told:
                    self._told.add(f"hatched-{kind}")
                    who = "grazers" if kind == GRAZER else "hunters"
                    self.note(f"The {who} are few, and cysts of them are hatching.")
            elif not few:
                self._told.discard(f"hatched-{kind}")

    def _within(self, x: float, y: float, r: float) -> tuple[float, float]:
        """A place at random, that near to another and inside the drop."""
        while True:
            angle, far = self._rng.uniform(0, math.tau), r * math.sqrt(self._rng.random())
            px, py = x + math.cos(angle) * far, y + math.sin(angle) * far
            if math.hypot(px, py) < RADIUS - 10:
                return px, py

    def _sprout(self, x: float, y: float, z: float) -> None:
        square = self._squares.setdefault((int(x // SQUARE), int(y // SQUARE)), [])
        if self._free and len(square) < CROWD:
            slot = self._free.pop()
            self.algae[slot] = (x, y, z)
            square.append(slot)

    def _eat(self, slot: int) -> None:
        x, y, _ = self.algae[slot]  # type: ignore[misc]
        self._squares[int(x // SQUARE), int(y // SQUARE)].remove(slot)
        self.algae[slot] = None
        self._free.append(slot)

    def _divide(self, cell: Cell) -> None:
        """One cell becomes two daughters, each a little unlike it. The
        one that keeps its number is the one a person goes on following."""
        cell.energy /= 2
        cell.divided += 1
        self._made += 1
        angle = self._rng.uniform(0, math.tau)
        twin = Cell(
            self._made,
            cell.kind,
            cell.x + math.cos(angle) * cell.radius,
            cell.y + math.sin(angle) * cell.radius,
            cell.z,
            angle,
            line=cell.line,
            energy=cell.energy,
            generation=cell.generation + 1,
        )
        self.cells[twin.id] = twin
        had = {trait: getattr(cell, trait) for trait in ("speed", "size", "sense")}
        for daughter in (cell, twin):
            for trait, was in had.items():
                changed = was * math.exp(self._rng.gauss(0, 0.07))
                setattr(daughter, trait, min(UTMOST, max(LEAST, changed)))
        twin.hue = cell.hue + self._rng.gauss(0, 6)
        cell.generation += 1
        cell.age = 0.0

    def _gone(self, cell: Cell, how: str) -> None:
        del self.cells[cell.id]
        if cell.id == self.followed:
            self.followed = None
            self.note(f"The cell that was followed {how}, in its generation {cell.generation}.")

    # ---------------------------------------------------- what is written

    def means(self, kind: int = GRAZER) -> dict[str, float]:
        """The traits of the cells of a kind, on average. 1 is a founder's."""
        cells = self.of(kind) or [Cell(0, kind, 0, 0, 0, 0)]
        return {
            t: sum(getattr(c, t) for c in cells) / len(cells) for t in ("speed", "size", "sense")
        }

    def generation(self) -> int:
        """The latest generation of grazers that is alive."""
        return max((c.generation for c in self.of(GRAZER)), default=0)

    def _sample(self) -> None:
        """A row of the record the charts are drawn from."""
        self._sampled = self.time
        grazers = self.of(GRAZER)
        row: dict[str, Any] = {
            "at": clock(self.time),
            "grazers": len(grazers),
            "hunters": len(self.of(HUNTER)),
            "algae": ALGAE - len(self._free),
            **{t: round(v, 3) for t, v in self.means().items()},
        }
        for n, line in enumerate(LINES):
            row[line] = sum(c.line == n for c in grazers)
        self.history.append(row)

    def _milestones(self) -> None:
        grazers, hunters = self.of(GRAZER), self.of(HUNTER)
        said = []
        latest = self.generation()
        if latest and latest % 5 == 0:
            m = self.means()
            traits = ", ".join(
                f"{abs(v - 1):.0%} {more if v > 1 else less}"
                for v, more, less in (
                    (m["speed"], "faster", "slower"),
                    (m["size"], "larger", "smaller"),
                    (m["sense"], "sharper of sense", "duller of sense"),
                )
            )
            said.append(
                (f"g{latest}", f"Generation {latest}. The grazers are {traits} than the founders.")
            )
        for n, line in enumerate(LINES):
            share = sum(c.line == n for c in grazers)
            if not share and grazers:
                said.append((f"gone-{line}", f"The last of the {line} line is gone."))
            elif len(grazers) >= 20 and share > 0.7 * len(grazers):
                said.append((f"most-{line}", f"Seven in ten grazers are of the {line} line now."))
            if share:
                # A line that comes back from a cyst can be lost again.
                self._told.discard(f"gone-{line}")
        if not hunters:
            said.append(("no-hunters", "The last hunter is gone. Nothing hunts the grazers now."))
        if not grazers:
            said.append(("no-grazers", "The last grazer is gone."))
        for key, text in said:
            if key not in self._told:
                self._told.add(key)
                self.note(text)
        # What was said of a kind that is back is said again when it goes.
        if hunters:
            self._told.discard("no-hunters")
        if grazers:
            self._told.discard("no-grazers")


def clock(seconds: float) -> str:
    """A time as minutes and seconds."""
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"
