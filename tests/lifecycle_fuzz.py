"""A fuzzer for the life of a session.

It drives a real millwork app through its ASGI surface, the way browsers do:
page loads and sign-ins over HTTP, and each tab over a websocket that speaks
the tab's protocol. A scenario is a list of small actions (a click, a dropped
connection, a role taken away, time passing) chosen at random from a seed.
Time is virtual, so a five-minute grace period or a ten-second hook costs
nothing to wait for, and a scenario runs the same way every time.

The app under test has one of most things a page can hold: buttons, an input,
a form, a table with row actions, a chat that streams its reply, an upload, a
download, a custom component, questions, and tasks that are async, delayed,
failing or run in a thread. Most of it sits in lazy parts under tabs, with
tabs inside one of them, so a scenario spends much of its time talking to
parts of the page that are kept as they were. In some scenarios its sign-in hooks are plain
functions, so they run in threads too. A thread takes turns with the loop
(see ``_Turns``), which keeps such a scenario repeatable.

What makes it a test is the oracle. The app writes down what its own code did
(which handler ran, for whom, when a hook started and finished) and each tab
writes down what it was sent. From that record the checks in ``examine`` ask
whether promises the manual makes were kept: nothing runs on a session that
is over, a page is closed exactly once, a tab is never left on a session it
was not told has ended, nothing is left running at the end.

A tab keeps the page it was sent, node for node, and chooses among its tabs
the way the bundle does. That gives the promises of a page at rest: the tab
holds exactly the page the session has, the session goes by the tab the
browser is on and has drawn by it, nothing is ever looked up in a part of
the page that was kept from an earlier render, and nobody who is done holds
the turn.

Run it from the command line for many seeds, or see ``test_lifecycle_fuzz``:

    uv run python tests/lifecycle_fuzz.py --seeds 500
    uv run python tests/lifecycle_fuzz.py --seed 137 --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import importlib
import json
import logging
import random
import selectors
import shutil
import sys
import tempfile
import threading
import types
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

import millwork as mw
from millwork import auth, marks, ui
from millwork.protocol import pack_frame

ADMIN_MARK = "ADMIN-ONLY-CONTENT"
RECHECK_EVERY = 30.0
GRACE = 60.0
SIGN_IN_LASTS = 900.0
EPOCH = 1_900_000_000.0
# How long anything the fuzzer waits for may take, in virtual seconds, before
# it counts as hung.
PATIENCE = 180.0


# ------------------------------------------------------------------ virtual time


# The step of the clock a scenario runs on. A loop calls a timer as soon as it
# is due within one step, so on a coarse clock, the one Windows has before
# Python 3.13, a timer can be called before its time whenever something else
# wakes the loop just ahead of it.
FINE, COARSE = 1e-9, 1 / 64
# How often the loop may go round with the clock standing still. Nothing in a
# scenario comes near it, so a loop that does is going round for good.
SPIN = 100_000


class Clock:
    def __init__(self, step: float = FINE) -> None:
        self.now = 0.0
        self.step = step


class _Selector:
    """A selector that never sleeps: when nothing is ready it moves the clock
    to the next timer instead."""

    def __init__(self, clock: Clock) -> None:
        self._real = selectors.DefaultSelector()
        self._clock = clock
        self._stood, self._rounds = 0.0, 0

    def select(self, timeout: float | None = None) -> Any:
        if self._clock.now != self._stood:
            self._stood, self._rounds = self._clock.now, 0
        self._rounds += 1
        if self._rounds > SPIN:
            self._rounds = 0
            raise RuntimeError(
                f"the loop went round {SPIN} times at {self._clock.now:.3f} s and time stood still"
            )
        ready = self._real.select(0)
        if ready:
            return ready
        if timeout is None:
            raise RuntimeError("the loop has nothing left to wait for")
        if timeout > 0:
            self._clock.now += timeout
        return []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


_worker = threading.local()


class _Turns:
    """Work for a thread, run so that it and the loop take turns.

    The thread only moves while the loop stands still waiting for it, and it
    hands back when it finishes or when it naps, which lets virtual time pass
    for it. So what a thread does between two naps is one indivisible moment
    to everything on the loop, and a scenario with threads in it runs the
    same way every time. It also cannot be stopped from outside, which is
    true of a real thread and the reason to have it in here."""

    def __init__(self, loop: VirtualLoop, future: Any, work: Any) -> None:
        self.loop, self.future, self.work = loop, future, work
        self.back = threading.Semaphore(0)
        self.on = threading.Semaphore(0)
        self.thread: threading.Thread | None = None
        self.nap_for: float | None = None
        self.finished = False
        self.result: Any = None
        self.error: BaseException | None = None

    def go(self) -> None:
        """On the loop: let the thread run until it finishes or naps."""
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        else:
            self.on.release()
        if not self.back.acquire(timeout=30):
            raise RuntimeError("a worker thread waited on the loop, which was waiting on it")
        if not self.finished:
            self.loop.call_later(self.nap_for or 0.0, self.go)
        elif not self.future.done():
            if self.error is not None:
                self.future.set_exception(self.error)
            else:
                self.future.set_result(self.result)

    def _run(self) -> None:
        _worker.turns = self
        try:
            self.result = self.work()
        except BaseException as exc:
            self.error = exc
        self.finished = True
        self.back.release()

    def nap(self, seconds: float) -> None:
        """In the thread: hand back to the loop for ``seconds`` of its time."""
        if self.loop.over:
            return
        self.nap_for = seconds
        self.back.release()
        self.on.acquire()


class VirtualLoop(asyncio.SelectorEventLoop):
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._turns: list[_Turns] = []
        self.over = False
        super().__init__(selector=_Selector(clock))  # type: ignore[arg-type]
        self._clock_resolution = clock.step

    def time(self) -> float:
        return self._clock.now

    def run_in_executor(self, executor: Any, func: Any, *args: Any) -> Any:
        future = self.create_future()
        turns = _Turns(self, future, lambda: func(*args))
        self._turns.append(turns)
        turns.go()
        return future

    def nap(self, seconds: float) -> None:
        """Called from a worker thread: let ``seconds`` of virtual time pass."""
        turns = getattr(_worker, "turns", None)
        if turns is not None and turns.loop is self:
            turns.nap(seconds)

    def release(self) -> None:
        """The scenario is over: no thread is left waiting for its turn."""
        self.over = True
        for turns in self._turns:
            turns.on.release()


@contextlib.contextmanager
def virtual_time(clock: Clock) -> Any:
    """Point the clocks millwork reads at the virtual one."""
    # By name from the modules table: the package has a ``session`` function
    # that hides the module of that name.
    modules = {
        n: importlib.import_module(f"millwork.{n}") for n in ("session", "auth", "app", "files")
    }

    class Moment(dt.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return dt.datetime.fromtimestamp(EPOCH + clock.now, tz)

    times = types.SimpleNamespace(
        monotonic=lambda: clock.now,
        perf_counter=lambda: clock.now,
        time=lambda: EPOCH + clock.now,
    )
    dates = types.SimpleNamespace(
        datetime=Moment, timedelta=dt.timedelta, UTC=dt.UTC, timezone=dt.timezone
    )
    patched = [(module, "time", times) for module in modules.values()]
    patched.append((modules["auth"], "dt", dates))
    patched.append((modules["auth"], "TICK", clock.step))
    saved = [(module, name, getattr(module, name)) for module, name, _ in patched]
    for module, name, value in patched:
        setattr(module, name, value)
    try:
        yield
    finally:
        for module, name, value in saved:
            setattr(module, name, value)


# ------------------------------------------------------------------ the world and its record


@dataclass
class World:
    """What is true outside the app, which the fuzzer changes as it goes, the
    knobs on the app's own hooks, and the record of everything that happened."""

    clock: Clock
    loop: Any = None
    # Sessions whose page is in its connect hook right now, and sessions
    # with a handler in the middle of a change it has not lent its turn for.
    connecting: set[str] = field(default_factory=set)
    halfway: set[str] = field(default_factory=set)
    # A number every session sees, and the signal that says it changed.
    shared: int = 0
    signal: mw.Signal = field(default_factory=mw.Signal)
    people: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "ada": {"role": "admin", "active": True},
            "cy": {"role": "candidate", "active": True},
        }
    )
    knobs: dict[str, Any] = field(
        default_factory=lambda: {
            "recheck_delay": 0.0,
            "recheck_fails": False,
            "logout_delay": 0.0,
            "logout_fails": False,
            "logout_to": None,
            "connect_delay": 0.0,
            "connect_fails": None,
            "connect_does": None,
            "close_delay": 0.0,
            "close_does": None,
            "handler_delay": 0.1,
            "render_fails": False,
        }
    )
    log: list[dict[str, Any]] = field(default_factory=list)
    # Promises the hooks on the session saw broken, and how often things
    # happened that a run should have had some of.
    broken: list[tuple[str, str]] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    names: dict[str, str] = field(default_factory=dict)
    sessions: list[Any] = field(default_factory=list)
    # What was said about a person, in order: (index in the log, time, who, role, active).
    changes: list[tuple[int, float, str, str, bool]] = field(default_factory=list)
    spans: int = 0

    def note(self, kind: str, **facts: Any) -> dict[str, Any]:
        entry = {"i": len(self.log), "t": round(self.clock.now, 4), "kind": kind, **facts}
        self.log.append(entry)
        return entry

    def name(self, session_id: str | None) -> str | None:
        if session_id is None:
            return None
        return self.names.setdefault(session_id, f"S{len(self.names) + 1}")

    def about(self, s: Any) -> dict[str, Any]:
        user = s.user
        return {
            "sid": self.name(s.id),
            "page": s.page.path,
            "user": user.id if user is not None else None,
            "role": user.claims.get("role") if user is not None else None,
        }

    def begin(self, kind: str, s: Any, **facts: Any) -> int:
        self.spans += 1
        self.note(f"{kind}:begin", span=self.spans, **self.about(s), **facts)
        return self.spans

    def end(self, kind: str, s: Any, span: int, **facts: Any) -> None:
        self.note(f"{kind}:end", span=span, sid=self.name(s.id), **facts)

    def nap(self, seconds: float) -> None:
        """From a worker thread: wait out ``seconds`` of the scenario's time."""
        if seconds > 0 and self.loop is not None:
            self.loop.nap(seconds)

    def change(self, who: str, **what: Any) -> None:
        self.people[who].update(what)
        person = self.people[who]
        entry = self.note("world", who=who, role=person["role"], active=person["active"])
        self.changes.append((entry["i"], entry["t"], who, person["role"], person["active"]))


class State(BaseModel):
    n: int = 0
    # How many rows the page's table has: enough for its updates to travel
    # as edits to the list rather than as the whole list.
    rows: int = 20


def make_bundle() -> Path:
    """A bundle directory with just enough in it for the shell to be served."""
    root = Path(tempfile.mkdtemp(prefix="mw-fuzz-"))
    (root / ".vite").mkdir()
    (root / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "main-abc.js", "isEntry": True, "css": []}})
    )
    return root


