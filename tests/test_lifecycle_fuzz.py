"""Random lives of sessions, checked against what the manual promises.

``lifecycle_fuzz`` drives the app the way browsers do, with time made
virtual, and reads back what happened. This runs a few hundred of its
scenarios on every test run. It fails when a promise that holds today is
broken, and when one of the known failures stops failing, so the list below
only ever gets shorter.
"""

import re
from collections import Counter

import lifecycle_fuzz as fuzz

# Promises the session's life does not keep yet. Each was found by the fuzzer
# and reduced to a few actions, and each is known by the kind of promise and
# by what the record says about it, so that a different way of breaking the
# same promise still fails this test.
KNOWN = {
    # A tab that was not reading when its session ended is never told, and
    # stays connected to nothing. So does one whose page was loaded again
    # just as its session ended.
    "stranded": r", (never )?told$",
    # A connect hook that raises for a tab that has already gone leaves its
    # session behind for good.
    "leak": r"^sessions left with no tab",
    # Something reaches a tab after its session ended: the closing chunks of
    # a chat reply that was under way, a toast or a navigation asked for just
    # before, or what is replayed to a tab that was reconnecting.
    "sent after the end": r" got \w+ for ",
    # The app telling every session something at once waits on a tab that is
    # not reading, and on it everyone after.
    "hung": r"^\('push',\) did not return",
    # A task started after a delay goes on once it has started, whatever
    # becomes of its session. A handler that waits on a task when its session
    # ends is told the task was cancelled, and goes on.
    "ran after the end": r"^(tick|its task) on ",
    # A handler waiting on a question when its session ends releases a lock
    # it no longer holds.
    "lost": r"Lock is not acquired",
    # A recheck or a sign-out being asked about when the app stops goes on
    # after it.
    "left running": r"^(Auth\._ask|Session\._recheck_user|App\._end_sign_in)$",
    # A request cancelled in the moment it arrives is never forgotten.
    "request kept": r"still holds a request that is done$",
    # A chat message stopped in the moment it arrives leaves the chat busy.
    "chat stuck": r"is busy with no reply under way$",
    # A connect hook that waits on a task has its page drawn before it
    # returns, and two navigations then connect side by side, one of whose
    # pages is never closed.
    "drawn early": r"was drawn before its connect returned$",
    "never closed": r"page\(s\) that were opened$",
    # A file that arrives for a session in the moment it ends stays on disk.
    "files kept": r"with no session left$",
}
SCENARIOS = 250
AGAIN = "uv run python tests/lifecycle_fuzz.py --steps 60 --shrink"


def test_sessions_keep_their_promises_through_random_lives() -> None:
    new: dict[tuple[str, str], int] = {}
    seen: Counter[str] = Counter()
    for seed in range(SCENARIOS):
        for kind, detail in fuzz.run(seed=seed, steps=60).violations:
            seen[kind] += 1
            if kind not in KNOWN or not re.search(KNOWN[kind], detail):
                new.setdefault((kind, detail), seed)
    assert not new, "a promise that held is broken:\n" + "\n".join(
        f"  {kind}: {detail}\n    {AGAIN} --seed {seed}" for (kind, detail), seed in new.items()
    )
    # The run is only worth something if it gets as far as the known failures.
    assert seen["stranded"] and seen["sent after the end"]


def test_a_scenario_runs_the_same_way_twice() -> None:
    # With and without worker threads in it: both run the same way every time.
    threaded = next(
        s for s in range(50) if ("setup", "threads") in fuzz.run(seed=s, steps=5).actions
    )
    for seed in (3, 58, threaded):
        once, again = fuzz.run(seed=seed, steps=60), fuzz.run(seed=seed, steps=60)
        assert once.actions == again.actions
        assert once.violations == again.violations
        assert [(e["t"], e["kind"]) for e in once.log] == [(e["t"], e["kind"]) for e in again.log]


def test_a_failure_shrinks_to_the_few_actions_that_cause_it() -> None:
    # One of the known failures, with things around it that have no part in it.
    actions = [
        ("wait", 0.3),
        ("sign_in", 0, "cy"),
        ("knob", "handler_delay", 0.5),
        ("knob", "connect_fails", "boom"),
        ("open", 0, "/", True),
        ("open", 1, "/open", True),
        ("drop", 2),
        ("world", "ada", "demote"),
        ("wait", 2.5),
        ("finish", "empty"),
    ]
    leaking = fuzz.run(actions=actions)
    assert "leak" in leaking.kinds
    small = fuzz.shrink(leaking, "leak")
    assert "leak" in small.kinds
    assert small.actions == [
        ("knob", "connect_fails", "boom"),
        ("open", 1, "/open", True),
        ("drop", 1),
        ("finish", "empty"),
    ]
