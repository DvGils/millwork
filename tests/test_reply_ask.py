"""A question in a reply: the reply waits for the person, goes on with the
value they chose, and the message keeps how the question ended."""

import asyncio
import json
from typing import Any

import pytest
from pydantic import BaseModel

import millwork as mw
from millwork import ui
from millwork.testing import TestApp

DELETE = {"no": "Keep them", "yes": "Delete", "always": "Always delete here"}


class State(BaseModel):
    off: bool = False


def make(ask: dict[str, Any] | None = None) -> tuple[mw.App, list[Any]]:
    """An app whose chat asks one question, and what the reply got for it."""
    app = mw.App("asks", state=State, public=None)
    got: list[Any] = []
    how = {"options": DELETE, "primary": "yes"} | (ask or {})

    async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
        async with turn.reply() as reply:
            await reply.text("Archive holds 14 files.")
            try:
                async with reply.step("Clearing"):
                    chosen = await reply.ask(
                        "Delete the 14 files?", "Nothing links to them.", **how
                    )
                    got.append(chosen)
            except asyncio.CancelledError:
                got.append("stopped")
                raise
            await reply.text("Done.")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Chat(key="c", on_message=answer, disabled=s.state.off))

    return app, got


def question(page: Any) -> dict[str, Any]:
    """The question of the last message, as the message keeps it."""
    parts = page.session.chat("c").messages[-1].parts
    return next(p for p in parts if p["type"] == "data-ask")["data"]


async def test_a_reply_asks_and_goes_on_with_what_was_chosen() -> None:
    app, got = make()
    async with TestApp(app).open("/") as page:
        await page.send("c", "clean up")
        thread = page.session.chat("c")
        # The reply waits for the person, and the page says what for.
        assert thread.busy and thread.asking and got == []
        said = page.outline(as_text=True)
        assert "waits for an answer" in said
        assert "Delete the 14 files? (asks: Keep them / Delete / Always delete here)" in said
        await page.answer("always")
        await page.settle()
        assert got == ["always"]
        assert not thread.busy and not thread.asked
        asked = question(page)
        assert asked["open"] is False and asked["answer"] == "always"
        assert asked["question"] == "Delete the 14 files?" and asked["primary"] == "yes"
        assert thread.messages[-1].text == "Archive holds 14 files.Done."
        assert "(answered: Always delete here)" in page.outline(as_text=True)


async def test_an_answer_that_was_not_offered_and_a_second_answer_are_not_taken() -> None:
    app, got = make()
    async with TestApp(app).open("/") as page:
        await page.send("c", "clean up")
        (ask_id,) = page.session.chat("c").asked
        with pytest.raises(LookupError, match="does not offer 'maybe'"):
            await page.event("c", "answer", {"id": ask_id, "value": "maybe"})
        with pytest.raises(LookupError, match="answered with one of"):
            await page.answer("maybe")
        assert got == []
        await page.answer("no")
        await page.settle()
        with pytest.raises(LookupError, match="no open question"):
            await page.event("c", "answer", {"id": ask_id, "value": "yes"})
        with pytest.raises(LookupError, match="nothing is being asked"):
            await page.answer("yes")
        assert got == ["no"] and question(page)["answer"] == "no"


async def test_a_reply_that_is_stopped_leaves_its_question_not_answered() -> None:
    app, got = make()
    async with TestApp(app).open("/") as page:
        await page.send("c", "clean up")
        await page.stop("c")
        await page.settle()
        thread = page.session.chat("c")
        assert got == ["stopped"]
        assert not thread.busy and not thread.asked
        assert question(page) | {"options": []} == {
            "question": "Delete the 14 files?",
            "description": "Nothing links to them.",
            "options": [],
            "primary": "yes",
            "open": False,
            "answer": None,
        }
        assert "(not answered)" in page.outline(as_text=True)