BUNDLE = make_bundle()


class Person(BaseModel):
    name: str = Field(min_length=2)
    age: int = Field(18, ge=18)


def make_app(world: World, files: Path, threads: bool = False) -> mw.App:
    """The app under test. With ``threads`` its sign-in hooks are plain
    functions, which millwork runs in worker threads."""
    knobs = world.knobs

    async def verify(username: str, password: str) -> bool:
        return True

    async def admit(identity: auth.Identity) -> auth.User | None:
        person = world.people.get(identity.subject)
        if person is None or not person["active"]:
            return None
        return auth.User(
            id=identity.subject, name=identity.subject, claims={"role": person["role"]}
        )

    async def recheck(user: auth.User) -> auth.User | None:
        world.note("recheck:begin", user=user.id)
        await asyncio.sleep(knobs["recheck_delay"])
        if knobs["recheck_fails"]:
            raise RuntimeError("the people database is away")
        person = world.people[user.id]
        answer = (
            user.model_copy(update={"claims": {"role": person["role"]}})
            if person["active"]
            else None
        )
        world.note("recheck:end", user=user.id, role=person["role"], active=person["active"])
        return answer

    async def on_logout(user: auth.User) -> str | None:
        world.note("on_logout:begin", user=user.id)
        await asyncio.sleep(knobs["logout_delay"])
        if knobs["logout_fails"]:
            raise RuntimeError("no idea where to send them")
        world.note("on_logout:end", user=user.id, to=knobs["logout_to"])
        return knobs["logout_to"]

    def recheck_in_a_thread(user: auth.User) -> auth.User | None:
        world.note("recheck:begin", user=user.id)
        world.nap(knobs["recheck_delay"])
        if knobs["recheck_fails"]:
            raise RuntimeError("the people database is away")
        person = world.people[user.id]
        world.note("recheck:end", user=user.id, role=person["role"], active=person["active"])
        if not person["active"]:
            return None
        return user.model_copy(update={"claims": {"role": person["role"]}})

    def on_logout_in_a_thread(user: auth.User) -> str | None:
        world.note("on_logout:begin", user=user.id)
        world.nap(knobs["logout_delay"])
        if knobs["logout_fails"]:
            raise RuntimeError("no idea where to send them")
        world.note("on_logout:end", user=user.id, to=knobs["logout_to"])
        return knobs["logout_to"]

    app = mw.App(
        "fuzz",
        state=State,
        public=None,
        bundle_dir=BUNDLE,
        files=mw.Files(files),
        secret="fuzz-fuzz-fuzz-fuzz-fuzz-fuzz-fuzz-fuzz",
        session_grace=GRACE,
        max_sessions=6,
        max_sessions_per_client=3,
        auth=auth.Auth(
            [auth.Password(verify)],
            on_login=admit,
            recheck=recheck_in_a_thread if threads else recheck,
            recheck_every=dt.timedelta(seconds=RECHECK_EVERY),
            on_logout=on_logout_in_a_thread if threads else on_logout,
            session=dt.timedelta(seconds=SIGN_IN_LASTS),
        ),
    )

    def handler(name: str, plain: bool = True) -> Any:
        """A handler that writes down when it started and finished, and for
        whom. ``plain`` marks one that never lets another handler in."""

        def wrap(fn: Any) -> Any:
            async def run(s: mw.Session[State], payload: Any) -> Any:
                span = world.begin("handler", s, name=name, plain=plain)
                try:
                    return await fn(s, payload)
                finally:
                    world.end("handler", s, span)

            return run

        return wrap

    def highlight(s: mw.Session[State]) -> None:
        # Marks are set on what the page has and on what it has not, in
        # steps and beside them, and taken off again, wherever the session
        # is in its life by then.
        world.counts["highlights asked for"] += 1
        turn = world.counts["highlights asked for"] % 5
        if turn == 1:
            s.highlight("bump", "blue", step=1)
            s.highlight("point", "orange", step=2, seconds=5)
            s.highlight("end", step=3)
        elif turn == 2:
            s.highlight("shared", "#0a7d5c", label="here")
            s.highlight("not-on-any-page", "red")
        elif turn == 3:
            s.highlight("share", "green", page="/")
        elif turn == 4:
            s.highlight("bump", None)
        else:
            s.highlight(None)

    def shared_changed() -> None:
        # What every session sees changes, and whoever shows it is told.
        world.shared += 1
        world.signal.fire()

    @handler("bump")
    async def bump(s: mw.Session[State], _: Any) -> None:
        s.state.n += 1
        shared_changed()
        highlight(s)

    @handler("share")
    async def share(s: mw.Session[State], _: Any) -> None:
        shared_changed()
        highlight(s)

    @handler("slow")
    async def slow(s: mw.Session[State], _: Any) -> None:
        # In the middle of a change for as long as it waits, with its turn
        # held: the page must not be drawn from what it has half done. It
        # asks for a drawing first, as a handler does that starts a task or
        # says something on the page, so one comes due while it waits.
        world.halfway.add(s.id)
        s.refresh()
        try:
            await asyncio.sleep(knobs["handler_delay"])
        finally:
            world.halfway.discard(s.id)
        s.state.n += 1
        if s.state.n % 2 == 0:
            # Every other time it leaves, with the drawing it asked for
            # still due: the page it leaves is not drawn again.
            s.navigate("/open")

    @handler("end", plain=False)
    async def end(s: mw.Session[State], _: Any) -> None:
        await s.end("The handler ended it.")

    @handler("logout")
    async def logout(s: mw.Session[State], _: Any) -> None:
        s.logout()

    @handler("boom")
    async def boom(s: mw.Session[State], _: Any) -> None:
        raise RuntimeError("the handler broke")

    @handler("confirm", plain=False)
    async def confirm(s: mw.Session[State], _: Any) -> None:
        if await s.confirm("Sure?"):
            s.state.n += 1

    async def work(s: mw.Session[State]) -> None:
        for _ in range(3):
            await asyncio.sleep(0.2)
            world.note("tick", **world.about(s))

    async def finished(s: mw.Session[State], task: Any) -> None:
        span = world.begin("handler", s, name="on_done", plain=True)
        world.end("handler", s, span)

    async def quick(s: mw.Session[State]) -> None:
        await asyncio.sleep(0.3)

    @handler("await_task", plain=False)
    async def await_task(s: mw.Session[State], _: Any) -> None:
        # A handler that waits on its own task, and goes on whatever became
        # of it. Whether it may go on is the session's to say.
        try:
            await s.task(work, s, label="awaited")
        except mw.Cancelled:
            pass
        world.note("tick", after="its task", **world.about(s))
        s.state.n += 1

    @handler("flood")
    async def flood(s: mw.Session[State], _: Any) -> None:
        # More than a session keeps for a tab that is away.
        for i in range(520):
            s.toast(f"note {i}")

    @handler("big_file")
    async def big_file(s: mw.Session[State], _: Any) -> None:
        s.download("big.bin", b"x" * (3 * 1024 * 1024))

    @handler("task")
    async def start_task(s: mw.Session[State], _: Any) -> None:
        s.task(work, s, label="work", on_done=finished)

    @handler("undo")
    async def undo(s: mw.Session[State], _: Any) -> None:
        s.state.n -= 1

    @handler("toast")
    async def toast(s: mw.Session[State], _: Any) -> None:
        s.toast("Changed.", action=("Undo", undo))
        highlight(s)

    @handler("point")
    async def point(s: mw.Session[State], _: Any) -> None:
        # The keyboard is asked for in something the page has, and a
        # component is put back to how it began, both by name, wherever
        # the session is in its life by then.
        s.state.n += 1
        s.focus("bump")
        s.reset("mark")
        highlight(s)

    async def search(s: mw.Session[State], query: Any) -> list[str]:
        span = world.begin("request", s, name="search")
        try:
            await asyncio.sleep(knobs["handler_delay"])
            return ["a", "b"]
        finally:
            world.end("request", s, span)

    def to(path: str) -> Any:
        @handler(f"to {path}")
        async def go(s: mw.Session[State], _: Any) -> None:
            s.navigate(path)

        return go

    def working(s: mw.Session[State], about: dict[str, Any]) -> None:
        """Work for a thread, in steps. Each step looks first at whether it
        has been told to stop, which is the one way a thread can be."""
        reporter = mw.progress()
        for _ in range(3):
            world.nap(0.2)
            reporter.check()
            world.note("tick", thread=True, **about)

    @handler("thread")
    async def start_thread(s: mw.Session[State], _: Any) -> None:
        s.task(working, s, world.about(s), label="thread", on_done=finished)

    @handler("later")
    async def later(s: mw.Session[State], _: Any) -> None:
        s.later(5.0, work, s, label="later")

    async def breaks(s: mw.Session[State]) -> None:
        await asyncio.sleep(0.2)
        raise RuntimeError("the task broke")

    @handler("task_boom")
    async def task_boom(s: mw.Session[State], _: Any) -> None:
        s.task(breaks, s, label="breaks", on_done=finished)

    @handler("one_task")
    async def one_task(s: mw.Session[State], _: Any) -> None:
        s.task(work, s, key="one", replace=True, label="one")

    @handler("ask_form", plain=False)
    async def ask_form(s: mw.Session[State], _: Any) -> None:
        answer = await s.ask(ui.Dialog(ui.Form(Person, key="details"), title="Who?"))
        if answer is not None:
            s.state.n += 1

    @handler("print")
    async def print_page(s: mw.Session[State], _: Any) -> None:
        s.state.n += 1
        s.print()

    @handler("send_file")
    async def send_file(s: mw.Session[State], _: Any) -> None:
        s.download("report.txt", "the numbers")

    @handler("grow")
    async def grow(s: mw.Session[State], _: Any) -> None:
        s.state.rows += 7

    @handler("typed")
    async def typed(s: mw.Session[State], value: Any) -> None:
        s.state.n += 1

    @handler("submitted")
    async def submitted(s: mw.Session[State], value: Any) -> None:
        s.state.n += 1

    @handler("table")
    async def on_table(s: mw.Session[State], payload: Any) -> None:
        await asyncio.sleep(0)
        s.state.n += 1

    @handler("uploaded")
    async def uploaded(s: mw.Session[State], refs: Any) -> None:
        s.state.n += len(refs)

    @handler("rejected")
    async def rejected(s: mw.Session[State], info: Any) -> None:
        s.state.n += 0

    @handler("waved")
    async def waved(s: mw.Session[State], payload: Any) -> None:
        s.state.n += 1

    async def chat(s: mw.Session[State], turn: Any) -> None:
        span = world.begin("handler", s, name="chat", plain=False)
        try:
            async with turn.reply() as reply:
                for word in ("one ", "two ", "three"):
                    await asyncio.sleep(knobs["handler_delay"])
                    await reply.text(word)
        finally:
            world.end("handler", s, span)

    def body(s: mw.Session[State], mark: str) -> ui.Component:
        rows = [{"id": i, "name": f"row {i}", "n": s.state.n + i} for i in range(s.state.rows)]
        world.note(
            "draw",
            sid=world.name(s.id),
            early=s.id in world.connecting,
            halfway=s.id in world.halfway,
            # On the tab already, another page asked for, and drawn at its
            # own time: this one is being left. A page that is put on the
            # tab for the first time while the next is already asked for is
            # not, and neither is one drawn for a handler in its turn, which
            # needs the page as it stands to find what was pressed.
            leaving=s.stage == "ready"
            and s.turn.free
            and s.tree is not None
            and s.tree is not s._failure
            and bool(s._wanted or getattr(s, "fuzz_leaving", False)),
        )
        if knobs["render_fails"]:
            raise RuntimeError("the page function fails")

        @ui.lazy
        def work_part(s: mw.Session[State], rows: list[dict[str, Any]]) -> ui.Component:
            world.note("part", sid=world.name(s.id), part="work")
            return ui.Stack(
                ui.Input(key="input", on_change=typed),
                ui.Form(Person, key="form", on_submit=submitted),
                ui.Table(
                    rows=rows,
                    key="table",
                    selection="rows",
                    row_actions=[
                        ui.MenuItem(id="open", label="Open"),
                        ui.MenuItem(id="remove", label="Remove", confirm="Remove it?"),
                    ],
                    on_select=on_table,
                    on_row_click=on_table,
                    on_action=on_table,
                    on_sort=on_table,
                    on_filter=on_table,
                ),
                ui.FileUpload(key="upload", max_size_mb=1, on_upload=uploaded, on_reject=rejected),
                ui.Download(filename="page.txt", content="what the page holds", key="download"),
                ui.Custom("Widget", key="custom", events={"wave": waved}),
                ui.Combobox(key="combo", on_search=search),
                ui.Button("slow", key="slow2", on_click=slow),
                ui.Button("confirm", key="confirm2", on_click=confirm),
                ui.Button("admin", key="admin2", on_click=to("/admin")),
                key="work",
            )

        @ui.lazy
        def talk_part(s: mw.Session[State]) -> ui.Component:
            world.note("part", sid=world.name(s.id), part="talk")
            return ui.Stack(
                ui.Chat(key="chat", on_message=chat),
                ui.Button("bump", key="bump2", on_click=bump),
                ui.Button("end", key="end2", on_click=end),
                ui.Button("ask_form", key="ask_form2", on_click=ask_form),
                ui.Button("task", key="task2", on_click=start_task),
                ui.Button("home", key="home2", on_click=to("/")),
                ui.Tabs(
                    ui.Tab(inner_part(s, "x"), id="x", label="X"),
                    ui.Tab(inner_part(s, "y"), id="y", label="Y"),
                    key="inner",
                ),
                key="talk",
            )

        @ui.lazy
        def inner_part(s: mw.Session[State], name: str) -> ui.Component:
            return ui.Stack(
                ui.Button("bump", key=f"bump-{name}", on_click=bump),
                ui.Button("open", key=f"open-{name}", on_click=to("/open")),
                ui.Button("grow", key=f"grow-{name}", on_click=grow) if s.state.n % 2 else None,
            )

        return ui.Page(
            ui.Text(f"{mark} n={s.state.n}", key="mark"),
            ui.Text(f"shared={world.shared}", key="shared"),
            ui.Button("share", key="share", on_click=share),
            ui.Button("point", key="point", on_click=point),
            ui.Button("await_task", key="await_task", on_click=await_task),
            ui.Button("flood", key="flood", on_click=flood),
            ui.Button("big_file", key="big_file", on_click=big_file),
            ui.Button("thread", key="thread", on_click=start_thread),
            ui.Button("later", key="later", on_click=later),
            ui.Button("task_boom", key="task_boom", on_click=task_boom),
            ui.Button("one_task", key="one_task", on_click=one_task),
            ui.Button("ask_form", key="ask_form", on_click=ask_form),
            ui.Button("print", key="print", on_click=print_page),
            ui.Button("send_file", key="send_file", on_click=send_file),
            ui.Button("grow", key="grow", on_click=grow),
            ui.Button("bump", key="bump", on_click=bump),
            ui.Button("slow", key="slow", on_click=slow),
            ui.Button("end", key="end", on_click=end),
            ui.Button("logout", key="logout", on_click=logout),
            ui.Button("boom", key="boom", on_click=boom),
            ui.Button("confirm", key="confirm", on_click=confirm),
            ui.Button("task", key="task", on_click=start_task),
            ui.Button("toast", key="toast", on_click=toast),
            ui.Button("home", key="home", on_click=to("/")),
            ui.Button("admin", key="admin", on_click=to("/admin")),
            ui.Button("open", key="open", on_click=to("/open")),
            ui.Tabs(
                ui.Tab(ui.Text("plain"), id="a", label="A"),
                ui.Tab(work_part(s, rows), id="b", label="B"),
                ui.Tab(talk_part(s), id="c", label="C"),
                key="tabs",
            ),
        )

    def is_admin(user: auth.User) -> bool:
        return user.claims.get("role") == "admin"

    def owns(user: auth.User, owner: str) -> bool:
        return user.id == owner

    async def connect(s: mw.Session[State], **params: Any) -> None:
        span = world.begin("connect", s)
        world.connecting.add(s.id)
        ok = False
        # Before anything that can fail: a page that does not come must not
        # leave the session following for it.
        s.follow(world.signal)
        try:
            await asyncio.sleep(knobs["connect_delay"])
            if knobs["connect_does"] == "task":
                await s.task(quick, s, label="for connect")
            if knobs["connect_fails"] == "forbidden":
                raise mw.Forbidden("Not today.")
            if knobs["connect_fails"] == "boom":
                raise RuntimeError("connect broke")
            ok = True
        finally:
            world.connecting.discard(s.id)
            world.end("connect", s, span, ok=ok)

    async def close(s: mw.Session[State]) -> None:
        span = world.begin("close", s)
        try:
            await asyncio.sleep(knobs["close_delay"])
            if knobs["close_does"] == "end":
                await s.end("The close hook ended it.")
            if knobs["close_does"] == "boom":
                raise RuntimeError("close broke")
        finally:
            world.end("close", s, span)

    for path, mark, options in (
        ("/", "home", {}),
        ("/admin", ADMIN_MARK, {"allow": is_admin}),
        ("/open", "open to all", {"public": True}),
        ("/desk/{owner}", "a desk", {"allow": owns}),
    ):
        page = app.page(path, **options)(lambda s, mark=mark: body(s, mark))
        page.connect(connect)
        page.close(close)
    return app


