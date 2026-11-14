"""The app the load test runs against: a counter, a field, a table and a
task, on a page that says which replica drew it. ``MW_REPLICA`` names the
replica and ``MW_SECRET`` is the secret the replicas share.
"""

from __future__ import annotations

import asyncio
import gc
import os
import time

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

import millwork as mw
from millwork import ui

REPLICA = os.environ.get("MW_REPLICA", "one")
ROWS = [
    {"id": i, "customer": f"Customer {i}", "amount": i * 13 % 997, "paid": i % 3 == 0}
    for i in range(200)
]


class State(BaseModel):
    n: int = 0
    note: str = ""
    job: mw.Task | None = None


app = mw.App(
    "Load test",
    state=State,
    secret=os.environ.get("MW_SECRET"),
    max_sessions=1_000_000,
    max_sessions_per_client=1_000_000,
)

# How late the loop runs its timers, the worst of the last second: what a
# click waits before anything is done about it.
lag = {"now": 0.0, "worst": 0.0}


@app.on_startup
async def watch_the_loop() -> None:
    async def watch() -> None:
        worst, since = 0.0, time.monotonic()
        while True:
            before = time.monotonic()
            await asyncio.sleep(0.05)
            late = time.monotonic() - before - 0.05
            worst = max(worst, late)
            if time.monotonic() - since >= 1.0:
                lag["now"], lag["worst"] = worst, max(lag["worst"], worst)
                worst, since = 0.0, time.monotonic()

    app.state_watch = asyncio.get_running_loop().create_task(watch())  # type: ignore[attr-defined]
    if os.environ.get("MW_GC_FREEZE"):
        gc.collect()
        gc.freeze()


# The collector's passes since the last look: how many of each generation,
# and the longest. A pass stops the loop for as long as it takes.
passes = {"began": 0.0, "count": [0, 0, 0], "longest": [0.0, 0.0, 0.0]}


def timed(phase: str, info: dict[str, int]) -> None:
    if phase == "start":
        passes["began"] = time.perf_counter()
    else:
        took, generation = time.perf_counter() - passes["began"], info["generation"]
        passes["count"][generation] += 1
        passes["longest"][generation] = max(passes["longest"][generation], took)


gc.callbacks.append(timed)
# Two things to try on the collector: MW_GC_THRESHOLD is the size of the
# youngest generation, and MW_GC_FREEZE sets aside what startup made.
if os.environ.get("MW_GC_THRESHOLD"):
    gc.set_threshold(int(os.environ["MW_GC_THRESHOLD"]), *gc.get_threshold()[1:])


def bump(s: mw.Session[State], _: object) -> None:
    s.state.n += 1


def note(s: mw.Session[State], value: str) -> None:
    s.state.note = value


async def work(seconds: float) -> str:
    p = mw.progress()
    steps = int(seconds * 4)
    for i in range(steps):
        p.set((i + 1) / steps, f"step {i + 1} of {steps}")
        await asyncio.sleep(0.25)
    return "done"


def start(s: mw.Session[State], _: object) -> None:
    s.state.job = s.task(work, 60.0, label="Working")


@app.page("/")
def home(s: mw.Session[State]) -> ui.Component:
    job = s.state.job
    return ui.Page(
        ui.Text(f"replica={REPLICA}", key="replica"),
        ui.Text(f"n={s.state.n}", key="mark"),
        ui.Text(f"note={s.state.note}", key="noted"),
        ui.Text(f"job={job.status if job else 'none'}", key="job"),
        ui.Button("bump", key="bump", on_click=bump),
        ui.Button("start", key="start", on_click=start),
        ui.Input(key="note", value=s.state.note, on_change=note),
        ui.Progress(task=job, key="progress") if job else None,
        ui.Table(rows=ROWS, key="orders", page_size=25),
    )


async def stats(request: Request) -> JSONResponse:
    sessions = list(app.sessions.values())
    with open(f"/proc/{os.getpid()}/statm") as fh:
        rss = int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    worst, lag["worst"] = lag["worst"], 0.0
    full = None
    if "collect" in request.query_params:
        began = time.perf_counter()
        gc.collect()
        full = round((time.perf_counter() - began) * 1e3, 1)
    found = JSONResponse(
        {
            "replica": REPLICA,
            "sessions": len(sessions),
            "with_tab": sum(1 for s in sessions if s.has_tab),
            "rss_mb": round(rss, 1),
            "cpu_s": round(time.process_time(), 2),
            "lag_ms": round(lag["now"] * 1e3, 1),
            "worst_lag_ms": round(worst * 1e3, 1),
            "gc_passes": list(passes["count"]),
            "gc_longest_ms": [round(t * 1e3, 1) for t in passes["longest"]],
            "gc_full_ms": full,
            "gc_threshold": list(gc.get_threshold()),
            "python": ".".join(map(str, __import__("sys").version_info[:3])),
            "gc_objects": len(gc.get_objects()) if "objects" in request.query_params else None,
        }
    )
    passes["count"], passes["longest"] = [0, 0, 0], [0.0, 0.0, 0.0]
    return found


app.route("/stats", stats, public=True)
