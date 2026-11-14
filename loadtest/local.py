"""Three replicas on this machine behind a router without sticky routing,
and the scenarios played against them. Nothing leaves the machine.

    uv run python loadtest/local.py spread blip stop load
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tabs import Tab, open_many, percentiles, spread  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FRONT = 9100
REPLICAS = {"one": 9101, "two": 9102, "three": 9103}
URL = f"ws://127.0.0.1:{FRONT}"


def stats(ask: str = "") -> dict[str, dict[str, float]]:
    found = {}
    for name, port in REPLICAS.items():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/stats{ask}", timeout=20) as r:
                found[name] = json.load(r)
        except OSError:
            found[name] = {}
    return found


def say_stats(title: str) -> None:
    print(f"  {title}")
    for name, s in stats().items():
        if not s:
            print(f"    {name:6} gone")
            continue
        print(
            f"    {name:6} {s['sessions']:5} sessions, {s['with_tab']:5} with a tab,"
            f" {s['rss_mb']:7.1f} MB, loop late {s['worst_lag_ms']:6.1f} ms at worst,"
            f" collector passes {s['gc_passes']} longest {s['gc_longest_ms']} ms"
        )


class Rig:
    def __init__(self) -> None:
        self.logs = Path(tempfile.mkdtemp(prefix="logs-", dir=HERE))
        self.procs: dict[str, subprocess.Popen[bytes]] = {}

    def start(self, name: str) -> None:
        env = dict(os.environ, MW_REPLICA=name, MW_SECRET="one-secret-for-all-replicas-0123456789")
        log = open(self.logs / f"{name}.log", "ab")
        self.procs[name] = subprocess.Popen(
            [os.environ.get("MW_MILLWORK", str(REPO / ".venv/bin/millwork")), "run", str(HERE / "app.py"), "--port", str(REPLICAS[name])],
            cwd=REPO, env=env, stdout=log, stderr=log,
        )  # fmt: skip

    def up(self, pins: bool = False) -> None:
        for name in REPLICAS:
            self.start(name)
        self.procs["front"] = subprocess.Popen(
            [
                sys.executable,
                str(HERE / "front.py"),
                *(["--cookie"] if pins else []),
                str(FRONT),
                *map(str, REPLICAS.values()),
            ]
        )
        deadline = time.monotonic() + 30
        for port in REPLICAS.values():
            while True:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/_mw/health", timeout=1).read()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise SystemExit(f"no replica on {port}; see {self.logs}") from None
                    time.sleep(0.2)
        time.sleep(0.3)

    def down(self) -> None:
        for proc in self.procs.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in self.procs.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


async def close_all(tabs: list[Tab]) -> None:
    await asyncio.gather(*(t.drop() for t in tabs))
    await asyncio.sleep(0.5)


async def scenario_spread(rig: Rig) -> None:
    print("\nSPREAD: 600 tabs through a router that keeps nothing")
    tabs = await open_many(URL, 600)
    print(f"  tabs by replica: {spread(tabs)}")
    say_stats("replicas")
    await close_all(tabs)


async def scenario_blip(rig: Rig) -> None:
    print("\nBLIP: 300 tabs with a count of 3, a note and a running task lose their connection")
    tabs = await open_many(URL, 300)

    async def use(tab: Tab) -> None:
        for _ in range(3):
            await tab.click()
        await tab.type("note", "kept")
        await tab.press("start")
        await tab.until(lambda: tab.text("noted") == "note=kept" and tab.text("job") != "job=none")

    await asyncio.gather(*(use(t) for t in tabs))
    print(f"  the task says {dict(collections.Counter(t.text('job') for t in tabs))}")
    say_stats("before")
    await asyncio.gather(*(t.drop() for t in tabs))
    back = await asyncio.gather(*(t.reconnect() for t in tabs))
    resumed = [t for t, (same, _) in zip(tabs, back, strict=True) if same]
    fresh = [t for t, (same, _) in zip(tabs, back, strict=True) if not same]
    print(f"  got their session back: {len(resumed)} of {len(tabs)}")
    print(f"    those still show n=3, the note and the task: "
          f"{sum(1 for t in resumed if t.n == 3 and t.text('noted') == 'note=kept' and t.text('job') != 'job=none')}")  # fmt: skip
    print(f"  started over: {len(fresh)}")
    print(f"    of those, n is {collections.Counter(t.n for t in fresh).most_common(3)},"
          f" job is {collections.Counter(t.text('job') for t in fresh).most_common(3)}")  # fmt: skip
    print(f"  without a page: {percentiles([gap for _, gap in back])}")
    say_stats("after: sessions nobody is looking at wait out their grace, tasks running")
    await close_all(tabs)


async def scenario_stop(rig: Rig) -> None:
    print("\nSTOP: 900 tabs, then replica two gets SIGINT")
    tabs = await open_many(URL, 900)
    print(f"  tabs by replica: {spread(tabs)}")
    for tab in tabs:
        await tab.click()
    on_two = [t for t in tabs if t.replica == "two"]
    others = [t for t in tabs if t.replica != "two"]
    probes = random.sample(others, 30)
    latencies: list[float] = []
    stop_probing = asyncio.Event()

    async def probe(tab: Tab) -> None:
        while not stop_probing.is_set():
            latencies.append(await tab.click())
            await asyncio.sleep(0.05)

    probing = [asyncio.ensure_future(probe(t)) for t in probes]
    await asyncio.sleep(1.0)
    calm, latencies[:] = list(latencies), []
    began = time.monotonic()
    rig.procs["two"].send_signal(signal.SIGINT)
    await asyncio.gather(*(t.closed.wait() for t in on_two))
    told = time.monotonic() - began
    back = await asyncio.gather(*(t.reconnect() for t in on_two))
    rig.procs["two"].wait(timeout=30)
    exited = time.monotonic() - began
    await asyncio.sleep(0.5)
    stop_probing.set()
    await asyncio.gather(*probing)
    print(f"  the {len(on_two)} tabs on two heard of it within {told * 1e3:.0f} ms,"
          f" close codes {dict(collections.Counter(t.close_code for t in on_two))}")  # fmt: skip
    print(f"  the process was gone after {exited:.1f} s")
    print(f"  got their session back: {sum(1 for same, _ in back if same)}, started over:"
          f" {sum(1 for same, _ in back if not same)}, now on {spread(on_two)}")  # fmt: skip
    print(f"  without a page: {percentiles([gap for _, gap in back])}")
    print(f"  a click on the other replicas, before:  {percentiles(calm)}")
    print(f"  a click on the other replicas, meanwhile: {percentiles(latencies)}")
    say_stats("after")
    await close_all(tabs)
    rig.start("two")
    await asyncio.sleep(3)


async def scenario_load(rig: Rig) -> None:
    print("\nLOAD: tabs that sit, and clicks at a rate, on three replicas")
    tabs: list[Tab] = []
    for count, rate in ((1500, 300), (3000, 600), (3000, 1500), (6000, 1500), (6000, 2400)):
        if len(tabs) < count:
            tabs += await open_many(URL, count - len(tabs), a_second=400)
        stats()  # forget the worst of the ramp
        latencies: list[float] = []
        late = 0.0

        async def one(tab: Tab) -> None:
            latencies.append(await tab.click())

        clicks = []
        began = time.monotonic()
        seconds = 10
        for i in range(rate * seconds):
            due = began + i / rate
            now = time.monotonic()
            if due > now:
                await asyncio.sleep(due - now)
            else:
                late = max(late, now - due)
            clicks.append(asyncio.ensure_future(one(random.choice(tabs))))
        await asyncio.gather(*clicks, return_exceptions=True)
        print(f"  {count} tabs, {rate} clicks a second: {percentiles(latencies)}"
              f"   (the generator itself ran {late * 1e3:.0f} ms late at worst)")  # fmt: skip
        say_stats("replicas")
    await close_all(tabs)


async def scenario_single(rig: Rig) -> None:
    print("\nSINGLE: one tab on idle replicas, a click every 300 ms")
    tab = Tab(URL, 0)
    await tab.open()
    latencies = []
    for _ in range(20):
        latencies.append(await tab.click())
        await asyncio.sleep(0.3)
    print(f"  a click: {percentiles(latencies)}")
    await close_all([tab])


async def scenario_stall(rig: Rig) -> None:
    print("\nSTALL: 6000 tabs, 300 clicks a second for 20 seconds")
    tabs = await open_many(URL, 6000, a_second=400)
    await asyncio.sleep(2)
    stats()
    latencies: list[float] = []

    async def one(tab: Tab) -> None:
        latencies.append(await tab.click())

    clicks = []
    for _ in range(300 * 20):
        clicks.append(asyncio.ensure_future(one(random.choice(tabs))))
        await asyncio.sleep(1 / 300)
    await asyncio.gather(*clicks, return_exceptions=True)
    print(f"  a click: {percentiles(latencies)}")
    one = stats()["one"]
    print(
        f"  Python {one['python']}, thresholds {one['gc_threshold']}: loop late"
        f" {one['worst_lag_ms']} ms at worst, collector passes {one['gc_passes']}"
        f" longest {one['gc_longest_ms']} ms"
    )
    await close_all(tabs)


async def scenario_weight(rig: Rig) -> None:
    print("\nWEIGHT: what the collector has to walk, without tabs and with 6000")
    empty = stats("?objects&collect")
    tabs = await open_many(URL, 6000, a_second=400)
    for tab in random.sample(tabs, 600):
        await tab.click()
    await asyncio.sleep(1)
    full = stats("?objects&collect")
    for name in REPLICAS:
        e, f = empty[name], full[name]
        each = (f["gc_objects"] - e["gc_objects"]) / max(1, f["sessions"])
        print(
            f"    {name:6} Python {f['python']}: {e['gc_objects']:,} objects and a full pass of"
            f" {e['gc_full_ms']} ms without tabs, {f['gc_objects']:,} and {f['gc_full_ms']} ms"
            f" with {f['sessions']} sessions: {each:,.0f} objects a session"
        )
    await close_all(tabs)


async def scenario_pinned(rig: Rig) -> None:
    print("\nPINNED: the router pins a browser to a replica by cookie, as a load balancer does")
    tabs = await open_many(URL, 300, cookies=True)
    print(f"  tabs by replica: {spread(tabs)}")

    async def use(tab: Tab) -> None:
        for _ in range(3):
            await tab.click()
        await tab.type("note", "kept")
        await tab.press("start")
        await tab.until(lambda: tab.text("noted") == "note=kept" and tab.text("job") != "job=none")

    await asyncio.gather(*(use(t) for t in tabs))
    was_on = {t.number: t.replica for t in tabs}
    for round_ in (1, 2):
        await asyncio.gather(*(t.drop() for t in tabs))
        back = await asyncio.gather(*(t.reconnect() for t in tabs))
        whole = sum(
            1
            for t in tabs
            if t.n == 3 and t.text("noted") == "note=kept" and t.text("job") != "job=none"
        )
        print(
            f"  connection lost, time {round_}: {sum(1 for same, _ in back if same)} of {len(tabs)}"
            f" got their session back, {whole} still show the count, the note and the task,"
            f" {sum(1 for t in tabs if t.replica == was_on[t.number])} on the replica they were on"
        )
    say_stats("replicas")

    print("  then replica two gets SIGINT")
    on_two = [t for t in tabs if t.replica == "two"]
    rig.procs["two"].send_signal(signal.SIGINT)
    await asyncio.gather(*(t.closed.wait() for t in on_two))
    back = await asyncio.gather(*(t.reconnect() for t in on_two))
    print(
        f"  its {len(on_two)} tabs: {sum(1 for same, _ in back if not same)} started over,"
        f" now on {spread(on_two)}; without a page: {percentiles([gap for _, gap in back])}"
    )
    await asyncio.gather(*(t.drop() for t in on_two))
    back = await asyncio.gather(*(t.reconnect() for t in on_two))
    print(
        f"  they lose the connection once more: {sum(1 for same, _ in back if same)} of"
        f" {len(on_two)} got the new session back"
    )
    await close_all(tabs)


SCENARIOS = {
    "pinned": scenario_pinned,
    "weight": scenario_weight,
    "stall": scenario_stall,
    "single": scenario_single,
    "spread": scenario_spread,
    "blip": scenario_blip,
    "stop": scenario_stop,
    "load": scenario_load,
}


async def main(names: list[str]) -> None:
    rig = Rig()
    rig.up(pins="pinned" in names)
    try:
        for name in names:
            await SCENARIOS[name](rig)
    finally:
        rig.down()
        print(f"\nreplica logs: {rig.logs}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(SCENARIOS)))
