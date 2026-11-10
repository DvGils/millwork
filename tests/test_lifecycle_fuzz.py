"""Random lives of sessions, checked against what the manual promises.

``lifecycle_fuzz`` drives the app the way browsers do, with time made
virtual, and reads back what happened. This runs a few hundred of its
scenarios on every test run, and fails when any of them breaks a promise.
"""

import importlib
from typing import Any

import lifecycle_fuzz as fuzz
import pytest

SCENARIOS = 250
AGAIN = "uv run python tests/lifecycle_fuzz.py --steps 60 --shrink"


def test_sessions_keep_their_promises_through_random_lives() -> None:
    broken: dict[tuple[str, str], int] = {}
    for seed in range(SCENARIOS):
        for kind, detail in fuzz.run(seed=seed, steps=60).violations:
            broken.setdefault((kind, detail), seed)
    assert not broken, "a promise is broken:\n" + "\n".join(
        f"  {kind}: {detail}\n    {AGAIN} --seed {seed}" for (kind, detail), seed in broken.items()
    )


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


def test_a_failure_shrinks_to_the_few_actions_that_cause_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failure made on purpose: a session that takes no notice of its tab
    # going away never ends. Around it, things that have no part in it.
    session = importlib.import_module("millwork.session")
    monkeypatch.setattr(session.Session, "detached", lambda self, conn: None)
    actions = [
        ("wait", 0.3),
        ("sign_in", 0, "cy"),
        ("knob", "handler_delay", 0.5),
        ("open", 0, "/", True),
        ("open", 1, "/open", True),
        ("click", 2, 3, 0),
        ("world", "ada", "demote"),
        ("wait", 2.5),
        ("finish", "empty"),
    ]
    leaking = fuzz.run(actions=actions)
    assert "leak" in leaking.kinds
    small = fuzz.shrink(leaking, "leak")
    assert "leak" in small.kinds
    assert small.actions == [("open", 1, "/open", True), ("finish", "empty")]


def test_the_oracle_notices_when_the_session_is_broken_on_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The run above is only worth something if a broken session fails it.
    # Four ways of breaking one, each of which a few scenarios must catch.
    scope = importlib.import_module("millwork.scope")
    session = importlib.import_module("millwork.session")
    connection = importlib.import_module("millwork.connection")
    outbox = importlib.import_module("millwork.outbox")

    def leaves_children(self: Any) -> None:
        self.cancelled = True

    def found(kind: str, seeds: int = 40) -> bool:
        return any(kind in fuzz.run(seed=seed, steps=60).kinds for seed in range(seeds))

    with monkeypatch.context() as broken:
        broken.setattr(scope.Scope, "cancel", leaves_children)
        assert found("ran after the end") or found("left running")
    with monkeypatch.context() as broken:
        broken.setattr(connection.Connection, "close", lambda self, end=None, code=1000: None)
        assert found("stranded")
    with monkeypatch.context() as broken:

        def draws_whoever_holds_the_turn(self: Any) -> None:
            self._render_timer = None
            self.render()

        broken.setattr(session.Session, "_render_tick", draws_whoever_holds_the_turn)
        # Rare: a render has to fall inside a handler's turn. A few seeds in
        # a hundred do it.
        assert found("half drawn", seeds=100)
    with monkeypatch.context() as broken:
        broken.setattr(outbox.Outbox, "seal", lambda self: None)
        broken.setattr(connection.Connection, "close", lambda self, end=None, code=1000: None)
        assert found("sent after the end")


def test_the_oracle_notices_a_page_with_lazy_parts_broken_on_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The promises of a page at rest, each broken in the one place that
    # keeps it.
    session = importlib.import_module("millwork.session")
    nodes = importlib.import_module("millwork.nodes")

    def found(kind: str, seeds: int = 40) -> bool:
        return any(kind in fuzz.run(seed=seed, steps=60).kinds for seed in range(seeds))

    with monkeypatch.context() as broken:
        # A part that was kept is called as it was, without being built.
        broken.setattr(session.Session, "bring_up", lambda self, node: True)
        assert found("kept part called")
    with monkeypatch.context() as broken:
        # What the tab says about its tabs is noted and nothing is drawn.
        refresh = session.Session.refresh

        def notes_and_leaves_it(self: Any, event: Any) -> None:
            broken.setattr(session.Session, "refresh", lambda self: None)
            try:
                shown(self, event)
            finally:
                broken.setattr(session.Session, "refresh", refresh)

        shown = session.Session.shown
        broken.setattr(session.Session, "shown", notes_and_leaves_it)
        assert found("tab not drawn")
    with monkeypatch.context() as broken:
        # The session takes no notice of what the tab says about its tabs.
        broken.setattr(session.Session, "shown", lambda self, event: None)
        assert found("tabs parted")
    with monkeypatch.context() as broken:
        # A patch that leaves out what changed in a node.
        diff = nodes.diff

        def forgets_changes(old: Any, new: Any) -> list[Any]:
            return [op for op in diff(old, new) if op.op != "set"]

        broken.setattr(session, "diff", forgets_changes)
        assert found("page differs")
    with monkeypatch.context() as broken:
        # A lazy part is taken as it was though its tab is the open one.
        part = nodes._part

        def never_shows(lazy: Any, node_id: str, index: int, tree: Any, how: Any, _: bool) -> Any:
            return part(lazy, node_id, index, tree, how, False)

        broken.setattr(nodes, "_part", never_shows)
        assert found("open part kept")