# ------------------------------------------------------------------ browsers and tabs


class Tab:
    """One websocket connection, as a tab makes it. It keeps what the server
    sent, and can stop listening, which is a tab whose computer went to sleep."""

    def __init__(self, sim: Sim, number: int, browser: Browser, path: str) -> None:
        self.sim, self.number, self.browser, self.path = sim, number, browser, path
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.hearing = asyncio.Event()
        self.hearing.set()
        self.session: str | None = None
        self.resume: str | None = None
        self.last_seq = 0
        self.sent = 1
        self.gone = False
        self.accepted = False
        self.server_closed = False
        self.fatal: str | None = None
        self.left_for: str | None = None
        self.leaving = False
        self.received: list[dict[str, Any]] = []
        self.task: asyncio.Task[Any] | None = None
        # Requests the tab has made and not had an answer to: what each was for.
        self.asked: dict[str, tuple[str, str]] = {}
        self.files: list[str] = []
        # What the tab wants to say before it has a session. The bundle keeps
        # it until the server has said which session this is.
        self.unsent: list[dict[str, Any]] = []
        # The page as the tab holds it: every node it was sent, with the
        # patches since applied.
        self.nodes: dict[str, dict[str, Any]] = {}
        # The highlights the tab has, as it was last given them, and the
        # session whose page the tab has when it comes back on a new socket.
        self.marks: list[dict[str, Any]] = []
        self.page_of: str | None = None
        # Whether the page that comes next is another one than the tab is on.
        self.another = False
        # Which tab each ``Tabs`` that keeps its own choice is on, and what
        # the tab last told the server about it.
        self.on: dict[str, str] = {}
        self.told: dict[str, str] = {}
        # True once it has said something about its tabs that is not so.
        self.lied = False

    @property
    def label(self) -> str:
        return f"T{self.number}"

    def open(self, resume_from: Tab | None = None, seq: int | None = None) -> None:
        cookies = "; ".join(f"{c.name}={c.value}" for c in self.browser.http.cookies.jar)
        headers = [(b"host", b"app"), (b"origin", b"http://app")]
        if cookies:
            headers.append((b"cookie", cookies.encode()))
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": "/_mw/ws",
            "raw_path": b"/_mw/ws",
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "client": (f"10.0.0.{self.browser.number}", 40000 + self.number),
            "server": ("app", 80),
            "subprotocols": [],
            "state": {},
        }
        hello: dict[str, Any] = {"type": "hello", "path": self.path, "protocol": 5}
        if resume_from is not None and resume_from.session is not None:
            seq = resume_from.last_seq if seq is None else seq
            hello.update(session=resume_from.session, resume=resume_from.resume, seq=seq)
        self.inbox.put_nowait({"type": "websocket.connect"})
        self.inbox.put_nowait(
            {"type": "websocket.receive", "text": json.dumps({"seq": 0, "msg": hello})}
        )
        self.task = asyncio.get_running_loop().create_task(
            self.sim.asgi(scope, self._receive, self._send), name=f"tab {self.number}"
        )

    def carry(self, old: Tab) -> None:
        """Go on with the page another connection of this tab had: the page
        in the browser outlives its socket."""
        self.nodes = {i: json.loads(json.dumps(n)) for i, n in old.nodes.items()}
        self.on = dict(old.on)
        self.marks = [dict(m) for m in old.marks]
        self.page_of = old.session
        self.another = old.another

    def patch(self, ops: list[dict[str, Any]]) -> None:
        nodes = self.nodes
        for op in ops:
            kind = op["op"]
            if kind == "add":
                nodes[op["node"]["id"]] = op["node"]
            elif kind == "remove":
                nodes.pop(op["id"], None)
            elif kind == "set":
                nodes[op["id"]]["props"].update(op["props"])
            elif kind == "unset":
                for key in op["keys"]:
                    nodes[op["id"]]["props"].pop(key, None)
            elif kind == "children":
                nodes[op["id"]]["children"] = list(op["children"])
            elif kind == "splice":
                old = nodes[op["id"]]["props"][op["prop"]]
                new: list[Any] = []
                at = 0
                for start, delete, items in op["edits"]:
                    new += old[at:start]
                    new += items
                    at = start + delete
                nodes[op["id"]]["props"][op["prop"]] = new + old[at:]

    def own_tabs(self) -> dict[str, list[str]]:
        """The ``Tabs`` on the page that keep their own choice, each with the
        ids of its tabs."""
        out: dict[str, list[str]] = {}
        for node_id, node in self.nodes.items():
            if node["type"] == "Tabs" and "value" not in node["props"]:
                tabs = [self.nodes[c] for c in node["children"] if c in self.nodes]
                out[node_id] = [c["props"]["id"] for c in tabs if c["type"] == "Tab"]
        return out

    def look(self) -> None:
        """What the bundle does when the page changed under it. ``Tabs`` that
        are new open on their default, or their first tab. One whose tab is
        gone moves to the first. And what the server asked to be told, with
        ``track``, is said when it is new or other than what was said last."""
        tabs = self.own_tabs()
        for gone in [i for i in self.on if i not in tabs]:
            del self.on[gone]
            self.told.pop(gone, None)
        for node_id, ids in tabs.items():
            props = self.nodes[node_id]["props"]
            if node_id not in self.on:
                self.on[node_id] = str(props.get("default") or (ids[0] if ids else ""))
            if self.on[node_id] not in ids and ids:
                self.on[node_id] = ids[0]
            if not props.get("track"):
                self.told.pop(node_id, None)
            elif self.told.get(node_id) != self.on[node_id]:
                self.told[node_id] = self.on[node_id]
                self.say(
                    {"type": "event", "node": node_id, "name": "show", "payload": self.on[node_id]}
                )

    def in_view(self, node_id: str) -> bool:
        """Whether a person could get at a node: every tab it sits under is
        the open one of its ``Tabs``."""
        above = {c: i for i, n in self.nodes.items() for c in n["children"]}
        while node_id in above:
            parent = above[node_id]
            if self.nodes[node_id]["type"] == "Tab" and self.nodes[parent]["type"] == "Tabs":
                props = self.nodes[parent]["props"]
                on = props["value"] if "value" in props else self.on.get(parent)
                if on != self.nodes[node_id]["props"]["id"]:
                    return False
            node_id = parent
        return True

    def say(self, message: dict[str, Any]) -> None:
        text = json.dumps({"seq": self.sent, "msg": message})
        self.sent += 1
        self._put({"type": "websocket.receive", "text": text})

    def _put(self, item: dict[str, Any]) -> None:
        if self.session is None:
            self.unsent.append(item)
        else:
            self.inbox.put_nowait(item)

    def ask(self, kind: str, node: str, **fields: Any) -> str:
        """Make a request, and remember what it was for."""
        request = f"q{self.number}x{self.sent}"
        self.asked[request] = (kind, node)
        self.say({"type": "request", "request": request, "node": node, **fields})
        return request

    def bytes(self, request: str, data: bytes) -> None:
        """A binary frame for an upload in flight."""
        self._put({"type": "websocket.receive", "bytes": pack_frame(request, data)})

    def drop(self) -> None:
        if not self.gone:
            self.gone = True
            self.hearing.set()
            self.inbox.put_nowait({"type": "websocket.disconnect", "code": 1006})

    async def _receive(self) -> dict[str, Any]:
        return await self.inbox.get()

    async def _send(self, event: dict[str, Any]) -> None:
        kind = event["type"]
        if kind == "websocket.accept":
            self.accepted = True
            return
        if self.gone:
            raise OSError("the tab is gone")
        # When the server sent it, which for a tab that is not listening is
        # some time before the tab gets it.
        sent = len(self.sim.world.log)
        await self.hearing.wait()
        if self.gone:
            raise OSError("the tab is gone")
        if kind == "websocket.close":
            self.server_closed = True
            self.sim.world.note("tab:closed", tab=self.label, code=event.get("code"))
            return
        if kind != "websocket.send":
            return
        if event.get("text") is None:
            # A frame of a file the tab asked for.
            self.sim.world.note(
                "tab:got",
                tab=self.label,
                type="bytes",
                seq=0,
                sent=sent,
                sid=self.sim.world.name(self.session),
            )
            return
        envelope = json.loads(event["text"])
        seq, msg = envelope["seq"], envelope["msg"]
        kind = msg["type"]
        # As the bundle counts: the message that says which session this is
        # carries the session's number and is not one of the numbered ones,
        # and a numbered one that comes a second time, where a replay
        # overlapped what was being sent, is not taken again.
        again = kind != "session" and 0 < seq <= self.last_seq
        if kind != "session" and seq > self.last_seq:
            self.last_seq = seq
        fact: dict[str, Any] = {"tab": self.label, "type": kind, "seq": seq, "sent": sent}
        if kind == "session":
            if msg["id"] != (self.session or self.page_of):
                # The marks were another session's.
                self.marks = []
            self.session, self.resume = msg["id"], msg["resume"]
            fact["sid"] = self.sim.world.name(msg["id"])
            unsent, self.unsent = self.unsent, []
            for item in unsent:
                self.inbox.put_nowait(item)
            # The socket is open: the session behind it may be a new one, or
            # may have missed what was said, so the tabs are said again.
            self.told.clear()
            self.look()
        elif kind == "mount":
            fact["marked"] = ADMIN_MARK in event["text"]
            if not again:
                self.nodes = msg["nodes"]
                # A page brings its marks.
                self.marks = msg.get("marks", [])
                if self.another:
                    # Its tabs start over, on the tab they open on.
                    self.on, self.another = {}, False
                # A whole page: the tabs that live on in it say again where
                # they are, as the session may have forgotten on the way.
                self.told.clear()
                self.look()
        elif kind == "patch":
            fact["marked"] = ADMIN_MARK in event["text"]
            if not again:
                self.patch(msg["ops"])
                self.look()
        elif kind == "command":
            fact["name"] = msg["name"]
            if msg["name"] == "navigate":
                # Another page, and not the one the tab is on with another
                # query: the body of the page that comes is drawn anew.
                if marks.bare(msg["args"]["path"]) != marks.bare(self.path):
                    self.another = True
                self.path = msg["args"]["path"]
            if msg["name"] == "leave":
                self.left_for = msg["args"]["to"]
                fact["to"] = self.left_for
            if msg["name"] == "marks" and not again:
                self.marks = msg["args"]["list"]
            if msg["name"] == "logout":
                # The tab signs out for its browser and goes, as a real one does.
                self.sim.background(self.sim.sign_out(self.browser.number - 1))
                self.leaving = True
        elif kind == "error":
            fact["fatal"] = msg["fatal"]
            fact["message"] = msg["message"]
            if msg["fatal"]:
                self.fatal = msg["message"]
        elif kind == "stream":
            fact["chunk"] = (msg.get("chunk") or {}).get("type")
        elif kind == "reply":
            what, node = self.asked.pop(msg["request"], ("", ""))
            fact["for"] = what
            fact["error"] = msg.get("error")
            if what == "upload" and isinstance(msg.get("payload"), dict):
                # The upload is in: the tab says so, with what it was given back.
                self.files.append(msg["payload"]["id"])
                self.say(
                    {"type": "event", "node": node, "name": "upload", "payload": [msg["payload"]]}
                )
        if kind == "command" and msg["name"] == "download":
            # Told that a file is ready, the tab fetches it.
            self.files.append(msg["args"]["id"])
            self.ask("file", "root", name="file", payload={"id": msg["args"]["id"]})
        fact["sid"] = fact.get("sid") or self.sim.world.name(self.session)
        self.received.append(self.sim.world.note("tab:got", **fact))
        if self.left_for is not None or self.leaving:
            # Sent away, the page unloads and its socket goes with it.
            self.drop()


