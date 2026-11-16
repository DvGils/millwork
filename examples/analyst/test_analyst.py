"""The analyst, driven without a browser and without a model. The script
answers in most of these. In the last ones a stand-in for the model's
client says what a model would, so the loop around it is tested as well."""

import asyncio
import copy
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from starlette.testclient import TestClient

from millwork import ui
from millwork.testing import Page, TestApp

SAMPLES = Path(__file__).parent / "samples"


@pytest.fixture
async def page(example: ModuleType) -> AsyncIterator[Page]:
    # The script takes no time over its words here.
    example.analyst.PACE = 0
    async with TestApp(example.app).open("/") as page:
        yield page


def said(page: Page) -> str:
    """The words of the analyst's last answer."""
    return page.session.chat("analyst").messages[-1].text


def steps(page: Page) -> list[tuple[str, str]]:
    """The tools of the last answer, each with how it ended."""
    parts = page.session.chat("analyst").messages[-1].parts
    return [(p["type"].removeprefix("tool-"), p["state"]) for p in parts if "toolCallId" in p]


async def _nothing(*_: Any) -> None:
    return None


async def _step(name: str, given: dict[str, Any]) -> Any:
    return SimpleNamespace(output=_nothing, error=_nothing)


# A reply that shows nothing, for using a tool by hand.
QUIET: Any = SimpleNamespace(tool=_step)


def told(page: Page, words: str) -> bool:
    """Whether the last answer has an error that says this. It is kept
    with the message, so it is there after a reload as well."""
    parts = page.session.chat("analyst").messages[-1].parts
    return any(p["type"] == "error" and words in p["errorText"] for p in parts)


# ------------------------------------------------------------- the script


async def test_a_question_is_answered_from_the_data_and_pinned(page: Page) -> None:
    assert "Nothing pinned yet" in page.text()
    await page.send("analyst", "Which region sold the most in 2025?")
    assert said(page).startswith("**West**, with €678,413 in 2025.")
    assert steps(page) == [("query", "output-available"), ("show", "output-available")]
    card = page.state.cards[0]
    assert (card.kind, card.x, card.y) == ("bar", "region", "revenue")
    assert [row["region"] for row in card.rows] == ["West", "South", "East", "North"]
    assert page.find(ui.BarChart, within="card-1")


async def test_the_analyst_points_at_what_its_answer_is_about(page: Page) -> None:
    await page.send("analyst", "Show revenue by month")
    assert page.state.cards[0].kind == "line" and len(page.state.cards[0].rows) == 18
    await page.send("analyst", "What happened in March 2026?")
    assert "The West sold no stoves and no tarps in March 2026" in said(page)
    assert steps(page) == [("query", "output-available"), ("point_at", "output-available")]
    # The mark is on the month in the chart, not on the card around it.
    assert [(mark["id"], mark["part"]) for mark in page.marks] == [
        (page.find("card-1-chart").id, "2026-03")
    ]


async def test_pointing_is_at_a_card_or_at_a_value_a_chart_has(
    page: Page, example: ModuleType
) -> None:
    brain, db = example.analyst, example.DATA[page.session.id]
    await page.send("analyst", "Show revenue by month")
    await page.send("analyst", "What is in this?", files=[SAMPLES / "returns.csv"])
    gaps = "SELECT NULL AS x, 1 AS y UNION ALL SELECT 3, 2"
    chart = {"title": "Gaps", "sql": gaps, "kind": "bar", "x": "x", "y": "y"}
    await brain.use(page.session, db, QUIET, "show", chart)
    for given, words in (
        ({"card": "card-1", "at": "2031-01"}, "no chart with 2031-01"),
        ({"card": "card-2", "at": "0"}, "no chart with 0"),
        # A value that is nothing has no place in a chart to mark.
        ({"card": "card-3", "at": "None"}, "no chart with None"),
    ):
        result, failed = await brain.use(page.session, db, QUIET, "point_at", given)
        assert failed and words in result
    # A number along the bottom is named as a number or as its text.
    for given in ({"card": "card-2"}, {"card": "card-3", "at": 3}):
        _, failed = await brain.use(page.session, db, QUIET, "point_at", given)
        assert not failed
    await page.settle()
    assert [(mark["id"], mark.get("part")) for mark in page.marks] == [
        (page.find("card-2").id, None),
        (page.find("card-3-chart").id, 3),
    ]


