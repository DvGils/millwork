"""The turn: one holder at a time, and nobody goes on without it."""

import asyncio
from typing import Any

from millwork.turn import Turn


def never() -> bool:
    return False


async def test_turns_are_taken_in_the_order_they_were_asked_for() -> None:
    turn = Turn()
    order: list[str] = []

    async def work(name: str) -> None:
        await turn.take(name)
        order.append(name)
        await asyncio.sleep(0)
        turn.give_back(name)

    await asyncio.gather(work("a"), work("b"), work("c"))
    assert order == ["a", "b", "c"] and turn.free and not turn.waiting


async def test_giving_back_does_nothing_for_someone_who_does_not_hold_it() -> None:
    turn = Turn()
    await turn.take("a")
    turn.give_back("b")
    assert turn.holder == "a"
    turn.give_back("a")
    turn.give_back("a")
    assert turn.free


async def test_someone_cancelled_while_in_line_is_passed_over() -> None:
    turn = Turn()
    await turn.take("a")
    b = asyncio.ensure_future(turn.take("b"))
    c = asyncio.ensure_future(turn.take("c"))
    await asyncio.sleep(0)
    b.cancel()
    await asyncio.sleep(0)
    turn.give_back("a")
    await c
    assert turn.holder == "c"


async def test_the_scope_gives_back_a_turn_handed_to_a_task_that_died_first() -> None:
    # The turn is handed over, and the one it was handed to is cancelled
    # before it runs. Nothing in that task can give the turn back. Whoever
    # watches the task can, by its name.
    turn = Turn()
    await turn.take("a")

    async def work() -> None:
        await turn.take(asyncio.current_task())
        raise AssertionError("never gets here")

    b = asyncio.ensure_future(work())
    c = asyncio.ensure_future(turn.take("c"))
    await asyncio.sleep(0)
    turn.give_back("a")
    assert turn.holder is b
    b.cancel()
    await asyncio.sleep(0)
    assert b.cancelled() and turn.holder is b
    turn.give_back(b)
    await c
    assert turn.holder == "c"


async def test_a_lent_turn_is_taken_again_after_the_wait() -> None:
    turn = Turn()
    seen: list[str] = []
    answer: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def asks() -> None:
        await turn.take("a")
        async with turn.lent("a", never):
            await answer
        seen.append(f"a goes on holding it: {turn.holder == 'a'}")
        turn.give_back("a")

    async def other() -> None:
        await turn.take("b")
        seen.append("b ran meanwhile")
        answer.set_result(None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        turn.give_back("b")

    await asyncio.gather(asks(), other())
    assert seen == ["b ran meanwhile", "a goes on holding it: True"]


async def test_lending_does_nothing_for_someone_who_does_not_hold_the_turn() -> None:
    turn = Turn()
    await turn.take("a")
    async with turn.lent("b", never):
        assert turn.holder == "a"
    assert turn.holder == "a"


async def test_a_timeout_during_the_wait_for_the_turn_is_held_until_the_turn_is_back() -> None:
    # A handler puts a timeout on its question. The answer comes, the handler
    # waits to get its turn back from another that holds it, and the timeout
    # fires in that wait. It must not go on without the turn.
    turn = Turn()
    seen: list[Any] = []
    answer: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    release = asyncio.Event()

    async def asks() -> None:
        await turn.take("a")
        try:
            async with asyncio.timeout(0.02):
                async with turn.lent("a", never):
                    await answer
        except TimeoutError:
            seen.append(("timed out, holding the turn", turn.holder == "a"))
        turn.give_back("a")

    async def other() -> None:
        await turn.take("b")
        answer.set_result(None)
        await release.wait()
        seen.append("b is done")
        turn.give_back("b")

    both = asyncio.gather(asks(), other())
    await asyncio.sleep(0.05)
    assert seen == []
    release.set()
    await both
    assert seen == ["b is done", ("timed out, holding the turn", True)]
    assert turn.free


async def test_the_end_lets_go_of_the_wait_for_a_lent_turn() -> None:
    turn = Turn()
    over = False
    answer: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def asks() -> None:
        await turn.take("a")
        async with turn.lent("a", lambda: over):
            await answer

    task = asyncio.ensure_future(asks())
    await asyncio.sleep(0)
    await turn.take("b")
    answer.set_result(None)
    await asyncio.sleep(0)
    assert turn.waiting == 1
    over = True
    task.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert task.cancelled() and turn.holder == "b" and not turn.waiting


async def test_what_is_due_when_the_turn_comes_free_runs_before_the_next_in_line() -> None:
    turn = Turn()
    seen: list[str] = []
    turn.on_free = lambda: seen.append(f"free, held by {turn.holder}")
    await turn.take("a")
    b = asyncio.ensure_future(turn.take("b"))
    await asyncio.sleep(0)
    turn.give_back("a")
    await b
    seen.append(f"then {turn.holder}")
    assert seen == ["free, held by None", "then b"]