class Browser:
    def __init__(self, sim: Sim, number: int) -> None:
        self.number = number
        self.http = httpx.AsyncClient(
            # A failure inside the app is a 500 to a browser, not an exception.
            transport=httpx.ASGITransport(app=sim.asgi, raise_app_exceptions=False),
            base_url="http://app",
        )


class Sim:
    """A running app with the browsers and tabs the scenario has opened."""

    def __init__(self, world: World, app: mw.App) -> None:
        self.world, self.app, self.asgi = world, app, app.asgi
        self.browsers = [Browser(self, n) for n in (1, 2)]
        self.tabs: list[Tab] = []
        self.problems: list[tuple[str, str]] = []
        self._lifespan: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._started = asyncio.Event()
        self._stopped = asyncio.Event()
        self._serving: asyncio.Task[Any] | None = None
        self._background: set[asyncio.Task[Any]] = set()

    # the app's own life

    async def start(self) -> None:
        async def receive() -> dict[str, Any]:
            return await self._lifespan.get()

        async def send(event: dict[str, Any]) -> None:
            if event["type"].startswith("lifespan.startup"):
                self._started.set()
            if event["type"].startswith("lifespan.shutdown"):
                self._stopped.set()

        scope = {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}
        self._serving = asyncio.get_running_loop().create_task(self.asgi(scope, receive, send))
        self._lifespan.put_nowait({"type": "lifespan.startup"})
        await asyncio.wait_for(self._started.wait(), PATIENCE)

    async def stop(self) -> None:
        """Stop the way the server millwork runs under does: connections are
        closed first and given a moment to wind up, what is still running
        for them after that is cancelled, and then the app is told to shut
        down."""
        for tab in self.tabs:
            tab.drop()
        serving = [t.task for t in self.tabs if t.task is not None and not t.task.done()]
        if serving:
            _, late = await asyncio.wait(serving, timeout=5.0)
            for task in late:
                task.cancel()
            await asyncio.wait(late, timeout=5.0) if late else None
        self._lifespan.put_nowait({"type": "lifespan.shutdown"})
        await self.patiently(self._stopped.wait(), "the app's shutdown")

    async def patiently(self, waiting: Any, what: str) -> Any:
        try:
            return await asyncio.wait_for(waiting, PATIENCE)
        except TimeoutError:
            self.problems.append(("hung", f"{what} did not finish in {PATIENCE:g} s"))
            return None

    # what a person at a browser does

    async def sign_in(self, browser: int, who: str) -> None:
        http = self.browsers[browser].http
        http.cookies.clear()
        self.world.note("act:sign_in", browser=browser, who=who)
        await self.patiently(
            http.post("/_mw/auth/login", json={"username": who, "password": "x"}), "a sign-in"
        )

    async def sign_out(self, browser: int) -> None:
        http = self.browsers[browser].http
        self.world.note("act:sign_out", browser=browser)
        await self.patiently(http.post("/_mw/auth/logout"), "a sign-out")
        http.cookies.clear()

    async def open_tab(self, browser: int, path: str, load: bool = True) -> Tab | None:
        """Load a page and connect its tab, as a browser does. ``load=False``
        skips the page load, which a tab that reconnects does, and an attacker."""
        http = self.browsers[browser].http
        where = path
        if load:
            response = await self.patiently(http.get(path), f"the page load of {path}")
            if response is None or "window.__mw = " not in response.text:
                self.world.note("act:load", browser=browser, path=path, got=_status(response))
                return None
            boot = json.loads(response.text.split("window.__mw = ")[1].split(";</script>")[0])
            self.world.note("act:load", browser=browser, path=path, got=response.status_code)
            if "login" in boot or "path" not in boot:
                # The login page, or a plain page for a failure: no tab to connect.
                return None
            where = boot["path"]
        tab = Tab(self, len(self.tabs) + 1, self.browsers[browser], where)
        self.tabs.append(tab)
        self.world.note("act:open", tab=tab.label, browser=browser, path=where)
        tab.open()
        return tab

    def reconnect(self, old: Tab, seq: int | None = None, how: str = "reconnect") -> Tab:
        """The same tab on a new connection, asking for its session back. A
        page that was loaded again asks with nothing seen (``seq=0``)."""
        tab = Tab(self, len(self.tabs) + 1, old.browser, old.path)
        self.tabs.append(tab)
        self.world.note(f"act:{how}", tab=tab.label, was=old.label)
        if how != "reload":
            tab.carry(old)
        tab.open(resume_from=old, seq=seq)
        return tab

    def live(self) -> list[Tab]:
        """Tabs a person could still be using: connected, and not told that
        their session ended, after which a real tab sends nothing more."""
        return [t for t in self.tabs if not t.gone and not t.server_closed and t.fatal is None]

    def background(self, work: Any) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def handlers(self, tab: Tab) -> list[tuple[str, str]]:
        """What the tab could press right now: the handlers of its session's page."""
        session = self.app.sessions.get(tab.session or "")
        if session is None or session.tree is None:
            return []
        return sorted(session.tree.handlers)