async def test_a_question_the_script_does_not_know_says_so(page: Page) -> None:
    await page.send("analyst", "What is the weather like?")
    assert "I know only a few questions" in said(page)
    assert page.state.cards == []


async def test_a_csv_file_sent_with_a_message_is_a_table_to_ask_about(
    page: Page, tmp_path: Path
) -> None:
    await page.send("analyst", "What is in this?", files=[SAMPLES / "returns.csv"])
    assert "**returns** has 10 rows, with the columns product, region, units, reason." in said(page)
    assert page.state.cards[0].kind == "table" and page.state.cards[0].rows[0]["units"] == 14.0
    assert page.find("returns").props["label"] == "returns"
    # It is still there for the next question, by its name.
    await page.send("analyst", "And what is in returns again?")
    assert len(page.state.cards) == 2
    # A file that is no table is refused in the answer, with the reason.
    (tmp_path / "empty.csv").write_text("only,a,header\n")
    await page.send("analyst", "And this?", files=[tmp_path / "empty.csv"])
    assert told(page, "empty.csv was not added. That file has no rows")
    # A table whose name is a letter of the question does not take it over.
    (tmp_path / "w.csv").write_text("a\n1\n")
    await page.send("analyst", "", files=[tmp_path / "w.csv"])
    await page.send("analyst", "Which region sold the most in 2025?")
    assert said(page).startswith("**West**")


async def test_a_card_is_taken_down_and_the_desk_cleared(page: Page, example: ModuleType) -> None:
    await page.send("analyst", "Show revenue by month")
    await page.send("analyst", "Which region sold the most in 2025?")
    await page.click(page.find(ui.Button, within="card-1"))
    assert [card.id for card in page.state.cards] == ["card-2"]
    await page.click("over")
    assert page.state.cards == [] and page.session.chat("analyst").messages == []
    # A card made after that has an id none had before, and the board keeps
    # the newest of them.
    for _ in range(example.analyst.BOARD + 2):
        await page.send("analyst", "Show revenue by month")
    ids = [card.id for card in page.state.cards]
    assert len(ids) == example.analyst.BOARD and ids[-1] == f"card-{example.analyst.BOARD + 4}"


# --------------------------------------------------------------- the data


def test_a_query_only_reads_and_does_not_run_away(example: ModuleType) -> None:
    dataset = example.dataset
    db = dataset.fresh()
    assert dataset.query(db, "SELECT COUNT(*) AS n FROM orders").rows[0]["n"] > 10_000
    for sql in (
        "DELETE FROM orders",
        "DROP TABLE orders",
        "INSERT INTO orders VALUES ('x', 'x', 'x', 'x', 1, 1)",
        "SELECT 1; SELECT 2",
        "PRAGMA table_info(orders)",
        "ATTACH DATABASE '/tmp/other.db' AS other",
        "SELECT load_extension('x')",
        "not sql at all",
        # A value of many megabytes, which no time limit would stop.
        "SELECT randomblob(5000000) FROM orders",
        "SELECT hex(zeroblob(400000000))",
        "SELECT " + ", ".join(f"{n} AS c{n}" for n in range(60)),
    ):
        with pytest.raises(dataset.Refused):
            dataset.query(db, sql)
    # A join of the table with itself, many times over, is cut off.
    endless = "SELECT COUNT(*) FROM orders a, orders b, orders c"
    with pytest.raises(dataset.Refused, match="interrupted"):
        dataset.query(db, endless, seconds=0.05)
    assert dataset.query(db, "SELECT COUNT(*) AS n FROM orders").rows[0]["n"] > 10_000
    # A long answer is given in part, and says so.
    some = dataset.query(db, "SELECT * FROM orders", limit=50)
    assert len(some.rows) == 50 and some.more
    # Bytes come back by what they are, which a page can draw.
    assert dataset.query(db, "SELECT x'ff00' AS b").rows == [{"b": "<2 bytes>"}]