async def test_a_question_nobody_answers_in_time_is_answered_with_nothing() -> None:
    app, got = make({"timeout": 0.05})
    async with TestApp(app).open("/") as page:
        await page.send("c", "clean up")
        thread = page.session.chat("c")
        turn = thread.turn_task
        assert turn is not None
        await asyncio.wait({turn}, timeout=5)
        await page.settle()
        assert got == [None] and question(page)["answer"] is None
        assert thread.messages[-1].text.endswith("Done.")


async def test_the_wait_for_the_person_is_no_part_of_how_long_a_reply_took() -> None:
    app, _ = make()
    async with TestApp(app).open("/") as page:
        await page.send("c", "clean up")
        await asyncio.sleep(0.3)
        await page.answer("yes")
        await page.settle()
        message = page.session.chat("c").messages[-1]
        step = next(p for p in message.parts if p["type"] == "tool-step")
        assert message.metadata is not None and message.metadata["took"] < 0.2
        assert step["took"] < 0.2


async def test_a_chat_that_is_disabled_still_takes_the_answer_to_its_question() -> None:
    app, got = make()
    async with TestApp(app).open("/") as page:
        await page.send("c", "clean up")
        page.state.off = True
        page.session.refresh()
        await page.settle()
        assert page.find("c").props["disabled"] is True
        await page.answer("yes")
        await page.settle()
        assert got == ["yes"]


@pytest.mark.parametrize(
    ("options", "offered"),
    [
        (["Work", "Home"], [("Work", "Work"), ("Home", "Home")]),
        ([("w", "Work"), ("h", "Home")], [("w", "Work"), ("h", "Home")]),
        ({"w": "Work", "h": "Home"}, [("w", "Work"), ("h", "Home")]),
        (
            [ui.Option(value="w", label="Work", icon="briefcase"), "Home"],
            [("w", "Work"), ("Home", "Home")],
        ),
    ],
)
async def test_the_options_of_a_question_are_what_a_select_takes(
    options: Any, offered: list[tuple[str, str]]
) -> None:
    app, _ = make({"options": options, "primary": None})
    async with TestApp(app).open("/") as page:
        await page.send("c", "which")
        (asked,) = page.session.chat("c").asked.values()
        assert [(o["value"], o["label"]) for o in asked.data["options"]] == offered
        assert "primary" not in asked.data
        if isinstance(options[0] if isinstance(options, list) else None, ui.Option):
            assert asked.data["options"][0]["icon"] == "briefcase"
        await page.answer(offered[0][0])


@pytest.mark.parametrize(
    ("how", "why"),
    [
        ({"options": []}, "at least one option"),
        ({"options": ["a", "a"]}, "a value of their own"),
        ({"options": ["a", "b"], "primary": "c"}, "not one of the options"),
    ],
)
async def test_a_question_that_cannot_be_answered_is_refused(how: dict[str, Any], why: str) -> None:
    app, _ = make({"primary": None} | how)
    async with TestApp(app, strict=False).open("/") as page:
        await page.send("c", "which")
        ((_, raised),) = page.failures
        assert isinstance(raised, ValueError) and why in str(raised)
        assert not page.session.chat("c").asked