def _status(response: Any) -> Any:
    return None if response is None else response.status_code


# ------------------------------------------------------------------ scenarios

PATHS = ("/", "/admin", "/open", "/admin?x=1", "/nowhere", "/desk/ada", "/desk/cy")
# How an upload goes: all of it, part of it and then nothing more, or part of
# it and then the tab is gone.
UPLOADS = ("whole", "whole", "part", "part then gone", "cancel")
# Small steps let things interleave, and the long ones cross a boundary each:
# the notice a tab is given, the hooks' time limit, the recheck interval, the
# grace period, the sign-in's lifetime.
STEPS = (0.0, 0.0, 0.01, 0.05, 0.3, 1.0, 2.5, 11.0, 31.0, 61.0, 70.0, 100.0, 1000.0)
KNOBS: dict[str, tuple[Any, ...]] = {
    "recheck_delay": (0.0, 0.0, 0.3, 12.0),
    "recheck_fails": (False, False, True),
    "logout_delay": (0.0, 0.0, 0.4, 3.0, 12.0),
    "logout_fails": (False, False, True),
    "logout_to": (None, "/open", "https://idp.example/bye"),
    "connect_delay": (0.0, 0.0, 0.3, 2.0),
    "connect_fails": (None, None, None, "forbidden", "boom"),
    "connect_does": (None, None, None, "task"),
    "close_delay": (0.0, 0.0, 0.3, 3.0),
    "close_does": (None, None, None, "end", "boom"),
    "handler_delay": (0.1, 0.5, 3.0),
    "render_fails": (False, False, False, True),
}


def choose(rng: random.Random, sim: Sim, avoid: frozenset[str] = frozenset()) -> tuple[Any, ...]:
    """One thing to do next, picked for the state the simulation is in.
    ``avoid`` leaves kinds of action out, to look past a failure that is
    already known and see what else there is."""
    while True:
        action = _choose(rng, sim)
        if action[0] not in avoid and not (action[0] == "knob" and action[1] in avoid):
            return action


def _choose(rng: random.Random, sim: Sim) -> tuple[Any, ...]:
    live = sim.live()
    kinds = ["wait"] * 5 + ["sign_in"] * 2 + ["open"] * 4 + ["knob"] * 2 + ["world"] * 2
    kinds += ["sign_out", "shutdown_soon"]
    if live:
        kinds += ["click"] * 14 + ["navigate"] * 2 + ["drop"] * 2 + ["deafen", "hear"]
        kinds += ["request", "stale", "answer", "chat", "chat", "upload", "upload", "fetch"]
        kinds += ["request", "reload", "duplicate"] + ["show"] * 8 + ["request"] * 3 + ["lie"]
        kinds += ["rest"] * 6 + ["touch"] * 3
    if sim.app.sessions:
        kinds += ["push"]
    if any(t.gone or t.server_closed for t in sim.tabs):
        kinds += ["reconnect"] * 3
    kind = rng.choice(kinds)
    if kind == "wait":
        return ("wait", rng.choice(STEPS))
    if kind == "sign_in":
        return ("sign_in", rng.randrange(2), rng.choice(["ada", "ada", "cy"]))
    if kind == "sign_out":
        return ("sign_out", rng.randrange(2))
    if kind == "open":
        return ("open", rng.randrange(2), rng.choice(PATHS), rng.random() < 0.8)
    if kind == "knob":
        name = rng.choice(sorted(KNOBS))
        return ("knob", name, rng.choice(KNOBS[name]))
    if kind == "world":
        who = rng.choice(["ada", "ada", "cy"])
        what = rng.choice(["demote", "promote", "remove", "restore"])
        return ("world", who, what)
    if kind == "shutdown_soon":
        return ("wait", 0.0)
    if kind == "push":
        return ("push",)
    if kind == "rest":
        return ("rest",)
    tab = rng.choice(live).number if live else 0
    if kind == "stale" and rng.random() < 0.5:
        open_still = [t.number for t in sim.tabs if not t.gone and not t.server_closed]
        tab = rng.choice(open_still) if open_still else tab
    if kind == "show":
        return ("show", tab, rng.randrange(4), rng.randrange(6))
    if kind == "lie":
        said = rng.choice(["a", "b", "c", "x", "y", "zz", "", 7, None, ["b"]])
        return ("lie", tab, rng.randrange(4), said)
    if kind == "click":
        return ("click", tab, rng.randrange(60), rng.randrange(3))
    if kind == "navigate":
        return ("navigate", tab, rng.choice(PATHS))
    if kind == "chat":
        return (
            "chat",
            tab,
            rng.choice(["message", "message", "stop", "regenerate", "message+stop"]),
        )
    if kind == "upload":
        return ("upload", tab, rng.choice(["small", "small", "big"]), rng.choice(UPLOADS))
    if kind == "fetch":
        return ("fetch", tab, rng.randrange(4))
    if kind == "drop":
        return ("drop", tab)
    if kind == "touch":
        return ("touch", tab, rng.randrange(4), rng.random() < 0.7)
    if kind == "deafen":
        return ("deafen", tab)
    if kind == "hear":
        return ("hear", tab)
    if kind == "request":
        return ("request", tab, rng.choice(["wait", "wait", "cancel"]))
    if kind in ("reload", "duplicate"):
        return (kind, tab)
    if kind == "stale":
        return ("stale", tab, rng.choice(["root/bump", "root/end", "root/admin", "toast:none"]))
    if kind == "answer":
        return ("answer", tab, rng.random() < 0.5)
    gone = [t.number for t in sim.tabs if t.gone or t.server_closed]
    return ("reconnect", rng.choice(gone))


async def perform(sim: Sim, action: tuple[Any, ...]) -> bool:
    """Do one action. False when it does not apply to the state things are in,
    which happens when a scenario is replayed with some of its actions left out."""
    kind, world = action[0], sim.world
    tabs = {t.number: t for t in sim.tabs}
    if kind == "wait":
        await asyncio.sleep(action[1])
        return True
    if kind == "sign_in":
        await sim.sign_in(action[1], action[2])
        return True
    if kind == "sign_out":
        await sim.sign_out(action[1])
        return True
    if kind == "open":
        await sim.open_tab(action[1], action[2], action[3])
        return True
    if kind == "knob":
        world.knobs[action[1]] = action[2]
        world.note("act:knob", name=action[1], value=action[2])
        return True
    if kind == "world":
        who, what = action[1], action[2]
        change = {
            "demote": {"role": "candidate"},
            "promote": {"role": "admin"},
            "remove": {"active": False},
            "restore": {"active": True},
        }[what]
        world.change(who, **change)
        return True
    if kind == "rest":
        # A pause in which nobody does anything, and then a look at every
        # page that has come to rest in it.
        await asyncio.sleep(5.0)
        world.note("act:rest")
        for session in list(sim.app.sessions.values()):
            if session.tree is not None:
                at_rest(sim, session, str(world.name(session.id)))
        return True
    if kind == "push":
        # The app says something to every session at once, as it does when a
        # theme file changes while it is being worked on.
        world.note("act:push")
        sim.app._push_theme()
        return True
    tab = tabs.get(action[1])
    if tab is None:
        return False
    if kind == "reconnect":
        if not (tab.gone or tab.server_closed):
            return False
        sim.reconnect(tab)
        return True
    if tab.gone or tab.server_closed:
        return False
    if tab.fatal is not None and kind != "stale":
        # Told its session ended, a real tab sends nothing more. One that
        # does anyway is somebody trying their luck.
        return False
    if kind == "click":
        # Any event the page has a handler for, with something that event
        # would carry: a click, a change, a submitted form, a table's row.
        handlers = [h for h in sim.handlers(tab) if h[1] not in ("upload", "reject", "search")]
        if not handlers:
            return False
        node, name = handlers[action[2] % len(handlers)]
        variant = action[3] if len(action) > 3 else 0
        world.note("act:event", tab=tab.label, node=node, name=name)
        tab.say({"type": "event", "node": node, "name": name, "payload": carried(name, variant)})
    elif kind == "chat":
        node = next((n for n, name in sim.handlers(tab) if name == "message"), None)
        if node is None:
            return False
        world.note("act:chat", tab=tab.label, what=action[2])
        if action[2] == "message+stop":
            # Both in one read: the stop arrives before the reply has begun.
            tab.say({"type": "event", "node": node, "name": "message", "payload": {"text": "hi"}})
            tab.say({"type": "event", "node": node, "name": "stop", "payload": None})
        else:
            payload = {"text": "hello"} if action[2] == "message" else None
            tab.say({"type": "event", "node": node, "name": action[2], "payload": payload})
    elif kind == "upload":
        node = next((n for n, name in sim.handlers(tab) if name == "upload"), None)
        if node is None:
            return False
        size = 2 * 1024 * 1024 if action[2] == "big" else 2000
        world.note("act:upload", tab=tab.label, size=size, how=action[3])
        details = {"name": "notes.txt", "mime": "text/plain"}
        request = tab.ask("upload", node, name="upload", payload=details, size=size)
        if action[3] == "cancel":
            # Cancelled in the moment it is asked, with the bytes behind it
            # on the wire all the same, in more frames than a stream holds.
            tab.say({"type": "cancel", "request": request})
            for start in range(0, size, 64 * 1024):
                tab.bytes(request, b"a" * min(64 * 1024, size - start))
        else:
            send = size if action[3] == "whole" else size // 2
            for start in range(0, send, 256 * 1024):
                tab.bytes(request, b"a" * min(256 * 1024, send - start))
        if action[3] == "part then gone":
            tab.drop()
    elif kind == "fetch":
        if not tab.files:
            return False
        world.note("act:fetch", tab=tab.label)
        tab.ask("file", "root", name="file", payload={"id": tab.files[action[2] % len(tab.files)]})
    elif kind == "show":
        # A person opens a tab, of the tabs they can get at. The bundle
        # switches at once, tells a handler of the app's if there is one,
        # and tells the server where it asked to be told.
        within = sorted((i, ids) for i, ids in tab.own_tabs().items() if ids and tab.in_view(i))
        if not within:
            return False
        node, ids = within[action[2] % len(within)]
        chosen = ids[action[3] % len(ids)]
        world.note("act:show", tab=tab.label, node=node, open=chosen)
        world.counts["tabs opened"] += 1
        tab.on[node] = chosen
        if tab.nodes[node]["props"].get("on_change"):
            tab.say({"type": "event", "node": node, "name": "change", "payload": chosen})
        tab.look()
    elif kind == "lie":
        # Something about a tab that the bundle would not say: any of the
        # tabs on the page, in view or not, and any word for the open one.
        tabs = sorted(i for i, n in tab.nodes.items() if n["type"] == "Tabs")
        if not tabs:
            return False
        node = tabs[action[2] % len(tabs)]
        world.note("act:lie", tab=tab.label, node=node, open=action[3])
        tab.lied = True
        tab.say({"type": "event", "node": node, "name": "show", "payload": action[3]})
    elif kind == "navigate":
        world.note("act:navigate", tab=tab.label, path=action[2])
        tab.say({"type": "navigate", "path": action[2]})
    elif kind == "request":
        world.note("act:request", tab=tab.label)
        combo = next((n for n, name in sim.handlers(tab) if name == "search"), "root/combo")
        request = tab.ask("search", combo, name="search", payload="a")
        if len(action) > 2 and action[2] == "cancel":
            tab.say({"type": "cancel", "request": request})
    elif kind == "reload":
        # The page is loaded again: its old socket goes, and the new one
        # asks for the session with nothing seen.
        if tab.session is None:
            return False
        tab.drop()
        sim.reconnect(tab, seq=0, how="reload")
    elif kind == "duplicate":
        # The tab is duplicated: a second socket for the same session while
        # the first is still there.
        if tab.session is None:
            return False
        sim.reconnect(tab, how="duplicate")
    elif kind == "stale":
        world.note("act:stale", tab=tab.label, node=action[2])
        tab.say({"type": "event", "node": action[2], "name": "click"})
    elif kind == "touch":
        # The person gets to a highlighted component, or its time runs
        # out. The tab says so and keeps the mark until the session sends
        # the list without it: what it says can be lost with its socket.
        if not tab.marks:
            return False
        mark = tab.marks[action[2] % len(tab.marks)]
        what = "touched" if action[3] else "timed out"
        world.note("act:touch", tab=tab.label, node=mark["id"], what=what)
        payload = {"n": mark["n"], "what": what}
        tab.say({"type": "event", "node": mark["id"], "name": "mark", "payload": payload})
    elif kind == "answer":
        handlers = [h for h in sim.handlers(tab) if "@ask" in h[0] and h[1] == "click"]
        wanted = "/ok" if action[2] else "/cancel"
        target = next((h for h in handlers if h[0].endswith(wanted)), None)
        if target is None:
            return False
        world.note("act:answer", tab=tab.label, node=target[0])
        tab.say({"type": "event", "node": target[0], "name": "click"})
    elif kind == "drop":
        world.note("act:drop", tab=tab.label)
        tab.drop()
    elif kind == "deafen":
        world.note("act:deafen", tab=tab.label)
        tab.hearing.clear()
    elif kind == "hear":
        world.note("act:hear", tab=tab.label)
        tab.hearing.set()
    else:
        return False
    # A breath, so what was just sent gets going before the next action lands on it.
    for _ in range(3):
        await asyncio.sleep(0)
    return True