def test_a_file_is_a_table_or_is_refused(example: ModuleType) -> None:
    dataset = example.dataset
    db = dataset.fresh()
    assert dataset.load_csv(db, "Notes 2026.csv", "A b,n\nx,1\ny,2.5\n") == ("notes_2026", 2)
    assert dataset.query(db, 'SELECT a_b, n FROM "notes_2026"').rows[1] == {"a_b": "y", "n": 2.5}
    # One session's table is not in another's database.
    assert "notes_2026" not in dataset.tables(dataset.fresh())
    for name, text in (
        ("notes 2026.csv", "a\n1\n"),  # there already
        ("orders.csv", "a\n1\n"),  # the orders are not replaced
        ("sqlite_master.csv", "a\n1\n"),
        ('x"; DROP TABLE orders; --.csv', "a,a\n1,2\n"),  # two columns of one name
        ("wide.csv", ",".join(f"c{n}" for n in range(60)) + "\n" + ",".join("1" * 60) + "\n"),
        ("huge.csv", "a\n" + "x" * 200_000 + "\n"),
        ("empty.csv", ""),
    ):
        with pytest.raises(dataset.Refused):
            dataset.load_csv(db, name, text)
    with pytest.raises(dataset.Refused, match="more than 3 rows"):
        dataset.load_csv(db, "long.csv", "a\n1\n2\n3\n4\n", most=3)
    assert sorted(dataset.tables(db)) == ["notes_2026", "orders"]


def test_a_page_takes_pictures_from_the_app_alone(example: ModuleType) -> None:
    with TestClient(example.app.asgi) as client:
        policy = client.get("/").headers["content-security-policy"]
    assert "img-src 'self' data: blob:;" in policy and "https:" not in policy
    assert "script-src 'self' 'nonce-" in policy


async def test_a_tool_is_held_to_what_it_takes(page: Page, example: ModuleType) -> None:
    brain, db = example.analyst, example.DATA[page.session.id]

    by_region = "SELECT region, product FROM orders LIMIT 5"
    chart = {"title": "t", "sql": by_region, "kind": "bar", "x": "region", "y": "revenue"}
    for name, given, words in (
        ("drop", {}, "no tool drop"),
        ("query", {}, "Field required"),
        ("show", {**chart, "kind": "pie"}, "Input should be"),
        # A chart of columns the query does not have, or of words.
        ("show", chart, "which are region, product"),
        ("show", {**chart, "y": "product"}, "has to hold numbers"),
        ("point_at", {"card": "card-9"}, "no card card-9"),
        ("query", {"sql": "DELETE FROM orders"}, "not authorized"),
    ):
        result, failed = await brain.use(page.session, db, QUIET, name, given)
        assert failed and words in result, name
    assert page.state.cards == []


# -------------------------------------------------------------- the model


class Stream:
    """What the client's stream is to the loop: the events of one message
    as they come, and then the whole message."""

    def __init__(self, stop_reason: str, content: list[dict[str, Any]]) -> None:
        self.content = content
        self.message = SimpleNamespace(
            stop_reason=stop_reason, to_dict=lambda: {"content": content}
        )

    async def __aenter__(self) -> "Stream":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def __aiter__(self) -> AsyncIterator[Any]:
        for block in self.content:
            if block["type"] in ("thinking", "text"):
                yield SimpleNamespace(
                    **{"type": block["type"], block["type"]: block[block["type"]]}
                )

    async def get_final_message(self) -> Any:
        return self.message


class Model:
    """A client that answers each request with the next of the messages it
    was given, and keeps what it was sent."""

    def __init__(self, *messages: tuple[str, list[dict[str, Any]]]) -> None:
        self.answers = list(messages)
        self.sent: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **request: Any) -> Stream:
        self.sent.append(copy.deepcopy(request))
        return Stream(*self.answers.pop(0))


def text(words: str) -> dict[str, Any]:
    # With the keys the SDK gives a block that the loop has no use for.
    return {"type": "text", "text": words, "citations": None}


