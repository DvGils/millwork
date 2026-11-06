"""A fuzzer for the life of a session.

It drives a real millwork app through its ASGI surface, the way browsers do:
page loads and sign-ins over HTTP, and each tab over a websocket that speaks
the tab's protocol. A scenario is a list of small actions (a click, a dropped
connection, a role taken away, time passing) chosen at random from a seed.
Time is virtual, so a five-minute grace period or a ten-second hook costs
nothing to wait for, and a scenario runs the same way every time.

What makes it a test is the oracle. The app writes down what its own code did
(which handler ran, for whom, when a hook started and finished) and each tab
writes down what it was sent. From that record the checks in ``examine`` ask
whether promises the manual makes were kept: nothing runs on a session that
is over, a page is closed exactly once, a tab is never left on a session it
was not told has ended, nothing is left running at the end.

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
import sys
import tempfile
import types
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

import millwork as mw
from millwork import auth, ui

ADMIN_MARK = "ADMIN-ONLY-CONTENT"
RECHECK_EVERY = 30.0
GRACE = 60.0
SIGN_IN_LASTS = 900.0
EPOCH = 1_900_000_000.0
# How long anything the fuzzer waits for may take, in virtual seconds, before
# it counts as hung.
PATIENCE = 180.0


# ------------------------------------------------------------------ virtual time


class Clock:
    def __init__(self) -> None:
        self.now = 0.0


class _Selector:
    """A selector that never sleeps: when nothing is ready it moves the clock
    to the next timer instead. Work in a thread is real, so while any is in
    flight the clock stands still and the selector waits for it."""

    def __init__(self, clock: Clock) -> None:
        self._real = selectors.DefaultSelector()
        self._clock = clock
        self.busy = 0

    def select(self, timeout: float | None = None) -> Any:
        ready = self._real.select(0)
        if ready:
            return ready
        if self.busy:
            return self._real.select(0.002)
        if timeout is None:
            raise RuntimeError("the loop has nothing left to wait for")
        if timeout > 0:
            self._clock.now += timeout
        return []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class VirtualLoop(asyncio.SelectorEventLoop):
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._virtual = _Selector(clock)
        super().__init__(selector=self._virtual)  # type: ignore[arg-type]

    def time(self) -> float:
        return self._clock.now

    def run_in_executor(self, executor: Any, func: Any, *args: Any) -> Any:
        self._virtual.busy += 1
        future = super().run_in_executor(executor, func, *args)

        def done(_: Any) -> None:
            self._virtual.busy -= 1

        future.add_done_callback(done)
        return future


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
            "close_delay": 0.0,
            "close_does": None,
            "handler_delay": 0.1,
        }
    )
    log: list[dict[str, Any]] = field(default_factory=list)
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

    def change(self, who: str, **what: Any) -> None:
        self.people[who].update(what)
        person = self.people[who]
        entry = self.note("world", who=who, role=person["role"], active=person["active"])
        self.changes.append((entry["i"], entry["t"], who, person["role"], person["active"]))


class State(BaseModel):
    n: int = 0


def make_bundle() -> Path:
    """A bundle directory with just enough in it for the shell to be served."""
    root = Path(tempfile.mkdtemp(prefix="mw-fuzz-"))
    (root / ".vite").mkdir()
    (root / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "main-abc.js", "isEntry": True, "css": []}})
    )
    return root


BUNDLE = make_bundle()


def make_app(world: World) -> mw.App:
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

    app = mw.App(
        "fuzz",
        state=State,
        public=None,
        bundle_dir=BUNDLE,
        secret="fuzz-fuzz-fuzz-fuzz-fuzz-fuzz-fuzz-fuzz",
        session_grace=GRACE,
        max_sessions=6,
        max_sessions_per_client=3,
        auth=auth.Auth(
            [auth.Password(verify)],
            on_login=admit,
            recheck=recheck,
            recheck_every=dt.timedelta(seconds=RECHECK_EVERY),
            on_logout=on_logout,
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

    @handler("bump")
    async def bump(s: mw.Session[State], _: Any) -> None:
        s.state.n += 1

    @handler("slow")
    async def slow(s: mw.Session[State], _: Any) -> None:
        await asyncio.sleep(knobs["handler_delay"])
        s.state.n += 1

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

    @handler("task")
    async def start_task(s: mw.Session[State], _: Any) -> None:
        s.task(work, s, label="work", on_done=finished)

    @handler("undo")
    async def undo(s: mw.Session[State], _: Any) -> None:
        s.state.n -= 1

    @handler("toast")
    async def toast(s: mw.Session[State], _: Any) -> None:
        s.toast("Changed.", action=("Undo", undo))

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

    def body(s: mw.Session[State], mark: str) -> ui.Component:
        return ui.Page(
            ui.Text(f"{mark} n={s.state.n}", key="mark"),
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
            ui.Combobox(key="combo", on_search=search),
        )

    def is_admin(user: auth.User) -> bool:
        return user.claims.get("role") == "admin"

    async def connect(s: mw.Session[State], **params: Any) -> None:
        span = world.begin("connect", s)
        ok = False
        try:
            await asyncio.sleep(knobs["connect_delay"])
            if knobs["connect_fails"] == "forbidden":
                raise mw.Forbidden("Not today.")
            if knobs["connect_fails"] == "boom":
                raise RuntimeError("connect broke")
            ok = True
        finally:
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

    @property
    def label(self) -> str:
        return f"T{self.number}"

    def open(self, resume_from: Tab | None = None) -> None:
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
        hello: dict[str, Any] = {"type": "hello", "path": self.path, "protocol": 4}
        if resume_from is not None and resume_from.session is not None:
            hello.update(
                session=resume_from.session, resume=resume_from.resume, seq=resume_from.last_seq
            )
        self.inbox.put_nowait({"type": "websocket.connect"})
        self.say(hello)
        self.task = asyncio.get_running_loop().create_task(
            self.sim.asgi(scope, self._receive, self._send), name=f"tab {self.number}"
        )

    def say(self, message: dict[str, Any]) -> None:
        text = json.dumps({"seq": self.sent, "msg": message})
        self.sent += 1
        self.inbox.put_nowait({"type": "websocket.receive", "text": text})

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
        if kind != "websocket.send" or event.get("text") is None:
            return
        envelope = json.loads(event["text"])
        seq, msg = envelope["seq"], envelope["msg"]
        if seq > self.last_seq:
            self.last_seq = seq
        kind = msg["type"]
        fact: dict[str, Any] = {"tab": self.label, "type": kind, "seq": seq, "sent": sent}
        if kind == "session":
            self.session, self.resume = msg["id"], msg["resume"]
            fact["sid"] = self.sim.world.name(msg["id"])
        elif kind == "mount":
            fact["marked"] = ADMIN_MARK in event["text"]
        elif kind == "patch":
            fact["marked"] = ADMIN_MARK in event["text"]
        elif kind == "command":
            fact["name"] = msg["name"]
            if msg["name"] == "navigate":
                self.path = msg["args"]["path"]
            if msg["name"] == "leave":
                self.left_for = msg["args"]["to"]
                fact["to"] = self.left_for
            if msg["name"] == "logout":
                # The tab signs out for its browser and goes, as a real one does.
                self.sim.background(self.sim.sign_out(self.browser.number - 1))
                self.leaving = True
        elif kind == "error":
            fact["fatal"] = msg["fatal"]
            fact["message"] = msg["message"]
            if msg["fatal"]:
                self.fatal = msg["message"]
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

    def reconnect(self, old: Tab) -> Tab:
        """The same tab on a new connection, asking for its session back."""
        tab = Tab(self, len(self.tabs) + 1, old.browser, old.path)
        self.tabs.append(tab)
        self.world.note("act:reconnect", tab=tab.label, was=old.label)
        tab.open(resume_from=old)
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

PATHS = ("/", "/admin", "/open", "/admin?x=1", "/nowhere")
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
    "close_delay": (0.0, 0.0, 0.3, 3.0),
    "close_does": (None, None, None, "end", "boom"),
    "handler_delay": (0.1, 0.5, 3.0),
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
        kinds += ["click"] * 10 + ["navigate"] * 2 + ["drop"] * 2 + ["deafen", "hear"]
        kinds += ["request", "stale", "answer"]
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
    tab = rng.choice(live).number if live else 0
    if kind == "stale" and rng.random() < 0.5:
        open_still = [t.number for t in sim.tabs if not t.gone and not t.server_closed]
        tab = rng.choice(open_still) if open_still else tab
    if kind == "click":
        return ("click", tab, rng.randrange(40))
    if kind == "navigate":
        return ("navigate", tab, rng.choice(PATHS))
    if kind == "drop":
        return ("drop", tab)
    if kind == "deafen":
        return ("deafen", tab)
    if kind == "hear":
        return ("hear", tab)
    if kind == "request":
        return ("request", tab)
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
        handlers = [h for h in sim.handlers(tab) if h[1] in ("click", "action")]
        if not handlers:
            return False
        node, name = handlers[action[2] % len(handlers)]
        world.note("act:click", tab=tab.label, node=node)
        tab.say({"type": "event", "node": node, "name": name})
    elif kind == "navigate":
        world.note("act:navigate", tab=tab.label, path=action[2])
        tab.say({"type": "navigate", "path": action[2]})
    elif kind == "request":
        world.note("act:request", tab=tab.label)
        request = {"type": "request", "request": f"r{tab.sent}", "node": "root/combo"}
        tab.say({**request, "name": "search", "payload": "a"})
    elif kind == "stale":
        world.note("act:stale", tab=tab.label, node=action[2])
        tab.say({"type": "event", "node": action[2], "name": "click"})
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


# ------------------------------------------------------------------ running one


@dataclass
class Outcome:
    seed: int | None
    actions: list[tuple[Any, ...]]
    violations: list[tuple[str, str]]
    log: list[dict[str, Any]]
    # For each action, the number of the tab it opened, if it opened one.
    made: list[int | None] = field(default_factory=list)

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
    clock = Clock()
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

    Session = importlib.import_module("millwork.session").Session
    original_init, original_shut = Session.__init__, Session._shut

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        world.sessions.append(self)
        world.note("session:new", sid=world.name(self.id))

    def shut(self: Any) -> None:
        if not self.closed:
            world.note("session:over", sid=world.name(self.id))
        original_shut(self)

    # A replayed scenario ends the way the original did.
    endings = [a[1] for a in actions or [] if a[0] == "finish"]
    if actions is not None:
        actions = [a for a in actions if a[0] != "finish"]

    async def scenario() -> Sim:
        app = make_app(world)
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
    Session.__init__, Session._shut = init, shut  # type: ignore[method-assign]
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
            violations += [("lost", message) for message in lost]
            violations += [
                ("warned", str(w.message)) for w in warned if "never awaited" in str(w.message)
            ]
            violations += unexpected(logged.records)
    finally:
        Session.__init__, Session._shut = original_init, original_shut  # type: ignore[method-assign]
        noisy.removeHandler(logged)
        noisy.propagate = propagate
        noisy.setLevel(level)
        for task in asyncio.all_tasks(loop):
            task.cancel()
        with contextlib.suppress(Exception):
            loop.run_until_complete(asyncio.sleep(0))
        loop.close()
    return Outcome(seed, done, violations, world.log, made)


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
    "page / failed to render",
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


def settled(sim: Sim) -> None:
    """With everything at rest and every tab listening: no tab is left on a
    session that is over without having been told, and none is left connected
    to nothing."""
    for tab in sim.tabs:
        if tab.gone or tab.server_closed or tab.session is None:
            continue
        if tab.session in sim.app.sessions:
            continue
        told = "told" if tab.fatal is not None else "never told"
        sim.problems.append(
            ("stranded", f"{tab.label} is still connected to a session that is over, {told}")
        )


def emptied(sim: Sim) -> None:
    """With every tab gone and the grace period over, nothing is left."""
    app = sim.app
    if app.sessions:
        names = sorted(sim.world.name(i) or "?" for i in app.sessions)
        sim.problems.append(("leak", f"sessions left with no tab: {', '.join(names)}"))
    if app.ending:
        sim.problems.append(("leak", f"{len(app.ending)} session(s) never finished ending"))
    if app._ending:
        sim.problems.append(("leak", f"{len(app._ending)} sign-in(s) never finished ending"))


def examine(world: World, sim: Sim, loop: asyncio.AbstractEventLoop) -> list[tuple[str, str]]:
    """Read the record back and list every promise it shows broken."""
    found: list[tuple[str, str]] = []
    log = world.log
    over = {e["sid"]: e["i"] for e in log if e["kind"] == "session:over"}

    # Nothing of the app's runs on a session once it is over.
    for e in log:
        starts = e["kind"] in ("handler:begin", "connect:begin", "request:begin", "tick")
        if starts and e["sid"] in over and e["i"] > over[e["sid"]]:
            what = e.get("name") or e["kind"].split(":")[0]
            found.append(("ran after the end", f"{what} on {e['sid']} at {e['t']} s"))

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
    asked = sum(1 for e in log if e["kind"] == "on_logout:begin")
    answered = sum(1 for e in log if e["kind"] == "on_logout:end")
    if asked and asked == answered and len(answers) == 1 and None not in answers:
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
            began = session._page_open or session.tree is not None or session.tasks
            if not session.closed and began:
                found.append(("left open", f"{sid} was never closed"))
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
    "answer",
    "drop",
    "deafen",
    "hear",
    "reconnect",
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
    example: dict[str, int] = {}
    failed = 0
    for seed in range(args.start, args.start + args.seeds):
        outcome = run(seed=seed, steps=args.steps, avoid=avoid)
        if outcome.violations:
            failed += 1
        for kind in outcome.kinds:
            tally[kind] += 1
            example.setdefault(kind, seed)
    print(f"{args.seeds} scenarios of {args.steps} actions, {failed} broke a promise")
    for kind, count in tally.most_common():
        print(f"  {kind:<22} {count:>5} scenarios, first at seed {example[kind]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