def carried(name: str, variant: int) -> Any:
    """What an event of this name brings with it, in one of a few variants."""
    if name == "change":
        return ("typed", "", True)[variant]
    if name == "submit":
        return ({"name": "Ada", "age": 30}, {"name": "", "age": 3}, None)[variant]
    if name == "select":
        return ([0, 1], [], [99])[variant]
    if name == "row_click":
        return (3, 99, None)[variant]
    if name == "action":
        return (["open", 2], ["remove", 1], ["nothing", 99])[variant]
    if name == "sort":
        return ([["name", "asc"]], [], [["nope", "asc"]])[variant]
    if name == "filter":
        searching = {"columns": {}, "search": "row 1"}
        return (searching, {"columns": {"name": "x"}, "search": ""}, {})[variant]
    if name in ("toggle", "wave"):
        return variant
    return None


# ------------------------------------------------------------------ running one


@dataclass
class Outcome:
    seed: int | None
    actions: list[tuple[Any, ...]]
    violations: list[tuple[str, str]]
    log: list[dict[str, Any]]
    # For each action, the number of the tab it opened, if it opened one.
    made: list[int | None] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)

    @property
    def kinds(self) -> list[str]:
        return sorted({name for name, _ in self.violations})


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def run(
    seed: int | None = None,
    actions: list[tuple[Any, ...]] | None = None,
    steps: int = 50,
    avoid: frozenset[str] = frozenset(),
) -> Outcome:
    """Run one scenario: ``steps`` actions chosen from ``seed``, or the given
    actions replayed. Returns what was done and every promise it broke."""
    # Every other scenario runs on a coarse clock. A replay has the clock of
    # the original, which its actions say.
    if actions is not None:
        coarse = ("setup", "coarse clock") in actions
    else:
        coarse = seed is not None and seed % 2 == 1
    clock = Clock(COARSE if coarse else FINE)
    world = World(clock)
    rng = random.Random(seed)
    done: list[tuple[Any, ...]] = []
    made: list[int | None] = []
    logged = _Collector()
    lost: list[str] = []
    noisy = logging.getLogger("millwork")
    level, propagate = noisy.level, noisy.propagate
    noisy.addHandler(logged)
    noisy.propagate = False
    noisy.setLevel(logging.WARNING)

    session_module = importlib.import_module("millwork.session")
    work_module = importlib.import_module("millwork.work")
    Session = session_module.Session
    original_init, original_end = Session.__init__, Session.dismiss
    original_sort, original_bring_up = Session.sort, Session.bring_up
    original_failed = Session._render_failed
    original_build, original_ask = session_module.build, work_module._ask_handler

    def kept(session: Any, node: str, what: str) -> None:
        """Nothing is looked up in a part of the page that was kept from an
        earlier render: what may be called is what the page offers now."""
        part = session.kept_part(node)
        if part is not None:
            sid = world.name(session.id)
            world.broken.append(("kept part called", f"{what} for {node} of {sid}, kept in {part}"))

    def sort(self: Any, event: Any) -> Any:
        kept(self, event.node, f"the event {event.name}")
        return original_sort(self, event)

    async def ask_handler(s: Any, conn: Any, msg: Any) -> None:
        kept(s, msg.node, f"the request {msg.name}")
        await original_ask(s, conn, msg)

    def bring_up(self: Any, node: str) -> bool:
        world.counts["messages for a node in a kept part"] += 1
        built = original_bring_up(self, node)
        world.counts["... whose part could not be built"] += not built
        return bool(built)

    def build(root: Any, *args: Any, **kwargs: Any) -> Any:
        tree = original_build(root, *args, **kwargs)
        # What the page was drawn by, for the check that it was drawn by
        # what the tab said last.
        tree.drawn_by = dict(kwargs.get("showing") or {})
        world.counts["renders"] += 1
        world.counts["... with a part kept as it was"] += bool(tree.kept)
        return tree

    def render_failed(self: Any, *args: Any, **kwargs: Any) -> None:
        self.fuzz_failed = True
        original_failed(self, *args, **kwargs)

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        world.sessions.append(self)
        world.note("session:new", sid=world.name(self.id))

    def end(self: Any, *args: Any, **kwargs: Any) -> None:
        if not self.over:
            world.note("session:over", sid=world.name(self.id))
        original_end(self, *args, **kwargs)

    # How the app is set up and how the scenario ends are part of it, so a
    # replay has them as the original did.
    endings = [a[1] for a in actions or [] if a[0] == "finish"]
    setups = [a[1] for a in actions or [] if a[0] == "setup"]
    if actions is not None:
        actions = [a for a in actions if a[0] not in ("finish", "setup")]
        threads = "threads" in setups
    else:
        threads = "threads" not in avoid and rng.random() < 0.3
    if threads:
        done.append(("setup", "threads"))
        made.append(None)
    if coarse:
        done.append(("setup", "coarse clock"))
        made.append(None)
    files_root = Path(tempfile.mkdtemp(prefix="mw-fuzz-files-"))

    async def scenario() -> Sim:
        app = make_app(world, files_root, threads)
        sim = Sim(world, app)
        await sim.start()
        tabs_before = 0
        for index in range(len(actions) if actions is not None else steps):
            action = actions[index] if actions is not None else choose(rng, sim, avoid)
            try:
                limit = PATIENCE + (action[1] if action[0] == "wait" else 0.0)
                applied = await asyncio.wait_for(perform(sim, action), limit)
            except TimeoutError:
                sim.problems.append(("hung", f"{action} did not return in {PATIENCE:g} s"))
                applied = True
            if applied:
                done.append(action)
                made.append(len(sim.tabs) if len(sim.tabs) > tabs_before else None)
            tabs_before = len(sim.tabs)
        # How it ends is part of the scenario: most come to rest first, and
        # some are stopped in the middle of whatever they were doing.
        ending = endings[0] if endings else rng.choice(["rest", "rest", "empty", "empty", "abrupt"])
        done.append(("finish", ending))
        made.append(None)
        if ending != "abrupt":
            # Let everything in motion come to rest, with the tabs as they are.
            for tab in sim.tabs:
                tab.hearing.set()
            await asyncio.sleep(75.0)
            world.note("phase:settled")
            settled(sim)
        if ending == "empty":
            # Then every tab goes, and its session with it once the grace is over.
            for tab in sim.tabs:
                tab.drop()
            await asyncio.sleep(GRACE + 20.0)
            world.note("phase:emptied")
            emptied(sim)
        await sim.stop()
        # Whatever is still running a moment after that was left behind.
        await asyncio.sleep(5.0)
        world.note("phase:stopped")
        for browser in sim.browsers:
            await browser.http.aclose()
        return sim

    loop = VirtualLoop(clock)
    world.loop = loop

    def dropped(_: Any, context: dict[str, Any]) -> None:
        error = context.get("exception")
        where = ""
        trace = getattr(error, "__traceback__", None)
        while trace is not None:
            code = trace.tb_frame.f_code
            if "millwork" in code.co_filename:
                where = f"{Path(code.co_filename).name}:{trace.tb_lineno} {code.co_name}"
            trace = trace.tb_next
        lost.append(f"{context.get('message')}: {type(error).__name__}: {error} at {where or '?'}")

    loop.set_exception_handler(dropped)
    Session.__init__, Session.dismiss = init, end  # type: ignore[method-assign]
    Session.sort, Session.bring_up = sort, bring_up  # type: ignore[method-assign]
    Session._render_failed = render_failed  # type: ignore[method-assign]
    session_module.build, work_module._ask_handler = build, ask_handler
    violations: list[tuple[str, str]] = []
    try:
        with virtual_time(clock), warnings.catch_warnings(record=True) as warned:
            warnings.simplefilter("always")
            try:
                sim = loop.run_until_complete(scenario())
            except Exception as exc:
                violations.append(("crashed", f"{type(exc).__name__}: {exc}"))
                sim = None
            if sim is not None:
                violations += sim.problems
                violations += examine(world, sim, loop)
            violations += world.broken
            violations += [("lost", message) for message in lost]
            violations += [
                ("warned", str(w.message)) for w in warned if "never awaited" in str(w.message)
            ]
            violations += unexpected(logged.records)
    finally:
        Session.__init__, Session.dismiss = original_init, original_end  # type: ignore[method-assign]
        Session.sort, Session.bring_up = original_sort, original_bring_up  # type: ignore[method-assign]
        Session._render_failed = original_failed  # type: ignore[method-assign]
        session_module.build, work_module._ask_handler = original_build, original_ask
        noisy.removeHandler(logged)
        noisy.propagate = propagate
        noisy.setLevel(level)
        loop.release()
        shutil.rmtree(files_root, ignore_errors=True)
        for task in asyncio.all_tasks(loop):
            task.cancel()
        with contextlib.suppress(Exception):
            loop.run_until_complete(asyncio.sleep(0))
        loop.close()
    return Outcome(seed, done, violations, world.log, made, world.counts)


