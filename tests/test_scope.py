"""The scope: what it starts ends with it, and it gives back what a child
was handed, however the child ended."""

import asyncio
import logging

import pytest

from millwork.scope import Scope


async def test_done_is_called_for_a_child_that_finished_was_cancelled_or_never_ran() -> None:
    scope = Scope("s")
    seen: list[str] = []
    ran: list[str] = []

    async def work(name: str, gate: asyncio.Event) -> None:
        ran.append(name)
        await gate.wait()

    def done(name: str):  # type: ignore[no-untyped-def]
        return lambda task: seen.append(f"{name}:{'none' if task is None else task.cancelled()}")

    open_gate, shut_gate = asyncio.Event(), asyncio.Event()
    open_gate.set()
    scope.start(work("finished", open_gate), "a", done("finished"))
    cancelled = scope.start(work("cancelled", shut_gate), "b", done("cancelled"))
    # Cancelled in the moment it is started: it never runs a line, and no
    # ``finally`` of its own could have given anything back.
    never = scope.start(work("never ran", shut_gate), "c", done("never ran"))
    assert never is not None and cancelled is not None
    never.cancel()
    await asyncio.sleep(0)
    cancelled.cancel()
    await scope.wait(1.0)
    await asyncio.sleep(0)
    assert sorted(seen) == ["cancelled:True", "finished:False", "never ran:True"]
    assert ran == ["finished", "cancelled"]
    assert not scope.children


async def test_a_cancelled_scope_starts_nothing_and_still_says_done() -> None:
    scope = Scope("s")
    seen: list[object] = []
    ran: list[int] = []

    async def work() -> None:
        ran.append(1)

    scope.cancel()
    assert scope.start(work(), "late", seen.append) is None
    assert scope.later(0.0, ran.append, 2, dropped=lambda: seen.append("dropped")) is None
    await asyncio.sleep(0.01)
    assert seen == [None, "dropped"] and ran == []


async def test_cancelling_takes_every_child_and_timer_and_wait_sees_them_out() -> None:
    scope = Scope("s")
    seen: list[str] = []

    async def work(name: str) -> None:
        try:
            await asyncio.sleep(10)
        finally:
            seen.append(name)

    scope.start(work("a"), "a")
    scope.start(work("b"), "b")
    fired: list[int] = []
    timer = scope.later(0.01, fired.append, 1, dropped=lambda: seen.append("dropped"))
    kept = scope.later(0.01, fired.append, 2)
    assert timer is not None and kept is not None and timer.pending
    kept.cancel()
    await asyncio.sleep(0)
    scope.cancel()
    assert await scope.wait(1.0) == []
    await asyncio.sleep(0.03)
    assert sorted(seen) == ["a", "b", "dropped"] and fired == []
    assert not timer.pending


async def test_a_timer_fires_once_and_its_owner_can_cancel_it() -> None:
    scope = Scope("s")
    fired: list[int] = []
    scope.later(0.0, fired.append, 1)
    gone = scope.later(0.0, fired.append, 2)
    assert gone is not None
    gone.cancel()
    await asyncio.sleep(0.01)
    assert fired == [1]


async def test_a_child_that_will_not_stop_is_named_and_left(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scope = Scope("s")
    release = asyncio.Event()

    async def stubborn() -> None:
        while not release.is_set():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

    scope.start(stubborn(), "stubborn")
    await asyncio.sleep(0)
    scope.cancel()
    with caplog.at_level(logging.ERROR, logger="millwork.scope"):
        assert await scope.wait(0.02) == ["s: stubborn"]
    assert "still running" in caplog.text
    release.set()
    for child in scope.children:
        child.cancel()
    await scope.wait(1.0)


async def test_a_failure_that_gets_out_of_a_child_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scope = Scope("s")
    seen: list[object] = []

    async def breaks() -> None:
        raise RuntimeError("out")

    with caplog.at_level(logging.ERROR, logger="millwork.scope"):
        scope.start(breaks(), "breaks", seen.append)
        await scope.wait(1.0)
        await asyncio.sleep(0)
    assert "s: breaks failed" in caplog.text and len(seen) == 1


async def test_a_child_knows_it_is_one() -> None:
    scope = Scope("s")
    inside: list[bool] = []

    async def work() -> None:
        inside.append(scope.owns(asyncio.current_task()))

    scope.start(work(), "w")
    await scope.wait(1.0)
    assert inside == [True] and not scope.owns(asyncio.current_task())