def tool_use(id: str, name: str, **given: Any) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": id,
        "name": name,
        "input": given,
        "caller": {"type": "direct"},
    }


def sound(history: list[dict[str, Any]]) -> bool:
    """Whether a conversation is one the API takes: every call an answer
    makes has its result in the message that follows it."""
    for n, turn in enumerate(history):
        if turn["role"] == "assistant":
            calls = [b["id"] for b in turn["content"] if b["type"] == "tool_use"]
            after = history[n + 1]["content"] if n + 1 < len(history) else []
            results = [
                b["tool_use_id"] for b in after if isinstance(b, dict) and "tool_use_id" in b
            ]
            if calls != results:
                return False
    return True


@pytest.fixture
def model(example: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Any:
    def put(*messages: tuple[str, list[dict[str, Any]]]) -> Model:
        client = Model(*messages)
        monkeypatch.setattr(example.analyst, "CLIENT", client)
        return client

    return put


BY_REGION = "SELECT region, SUM(revenue) AS revenue FROM orders GROUP BY region"
COUNT = tool_use("t1", "query", sql="SELECT COUNT(*) AS n FROM orders")


async def test_the_model_asks_for_tools_and_gets_their_results(page: Page, model: Any) -> None:
    chart = {"sql": BY_REGION, "kind": "bar", "x": "region"}
    client = model(
        (
            "tool_use",
            [
                {
                    "type": "thinking",
                    "thinking": "Revenue by region answers this.",
                    "signature": "s1",
                },
                text("Let me look. "),
                tool_use("t1", "query", sql=BY_REGION),
                tool_use("t2", "show", title="By region", y="revenue", **chart),
                tool_use("t3", "show", title="Bad", y="nothing", **chart),
            ],
        ),
        ("end_turn", [text("The West leads.")]),
    )
    await page.send("analyst", "Who leads?")
    # Its reasoning and its words are in the chat, with the tools it used.
    parts = page.session.chat("analyst").messages[-1].parts
    assert parts[0]["type"] == "reasoning" and parts[0]["text"] == "Revenue by region answers this."
    assert said(page) == "Let me look. The West leads."
    assert steps(page) == [
        ("query", "output-available"),
        ("show", "output-available"),
        ("show", "output-error"),
    ]
    assert [card.title for card in page.state.cards] == ["By region"]
    # The second request carries the first answer as it came, reasoning and
    # all, and one message with a result for each call, in their order.
    first, second = client.sent
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert [tool["name"] for tool in first["tools"]] == ["query", "show", "point_at"]
    question = first["messages"][0]["content"]
    assert "- orders(day, region, product, channel, units, revenue)" in question
    assert question.endswith("Question: Who leads?")
    assert second["messages"][:1] == first["messages"]
    assert second["messages"][1]["content"][0]["signature"] == "s1"
    assert second["messages"][1]["content"][2] == tool_use("t1", "query", sql=BY_REGION)
    results = second["messages"][2]["content"]
    assert [(r["tool_use_id"], r["is_error"]) for r in results] == [
        ("t1", False),
        ("t2", False),
        ("t3", True),
    ]
    assert (
        '"West"' in results[0]["content"] and "which are region, revenue" in results[2]["content"]
    )
    # And what the model said last is kept for the next question.
    assert page.state.history[-1]["content"] == [text("The West leads.")]
    assert sound(page.state.history) and len(page.state.history) == 4


async def test_the_next_question_tells_the_model_what_is_on_the_board(
    page: Page, model: Any
) -> None:
    by_month = "SELECT substr(day, 1, 7) AS month, SUM(revenue) AS revenue FROM orders GROUP BY 1"
    chart = tool_use(
        "t1", "show", title="By month", sql=by_month, kind="line", x="month", y="revenue"
    )
    client = model(
        ("tool_use", [chart]),
        ("end_turn", [text("Pinned.")]),
        ("end_turn", [text("It is the line chart.")]),
        ("end_turn", [text("Ten rows of returns.")]),
    )
    await page.send("analyst", "Chart it")
    await page.send("analyst", "What am I looking at?")
    # The page as data: the card the person sees, by its title.
    assert "By month" in client.sent[2]["messages"][-1]["content"]
    assert len(client.sent[2]["messages"]) == 5
    # And a file that came with a message is a table it is told of.
    await page.send("analyst", "", files=[SAMPLES / "returns.csv"])
    last = client.sent[3]["messages"][-1]["content"]
    assert "- returns(product, region, units, reason)" in last
    assert "now the table returns" in last and last.endswith("Question: What is in it?")


@pytest.mark.parametrize(
    ("ended", "words"),
    [
        ("max_tokens", "cut off"),
        ("refusal", "not something I can help with"),
        ("model_context_window_exceeded", "grown too long"),
    ],
)
async def test_an_answer_that_did_not_finish_is_not_kept(
    page: Page, model: Any, ended: str, words: str
) -> None:
    # Each of these can carry a call that was never meant to run.
    client = model((ended, [text("Let me "), COUNT]), ("end_turn", [text("There are many.")]))
    await page.send("analyst", "Count them")
    assert steps(page) == [] and told(page, words)
    assert [turn["role"] for turn in page.state.history] == ["user"]
    # The conversation goes on from the question, and the model takes it.
    await page.send("analyst", "Count them again")
    assert said(page) == "There are many."
    assert sound(client.sent[1]["messages"]) and sound(page.state.history)


async def test_a_tool_that_fails_or_is_stopped_leaves_a_conversation_that_goes_on(
    page: Page, example: ModuleType, model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    brain = example.analyst
    waiting = asyncio.Event()

    async def broken(*_: Any) -> None:
        raise RuntimeError("the disk is gone")

    async def slow(*_: Any) -> None:
        waiting.set()
        await asyncio.sleep(60)

    client = model(
        ("tool_use", [COUNT]),
        ("end_turn", [text("I could not count them.")]),
        ("tool_use", [COUNT]),
    )
    # A tool that raises is an answer to its call like any other, in words
    # that say nothing of what went wrong inside.
    monkeypatch.setitem(brain.TOOLS, "query", (brain.Query, broken))
    await page.send("analyst", "Count them")
    result = client.sent[1]["messages"][2]["content"][0]
    assert result["is_error"] and result["content"] == "The tool failed."
    assert steps(page) == [("query", "output-error")] and sound(page.state.history)
    # Stopped in the middle of a tool, the answer leaves nothing behind.
    monkeypatch.setitem(brain.TOOLS, "query", (brain.Query, slow))
    kept = len(page.state.history)
    asking = asyncio.ensure_future(page.send("analyst", "Count them again"))
    await waiting.wait()
    await page.stop("analyst")
    await asking
    assert len(page.state.history) == kept + 1 and page.state.history[-1]["role"] == "user"
    assert sound(page.state.history)


async def test_an_answer_another_model_took_over_keeps_what_the_api_wants_back(
    page: Page, model: Any
) -> None:
    client = model(
        (
            "tool_use",
            [
                {"type": "thinking", "thinking": "First thoughts.", "signature": "s1"},
                text("Let me "),
                tool_use("t0", "query", sql="SELECT 0 AS declined"),
                {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}},
                text("look. "),
                COUNT,
            ],
        ),
        ("end_turn", [text("Many.")]),
    )
    await page.send("analyst", "Count them")
    # Only the call made after the other model took over is run.
    assert steps(page) == [("query", "output-available")]
    kept = [block["type"] for block in client.sent[1]["messages"][1]["content"]]
    assert kept == ["text", "fallback", "text", "tool_use"]
    assert [r["tool_use_id"] for r in client.sent[1]["messages"][2]["content"]] == ["t1"]
    assert sound(page.state.history)


async def test_the_model_is_given_only_so_many_rounds(
    page: Page, example: ModuleType, model: Any
) -> None:
    client = model(*[("tool_use", [COUNT])] * 20)
    await page.send("analyst", "Loop")
    assert len(client.sent) == example.analyst.ROUNDS
    assert said(page) == "That took more steps than I am given for one question."
    # Every call it made has its result, so the next question can follow.
    assert sound(page.state.history) and page.state.history[-1]["role"] == "user"