# ------------------------------------------------------------------ the oracle

# Errors the scenario provokes on purpose, by the words millwork logs them with.
EXPECTED = (
    "connect failed for",
    "close hook of",
    "handler ",
    "recheck gave no answer",
    "on_logout failed",
    "on_logout took over",
    "refresh failed",
    "session refused",
    "resume refused",
    "login denied",
    "sign-in ended by recheck",
    "event ",
    "bad message",
    " failed to render",
    "identity lookup failed",
    "messages pending",
    "ended: recheck has not answered",
    "request ",
    "task ",
    "work failed",
    "navigate ",
    "on_done failed",
    "answer for unknown request",
)


def unexpected(records: list[logging.LogRecord]) -> list[tuple[str, str]]:
    out = []
    for record in records:
        text = record.getMessage()
        if record.levelno >= logging.ERROR and not any(known in text for known in EXPECTED):
            why = ""
            if record.exc_info and record.exc_info[1] is not None:
                error = record.exc_info[1]
                why = f" ({type(error).__name__}: {error})"
            out.append(("logged", f"{record.name}: {text}{why}"))
    return out


def check_tree(session: Any) -> None:
    tree = session.tree
    seen: set[str] = set()
    todo = [tree.root]
    while todo:
        node_id = todo.pop()
        assert node_id in tree.nodes, f"dangling id {node_id}"
        assert node_id not in seen, f"{node_id} reached twice"
        seen.add(node_id)
        node = tree.nodes[node_id]
        todo += node.children
        stack = [node.props]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                if set(value) == {"$node"}:
                    todo.append(value["$node"])
                else:
                    stack += list(value.values())
            elif isinstance(value, list):
                stack += value
    assert seen == set(tree.nodes), f"leftover nodes {sorted(set(tree.nodes) - seen)[:4]}"
    assert set(tree.components) == set(tree.nodes)
    for node_id, _ in tree.handlers:
        assert node_id in tree.nodes, f"a handler for {node_id}, which is no node"
    # What the tab said about its tabs is kept for the nodes of the page, and
    # for a bounded number that were said while the session had no page.
    extra = [key for key in session._showing if key not in tree.nodes]
    assert len(extra) <= 64, f"{len(extra)} open tabs kept for nodes that are not there"


def kept_requests(session: Any) -> list[str]:
    """Requests a session still holds though nothing is working on them."""
    return [rid for rid, (child, _) in session._requests.items() if child is None or child.done()]


def stuck_chats(session: Any) -> list[str]:
    """Chats that say a reply is under way while none is."""
    return [
        key
        for key, thread in session._threads.items()
        if thread.busy and (thread.turn_task is None or thread.turn_task.done())
    ]


def settled(sim: Sim) -> None:
    """With everything at rest and every tab listening: no tab is left on a
    session that is over without having been told, and none is left connected
    to nothing. A session holds nothing for work that is no longer there."""
    for session in sim.app.sessions.values():
        sid = sim.world.name(session.id)
        if kept_requests(session):
            sim.problems.append(("request kept", f"{sid} still holds a request that is done"))
        holder = session.turn.holder
        if holder is not None and hasattr(holder, "done") and holder.done():
            name = holder.get_name()
            sim.problems.append(
                ("turn kept", f"the turn of {sid} is held by {name}, which is done")
            )
        if session.tree is not None:
            try:
                check_tree(session)
            except AssertionError as exc:
                sim.problems.append(("tree broken", f"{sid}: {exc}"))
            at_rest(sim, session, sid)
        if stuck_chats(session):
            sim.problems.append(("chat stuck", f"a chat of {sid} is busy with no reply under way"))
    for tab in sim.tabs:
        if tab.gone or tab.server_closed or tab.session is None:
            continue
        if tab.session in sim.app.sessions:
            continue
        told = "told" if tab.fatal is not None else "never told"
        sim.problems.append(
            ("stranded", f"{tab.label} is still connected to a session that is over, {told}")
        )


def above(tree: Any) -> dict[str, str]:
    """The node each node of a page sits in, as a child or in a slot."""
    up: dict[str, str] = {}
    for node_id, node in tree.nodes.items():
        for child in node.children:
            up[child] = node_id
        stack = [node.props]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                if set(value) == {"$node"}:
                    up[value["$node"]] = node_id
                else:
                    stack += list(value.values())
            elif isinstance(value, list):
                stack += value
    return up


def at_rest(sim: Sim, session: Any, sid: str) -> None:
    """A page that has come to rest, and the tab that is on it. The session
    has drawn the page by the tab of each ``Tabs`` it was last told, and no
    part of it that shows was kept from an earlier render. The tab holds
    exactly the page the session has, and the session goes by the tab of
    each ``Tabs`` that the browser is on."""
    tree = session.tree
    quiet = (
        not session.over
        and session.stage == "ready"
        and not session._wanted
        and session.turn.free
        and session._inflight == 0
        and session._render_timer is None
        and tree is not session._failure
        and not getattr(session, "fuzz_failed", False)
    )
    if quiet and session._render_due:
        # Nothing is under way and no timer is armed, so nothing is going
        # to make the drawing: the tab stays on what it was last told.
        why = f"{sid} has a drawing due and nothing that will make it"
        sim.world.broken.append(("left undrawn", why))
    if not quiet or session._render_due:
        return
    sim.world.counts["pages looked at, at rest"] += 1
    if sim.world.signal in session._following:
        # A page that follows the signal shows what is shared as it is now:
        # every fire since reached it, wherever the session was then.
        shows = next(
            (n.props["content"] for i, n in tree.nodes.items() if i.endswith("/shared")), None
        )
        if shows is not None:
            sim.world.counts["... that follow the signal"] += 1
            if shows != f"shared={sim.world.shared}":
                why = f"{sid} shows {shows} and it is shared={sim.world.shared}"
                sim.world.broken.append(("stale", why))
    tabs = {
        node_id: component
        for node_id, component in tree.components.items()
        if isinstance(component, ui.Tabs) and "value" not in component.model_fields_set
    }
    for node_id, component in tabs.items():
        was = component.shown(getattr(tree, "drawn_by", {}).get(node_id))
        now = component.shown(session._showing.get(node_id))
        if was != now:
            said = f"{node_id} of {sid} was drawn on {was!r} and the session has {now!r}"
            sim.problems.append(("tab not drawn", said))
    up = above(tree)
    for part in tree.kept:
        # Up from where the part sits: it shows when every tab on the way
        # is the open one of its tabs.
        node_id, shows = part.key.rsplit("/", 1)[0], True
        while shows and node_id in up:
            tab_of, tabs_of = tree.components[node_id], tree.components[up[node_id]]
            if isinstance(tabs_of, ui.Tabs) and isinstance(tab_of, ui.Tab):
                shows = tab_of.id == tabs_of.shown(session._showing.get(up[node_id]))
            node_id = up[node_id]
        if shows:
            sim.problems.append(("open part kept", f"{part.key} of {sid} shows and was not built"))
    ours = [
        t
        for t in sim.tabs
        if t.session == session.id and not t.gone and not t.server_closed and t.fatal is None
    ]
    if not ours:
        return
    tab = ours[-1]
    heard = tab.last_seq == session.outbox.seq and tab.hearing.is_set()
    if not heard or not tab.inbox.empty() or tab.unsent:
        # The tab has not been sent all of it, or has more to say.
        return
    sim.world.counts["... with the tab that is on them"] += 1
    page = {node_id: json.loads(node.model_dump_json()) for node_id, node in tree.nodes.items()}
    if tab.nodes != page:
        ids = set(tab.nodes) ^ set(page)
        other = sorted(ids or (i for i in page if tab.nodes[i] != page[i]))
        what = "nodes on one side only" if ids else "nodes that differ"
        sim.problems.append(("page differs", f"{tab.label} and {sid}: {what}, {other[:3]}"))
    # And exactly the highlights the session holds for this page.
    held = json.loads(json.dumps(marks.now(session._marks, session.place)[0]))
    if held:
        sim.world.counts["... that have highlights"] += 1
    if tab.marks != held:
        has = [(m["n"], m["id"]) for m in tab.marks]
        wants = [(m["n"], m["id"]) for m in held]
        sim.problems.append(("marks differ", f"{tab.label} has {has} and {sid} holds {wants}"))
    if tab.lied:
        return
    for node_id, component in tabs.items():
        if not tree.nodes[node_id].props.get("track"):
            continue
        sim.world.counts["tabs compared with the browser's"] += 1
        server, browser = component.shown(session._showing.get(node_id)), tab.on.get(node_id)
        if server != browser:
            said = f"{node_id}: {tab.label} is on {browser!r} and {sid} goes by {server!r}"
            sim.problems.append(("tabs parted", said))


def emptied(sim: Sim) -> None:
    """With every tab gone and the grace period over, nothing is left."""
    app = sim.app
    if app.sessions:
        names = sorted(sim.world.name(i) or "?" for i in app.sessions)
        sim.problems.append(("leak", f"sessions left with no tab: {', '.join(names)}"))
    unfinished = [s for s in sim.world.sessions if s.over and not s.gone.done()]
    if unfinished:
        sim.problems.append(("leak", f"{len(unfinished)} session(s) never finished ending"))
    root = app.files.root
    kept = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
    if kept or app.files.used():
        held = f"{len(kept)} file(s) and {app.files.used()} bytes"
        sim.problems.append(("files kept", f"{held} with no session left"))


