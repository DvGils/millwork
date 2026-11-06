"""Random lives of sessions, checked against what the manual promises.

``lifecycle_fuzz`` drives the app the way browsers do, with time made
virtual, and reads back what happened. This runs a few hundred of its
scenarios on every test run. It fails when a promise that holds today is
broken, and when one of the known failures stops failing, so the list below
only ever gets shorter.
"""

from collections import Counter

import lifecycle_fuzz as fuzz

# Promises the session's life does not keep yet, each found by the fuzzer and
# reduced to a few actions:
#
# stranded            a tab that was not reading when its session ended is
#                     never told, and stays connected to nothing
# leak                a connect hook that raises for a tab that has already
#                     gone leaves its session behind for good
# sent after the end  a toast or a navigation asked for before the end, or a
#                     reconnecting tab's replay, reaches the tab after it
# lost                a handler waiting on a question when its session ends
#                     releases a lock it no longer holds
# left running        a recheck that is being asked when the app stops goes
#                     on after it
KNOWN = {"stranded", "leak", "sent after the end", "lost", "left running"}
SCENARIOS = 250


def test_sessions_keep_their_promises_through_random_lives() -> None:
    broken: Counter[str] = Counter()
    first: dict[str, int] = {}
    for seed in range(SCENARIOS):
        for kind in fuzz.run(seed=seed, steps=60).kinds:
            broken[kind] += 1
            first.setdefault(kind, seed)
    new = {kind: first[kind] for kind in broken if kind not in KNOWN}
    assert not new, "a promise that held is broken; replay with " + ", ".join(
        f"`uv run python tests/lifecycle_fuzz.py --seed {seed} --steps 60 --shrink` ({kind})"
        for kind, seed in new.items()
    )


def test_a_scenario_runs_the_same_way_twice() -> None:
    for seed in (3, 58, 457):
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