async def test_a_tab_that_comes_back_is_told_the_reply_as_far_as_it_came() -> None:
    app = mw.App("midway", public=None)
    go_on = asyncio.Event()

    async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
        async with turn.reply() as reply:
            await reply.text("First. ")
            async with reply.reasoning() as thought:
                await thought.text("hm")
            done = await reply.tool("lookup", {"q": 1})
            await done.output({"hits": 2})
            await reply.status("Reading")
            async with reply.step("Clearing"):
                await reply.text("Half a sen")
                await go_on.wait()
                await reply.text("tence.")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Chat(key="c", on_message=answer))

    async with TestApp(app).open("/") as page:
        sending = asyncio.ensure_future(page.send("c", "go"))
        thread = page.session.chat("c")
        for _ in range(1000):
            if thread.reply is not None and thread.reply._status == "Reading":
                break
            await asyncio.sleep(0)
        for _ in range(20):
            await asyncio.sleep(0)
        again = [json.loads(text)["msg"]["chunk"] for text in page.session.replies()]
        kinds = [c["type"] for c in again]
        assert kinds == [
            "start",
            "start-step",
            "text-start",
            "text-delta",
            "text-end",
            "reasoning-start",
            "reasoning-delta",
            "reasoning-end",
            "tool-input-available",
            "tool-output-available",
            "tool-input-available",
            "text-start",
            "text-delta",
            "data-status",
        ]
        assert again[0]["messageId"] == thread.reply.message.id
        assert again[9]["output"] == {"hits": 2}
        assert again[12]["delta"] == "Half a sen"
        # What is still being written keeps its id, so the rest of it
        # lands in the same place.
        go_on.set()
        await sending
        await page.settle()
        rest = next(c for c in reversed(page.stream) if c["type"] == "text-delta")
        assert rest["delta"] == "tence." and rest["id"] == again[12]["id"]
        assert page.session.replies() == []


async def test_a_tool_in_a_thread_asks_through_the_loop_and_is_let_go_by_a_stop() -> None:
    app = mw.App("threads", public=None)
    got: list[Any] = []

    async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
        loop = asyncio.get_running_loop()
        async with turn.reply() as reply:

            def tool() -> None:
                asking = reply.ask("Go on?", options=["Yes", "No"])
                try:
                    got.append(asyncio.run_coroutine_threadsafe(asking, loop).result(20))
                except BaseException as exc:
                    got.append(type(exc).__name__)

            await asyncio.to_thread(tool)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Chat(key="c", on_message=answer))

    async def asked(thread: Any) -> None:
        # The question comes from another thread, so in its own time.
        for _ in range(500):
            if thread.asking:
                return
            await asyncio.sleep(0.02)
        raise AssertionError("no question came")

    async with TestApp(app).open("/") as page:
        thread = page.session.chat("c")
        sending = asyncio.ensure_future(page.send("c", "go"))
        await asked(thread)
        await sending
        await page.answer("Yes")
        await page.settle()
        assert got == ["Yes"]
        # Stopped, the reply ends its question, and the thread that waited
        # on the answer is let go.
        sending = asyncio.ensure_future(page.send("c", "again"))
        await asked(thread)
        await sending
        await page.stop("c")
        await page.settle()
        loop = asyncio.get_running_loop()
        until = loop.time() + 5
        while len(got) < 2 and loop.time() < until:  # noqa: ASYNC110
            await asyncio.sleep(0.02)
        assert got == ["Yes", "CancelledError"]
        assert not thread.asked and not thread.busy
        closed = next(p for p in thread.messages[-1].parts if p["type"] == "data-ask")["data"]
        assert closed["open"] is False and closed["answer"] is None


async def test_two_questions_open_at_once_wait_once_and_take_only_strings() -> None:
    app = mw.App("two", public=None)

    async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
        async with turn.reply() as reply:
            async with reply.step("Both"):
                await asyncio.gather(
                    reply.ask("First?", options=["a", "b"]),
                    reply.ask("Second?", options=["c", "d"]),
                )
                await asyncio.sleep(0.3)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Chat(key="c", on_message=answer))

    async with TestApp(app).open("/") as page:
        await page.send("c", "go")
        thread = page.session.chat("c")
        first, second = thread.asked
        await asyncio.sleep(0.3)
        # A value that is no string is one the question does not offer.
        with pytest.raises(LookupError, match="does not offer"):
            await page.event("c", "answer", {"id": first, "value": ["a"]})
        await page.answer("d")
        await page.event("c", "answer", {"id": first, "value": "a"})
        await page.settle()
        message = thread.messages[-1]
        step = next(p for p in message.parts if p["type"] == "tool-step")
        # The work after the answers is counted, and the wait is not, though
        # two questions had it at the same time.
        assert message.metadata is not None
        assert 0.2 < message.metadata["took"] < 0.5
        assert 0.2 < step["took"] < 0.5