def examine(world: World, sim: Sim, loop: asyncio.AbstractEventLoop) -> list[tuple[str, str]]:
    """Read the record back and list every promise it shows broken."""
    found: list[tuple[str, str]] = []
    log = world.log
    over = {e["sid"]: e["i"] for e in log if e["kind"] == "session:over"}

    # Nothing of the app's runs on a session once it is over.
    for e in log:
        starts = e["kind"] in (
            "handler:begin",
            "connect:begin",
            "request:begin",
            "tick",
            "draw",
            "part",
        )
        if starts and e["sid"] in over and e["i"] > over[e["sid"]]:
            what = e.get("name") or e.get("after") or e["kind"].split(":")[0]
            found.append(("ran after the end", f"{what} on {e['sid']} at {e['t']} s"))
        if e["kind"] == "draw" and e["early"]:
            # A page is drawn once its connect hook has returned, not before.
            found.append(("drawn early", f"{e['sid']} was drawn before its connect returned"))
        if e["kind"] == "draw" and e["halfway"]:
            found.append(("half drawn", f"{e['sid']} was drawn in the middle of a handler's turn"))
        if e["kind"] == "draw" and e["leaving"]:
            # A handler that asks for another page may have left state the
            # page it is on cannot show.
            found.append(("drawn on the way out", f"{e['sid']} drew a page it was leaving"))

    # A session keeps the user it started with, and a guarded page is only
    # ever acted on for a user its rule admits.
    first: dict[str, tuple[Any, Any]] = {}
    for e in log:
        if e["kind"] not in ("handler:begin", "connect:begin", "request:begin", "close:begin"):
            continue
        who = (e["user"], e["role"])
        if first.setdefault(e["sid"], who) != who:
            found.append(("user changed", f"{e['sid']} went from {first[e['sid']]} to {who}"))
        if e["page"] == "/admin" and e["kind"] != "close:begin" and e["role"] != "admin":
            found.append(("past the rule", f"{e['kind']} on /admin for {who} in {e['sid']}"))

    # What a guarded page shows only goes to a session of a user it admits.
    for e in log:
        if e["kind"] == "tab:got" and e.get("marked") and e["sid"] in first:
            if first[e["sid"]][1] != "admin":
                found.append(
                    ("content", f"{e['tab']} was sent the admin page as {first[e['sid']]}")
                )

    # A change in the world reaches a session within the recheck interval, give
    # or take the time a slow hook may take. Twice that when the hook cannot say.
    bound = 2 * RECHECK_EVERY + 25.0
    for e in log:
        if e["kind"] != "handler:begin" or e["user"] is None:
            continue
        said = [c for c in world.changes if c[2] == e["user"] and c[0] < e["i"]]
        if not said:
            continue
        # The stretch of the world's last word: every change at the end of
        # the list that says the same as the last one.
        last = said[-1]
        since = last[1]
        for change in reversed(said):
            if change[3:] != last[3:]:
                break
            since = change[1]
        if e["t"] - since <= bound:
            continue
        role, active = last[3], last[4]
        if not active:
            found.append(("stale", f"{e['name']} ran for {e['user']}, removed {bound:g} s before"))
        elif e["role"] != role:
            found.append(
                ("stale", f"{e['name']} ran for {e['user']} as {e['role']}, long since {role}")
            )

    # A page that was opened is closed, once. One whose connect failed is not.
    opened: Counter[str] = Counter()
    for e in log:
        if e["kind"] == "connect:end" and e["ok"]:
            opened[e["sid"]] += 1
        if e["kind"] == "close:begin":
            opened[e["sid"]] -= 1
            if opened[e["sid"]] < 0:
                found.append(("closed twice", f"{e['sid']} at {e['t']} s"))
                opened[e["sid"]] = 0
    stopped = any(e["kind"] == "phase:stopped" for e in log)
    for sid, count in opened.items():
        if count > 0 and stopped:
            found.append(("never closed", f"{sid} has {count} page(s) that were opened"))
    begun = {e["span"] for e in log if e["kind"] == "close:begin"}
    ended = {e["span"] for e in log if e["kind"] == "close:end"}
    if stopped and begun - ended:
        found.append(("close cut short", f"{len(begun - ended)} close hook(s) never finished"))

    # One handler at a time on a session, for the ones that hold their turn.
    running: dict[str, dict[str, Any]] = {}
    for e in log:
        if e["kind"] == "handler:begin" and e["plain"]:
            other = running.get(e["sid"])
            if other is not None:
                found.append(
                    ("overlap", f"{e['name']} began on {e['sid']} while {other['name']} ran")
                )
            running[e["sid"]] = e
        if e["kind"] == "handler:end" and running.get(e["sid"], {}).get("span") == e["span"]:
            del running[e["sid"]]

    # Once a session is over, nothing more of its page is sent to its tab:
    # only the word that it ended, and where to go.
    for e in log:
        if e["kind"] != "tab:got" or e["sid"] not in over or e["sent"] < over[e["sid"]]:
            continue
        page_content = e["type"] in ("mount", "patch", "stream")
        command = e["type"] == "command" and e["name"] != "leave"
        if page_content or command:
            what = e.get("name") or e["type"]
            found.append(("sent after the end", f"{e['tab']} got {what} for {e['sid']}"))

    # Where the app said a sign-in's tabs should go is where they are sent.
    # (Only when every answer in the scenario was the same one.)
    answers = {e["to"] for e in log if e["kind"] == "on_logout:end"}
    asked = [e["t"] for e in log if e["kind"] == "on_logout:begin"]
    answered = [e["t"] for e in log if e["kind"] == "on_logout:end"]
    # An answer that took longer than the hook is given does not count, and
    # one from a thread arrives all the same, long after it was given up on.
    in_time = len(asked) == len(answered) and all(
        b - a < 9.0 for a, b in zip(asked, answered, strict=True)
    )
    if asked and in_time and len(answers) == 1 and None not in answers:
        (wanted,) = answers
        for tab in sim.tabs:
            if tab.left_for is not None and "/_mw/login" in tab.left_for:
                found.append(
                    ("sent elsewhere", f"{tab.label} was sent to the login page, not to {wanted}")
                )

    # Nothing is left running once the app has stopped.
    if stopped:
        current = asyncio.current_task(loop)
        for task in asyncio.all_tasks(loop):
            if task is not current and not task.done():
                doing = getattr(task.get_coro(), "__qualname__", "")
                # The fuzzer's own: a browser still waiting on a request.
                if not doing.startswith(("Sim.", "Tab.", "Browser.")):
                    found.append(("left running", f"{doing or task.get_name()}"))
        for session in world.sessions:
            sid = world.name(session.id)
            # One that was refused before it began has nothing to close.
            # One that was refused before it was admitted never began.
            began = session.owed is not None or session.tree is not None or session.tasks
            if began and not (session.over and session.gone.done()):
                found.append(("left open", f"{sid} was never closed"))
            if session.scope.children:
                found.append(("left running", f"{len(session.scope.children)} children of {sid}"))
            if session.over and not session.turn.free:
                found.append(("left running", f"the turn of {sid} is still held"))
            for task in session.tasks:
                if not task.done:
                    found.append(("left running", f"task {task.label} of {sid}"))
    return found


# ------------------------------------------------------------------ making a failure small


# The actions that name a tab, which is always their first argument.
ON_A_TAB = {
    "click",
    "navigate",
    "request",
    "stale",
    "touch",
    "answer",
    "drop",
    "deafen",
    "hear",
    "reconnect",
    "chat",
    "upload",
    "fetch",
    "reload",
    "duplicate",
}


def leave_out(outcome: Outcome, start: int, count: int) -> list[tuple[Any, ...]]:
    """A scenario's actions without a run of them. Tabs are numbered in the
    order they open, so with an opening left out the later ones move up, and
    whatever was done to a tab that is no longer opened goes too."""
    removed = {n for n in outcome.made[start : start + count] if n is not None}
    kept = []
    for index, action in enumerate(outcome.actions):
        if start <= index < start + count:
            continue
        if action[0] in ON_A_TAB:
            tab = action[1]
            if tab in removed:
                continue
            action = (action[0], tab - sum(1 for n in removed if n < tab), *action[2:])
        kept.append(action)
    return kept


def shrink(outcome: Outcome, kind: str, budget: int = 120) -> Outcome:
    """The fewest of a scenario's actions that still break the same promise,
    found by leaving out ever smaller runs of them."""
    best = outcome
    chunk = max(1, len(best.actions) // 2)
    while chunk >= 1 and budget > 0:
        index, shrunk = 0, False
        while index < len(best.actions) and budget > 0:
            trial = leave_out(best, index, chunk)
            budget -= 1
            result = run(actions=trial)
            if kind in result.kinds and len(result.actions) < len(best.actions):
                best, shrunk = result, True
            else:
                index += chunk
        if not shrunk:
            chunk //= 2
    return best


def describe(outcome: Outcome, verbose: bool = False) -> str:
    lines = [f"seed {outcome.seed}: {len(outcome.actions)} actions"]
    lines += [f"  {name}: {detail}" for name, detail in outcome.violations]
    lines.append("  actions:")
    lines += [f"    {action}" for action in outcome.actions]
    if verbose:
        lines.append("  record:")
        for e in outcome.log:
            facts = " ".join(f"{k}={v}" for k, v in e.items() if k not in ("i", "t", "kind"))
            lines.append(f"    {e['t']:>9.3f} {e['kind']:<16} {facts}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seeds", type=int, default=200, help="how many seeds to run, from 0")
    parser.add_argument("--seed", type=int, default=None, help="run this one seed and show it")
    parser.add_argument("--steps", type=int, default=50, help="actions per scenario")
    parser.add_argument("--verbose", action="store_true", help="show the whole record")
    parser.add_argument("--shrink", action="store_true", help="make each failure small")
    parser.add_argument("--start", type=int, default=0, help="the first seed of a run of many")
    parser.add_argument(
        "--avoid", default="", help="kinds of action or knobs to leave out, comma separated"
    )
    args = parser.parse_args(argv)
    avoid = frozenset(filter(None, args.avoid.split(",")))
    if args.seed is not None:
        outcome = run(seed=args.seed, steps=args.steps, avoid=avoid)
        if args.shrink and outcome.violations:
            outcome = shrink(outcome, outcome.kinds[0])
        print(describe(outcome, args.verbose))
        return 1 if outcome.violations else 0
    tally: Counter[str] = Counter()
    seen: Counter[str] = Counter()
    example: dict[str, int] = {}
    failed = 0
    for seed in range(args.start, args.start + args.seeds):
        outcome = run(seed=seed, steps=args.steps, avoid=avoid)
        seen += outcome.counts
        if outcome.violations:
            failed += 1
        for kind in outcome.kinds:
            tally[kind] += 1
            example.setdefault(kind, seed)
    print(f"{args.seeds} scenarios of {args.steps} actions, {failed} broke a promise")
    for what, count in sorted(seen.items()):
        print(f"  ({what}: {count})")
    for kind, count in tally.most_common():
        print(f"  {kind:<22} {count:>5} scenarios, first at seed {example[kind]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
