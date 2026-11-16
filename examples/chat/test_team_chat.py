"""The chat, driven without a browser. Each page a test opens is a session
of its own, and one opened with another ``visitor`` is another person."""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import ModuleType

import pytest

import millwork as mw
from millwork import ui
from millwork.testing import Page, TestApp


@pytest.fixture
async def t(example: ModuleType) -> AsyncIterator[TestApp]:
    harness = TestApp(example.app)
    yield harness
    # Stops the chat's clock, which the app started for itself.
    await harness.shutdown()


async def join(page: Page, name: str) -> None:
    await page.submit("join", {"name": name})


def here_now(page: Page) -> list[str]:
    """The people the sidebar shows as here, by the ids of their browsers."""
    return sorted(pid for pid in ("ada", "sam") if page.find_all(f"here-{pid}"))


class Tab:
    """A session as far as the chat looks at one: whose it is, and whether
    its tab is there."""

    def __init__(self, visitor: str) -> None:
        self.visitor = self
        self.id = visitor
        self.connected = True


async def test_a_newcomer_gives_a_name_and_is_in(t: TestApp, example: ModuleType) -> None:
    async with t.open("/c/general", visitor="ada") as ada:
        assert "Pick a name to join #general." in ada.text()
        # A name of spaces is no name.
        await ada.submit("join", {"name": "   "})
        assert ada.commands[-1].name == "form_issues"
        await join(ada, "  Ada   Park ")
        assert example.CHAT.people["ada"].name == "Ada Park"
        assert "Ada Park (you)" in ada.text()
        # What the team said before is there to read.
        assert "Lunch at one?" in ada.text()


async def test_the_front_door_leads_to_general(t: TestApp) -> None:
    async with t.open("/", visitor="ada") as ada:
        assert ada.session.path == "/c/general"


async def test_a_channel_that_is_not_there_is_not_found(t: TestApp) -> None:
    with pytest.raises(mw.NotFound):
        async with t.open("/c/nowhere", visitor="ada"):
            pass


async def test_a_message_reaches_everyone_on_the_channel(t: TestApp, example: ModuleType) -> None:
    async with (
        t.open("/c/general", visitor="ada") as ada,
        t.open("/c/general", visitor="sam") as sam,
    ):
        await join(ada, "Ada Park")
        await join(sam, "Sam Okafor")
        await ada.submit("say-general", "Is the soup place open?")
        await sam.settle()
        assert "Is the soup place open?" in sam.text()
        # The field emptied itself, and the draft went with it.
        assert ada.state.drafts["general"] == ""
        # Nothing but spaces is not a message.
        said = len(example.CHAT.channels["general"].messages)
        await ada.submit("say-general", "   ")
        assert len(example.CHAT.channels["general"].messages) == said


async def test_a_channel_counts_what_was_not_read(t: TestApp, example: ModuleType) -> None:
    async with (
        t.open("/c/general", visitor="ada") as ada,
        t.open("/c/design", visitor="sam") as sam,
    ):
        await join(ada, "Ada Park")
        await join(sam, "Sam Okafor")
        # Someone new has nothing to catch up on.
        assert sam.find("general").props["badge"] is None
        await ada.submit("say-general", "One.")
        await ada.submit("say-general", "Two.")
        await sam.settle()
        assert sam.find("general").props["badge"] == "2"
        # Ada has the channel in front of her, and her own words are read.
        assert ada.find("general").props["badge"] is None
        assert not ada.find_all("new-line")
        await sam.click("general")
        assert sam.session.path == "/c/general"
        assert sam.find("general").props["badge"] is None
        # A line stands above what was said since Sam was last here, and
        # is gone when he comes back a second time.
        lines = sam.text().splitlines()
        assert lines.index("New") < lines.index("One.") < lines.index("Two.")
        assert "Lunch at one?" in " ".join(lines[: lines.index("New")])
        # What is new to him stands on a tint, and what he had read does not.
        old, _, two = example.CHAT.channels["general"].messages[-3:]
        assert "bg-accent/60" in sam.find(f"m{two.id}").props["cls"]
        assert "bg-accent/60" not in sam.find(f"m{old.id}").props["cls"]
        await sam.click("design")
        await sam.click("general")
        assert not sam.find_all("new-line")


async def test_dots_stand_where_someone_is_typing(t: TestApp, example: ModuleType) -> None:
    async with (
        t.open("/c/general", visitor="ada") as ada,
        t.open("/c/general", visitor="sam") as sam,
        t.open("/c/design", visitor="pat") as pat,
    ):
        await join(ada, "Ada Park")
        await join(sam, "Sam Okafor")
        await join(pat, "Pat Lee")
        await ada.change("say-general", "Has any")
        await sam.settle()
        assert sam.find_all("typing-ada") and "Ada Park is typing" in sam.text()
        # Not to herself, and not on another channel.
        assert not ada.find_all("typing-ada") and not pat.find_all("typing-ada")
        # It runs out when she stops, at the clock's next tick.
        general = example.CHAT.channels["general"]
        general.typing["ada"] = time.monotonic() - 1
        example.CHAT.tick()
        await sam.settle()
        assert not sam.find_all("typing-ada")


async def test_a_time_is_on_the_viewers_clock(t: TestApp, example: ModuleType) -> None:
    chat = example.CHAT
    noon = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    chat.post(chat.add_channel("clock"), chat.people["seed:mara"], "Noon in UTC.", at=noon)
    async with (
        t.open("/c/clock", visitor="ada", timezone="Asia/Tokyo") as ada,
        t.open("/c/clock", visitor="sam", timezone="America/Lima") as sam,
    ):
        await join(ada, "Ada Park")
        await join(sam, "Sam Okafor")
        assert "21:00" in ada.text() and "07:00" in sam.text()
        assert "Friday 2 January" in ada.text()


async def test_a_new_channel_is_there_for_everyone(t: TestApp) -> None:
    async with (
        t.open("/c/general", visitor="ada") as ada,
        t.open("/c/general", visitor="sam") as sam,
    ):
        await join(ada, "Ada Park")
        await join(sam, "Sam Okafor")
        await ada.click("new")
        assert ada.state.creating
        for taken_or_wrong in ("design", "Release Notes"):
            await ada.submit("new-channel", {"name": taken_or_wrong})
            assert ada.commands[-1].name == "form_issues"
            assert ada.session.path == "/c/general"
        await ada.submit("new-channel", {"name": "releases", "topic": "What went out"})
        assert ada.session.path == "/c/releases" and not ada.state.creating
        assert "Nothing in #releases yet" in ada.text()
        await sam.settle()
        assert sam.find("releases").props["href"] == "/c/releases"


async def test_the_sidebar_says_who_is_here(t: TestApp) -> None:
    async with t.open("/c/general", visitor="ada") as ada:
        await join(ada, "Ada Park")
        async with t.open("/c/launch", visitor="sam") as sam:
            await join(sam, "Sam Okafor")
            await ada.settle()
            assert here_now(ada) == ["ada", "sam"]
        # Sam's session has ended, and its page said so as it closed. He
        # is still one of the team, among those who are away.
        await ada.settle()
        assert here_now(ada) == ["ada"] and ada.find_all("away-sam")


async def test_a_tab_that_went_away_is_noticed_by_the_clock(
    t: TestApp, example: ModuleType
) -> None:
    chat = example.CHAT
    async with t.open("/c/general", visitor="ada") as ada:
        await join(ada, "Ada Park")
        # A laptop that sleeps ends no session. Its tab is just not there.
        chat.join("sam", "Sam Okafor")
        tab = Tab("sam")
        chat.enter(chat.channels["launch"], tab)
        await ada.settle()
        assert here_now(ada) == ["ada", "sam"]
        tab.connected = False
        chat.tick()
        await ada.settle()
        assert here_now(ada) == ["ada"]


async def test_two_tabs_of_one_browser_are_one_person(t: TestApp) -> None:
    async with t.open("/c/general", visitor="sam") as sam:
        await join(sam, "Sam Okafor")
        async with t.open("/c/general", visitor="ada") as second:
            async with t.open("/c/general", visitor="ada") as first:
                # The name is given in one tab, and both are in.
                await join(first, "Ada Park")
                await second.settle()
                assert "Ada Park (you)" in second.text()
            # The first tab is closed, and Ada is still here in the other.
            await sam.settle()
            assert here_now(sam) == ["ada", "sam"]
            await sam.submit("say-general", "Still there?")
            await second.settle()
            assert "Still there?" in second.text()


async def test_a_long_channel_shows_its_latest_messages(t: TestApp, example: ModuleType) -> None:
    chat = example.CHAT
    long = chat.add_channel("log")
    for n in range(example.SHOWN + 5):
        chat.post(long, chat.people["seed:ito"], f"Line {n}.")
    async with t.open("/c/log", visitor="ada") as ada:
        await join(ada, "Ada Park")
        text = ada.text()
        assert f"The latest {example.SHOWN} messages." in text
        assert "Line 4." not in text.splitlines() and "Line 5." in text.splitlines()


async def test_a_mention_is_counted_and_stands_out(t: TestApp, example: ModuleType) -> None:
    async with (
        t.open("/c/general", visitor="ada") as ada,
        t.open("/c/design", visitor="sam") as sam,
    ):
        await join(ada, "Ada Park")
        await join(sam, "Sam Okafor")
        await ada.submit("say-general", "Nothing for anyone.")
        await sam.settle()
        assert sam.find("general").props["badge"] == "1"
        await ada.submit("say-general", "@sam can you look at this, and @nobody too?")
        await sam.settle()
        assert sam.find("general").props["badge"] == "@2"
        # The name of someone stands out in the text, and a word behind an
        # @ that is nobody's name is left as it was.
        message = example.CHAT.channels["general"].messages[-1]
        assert message.mentions == {"sam"}
        await sam.click("general")
        assert "**@sam** can you look at this, and @nobody too?" in [
            found.props["content"] for found in sam.find_all(ui.Markdown)
        ]
        # It stands on a tint for the one it names, and not for who wrote it.
        assert "bg-primary/10" in sam.find(f"m{message.id}").props["cls"]
        assert "bg-primary/10" not in ada.find(f"m{message.id}").props["cls"]


def test_an_at_names_someone_only_where_it_starts_a_word(example: ModuleType) -> None:
    chat = example.CHAT
    chat.join("sam", "Sam Okafor")
    chat.join("anne", "Anne-Marie Roux")
    general, mara = chat.channels["general"], chat.people["seed:mara"]
    for text, named in (
        ("@Sam, are you there?", {"sam"}),
        ("(see @sam)", {"sam"}),
        ("@anne-marie and @SAM", {"anne", "sam"}),
        ("write to sam@mara.example", set()),
        ("https://example.com/@sam", set()),
        ("`@sam` in code is not at a word's start", set()),
        ("@mara talking to herself", {"seed:mara"}),
    ):
        chat.post(general, mara, text)
        assert general.messages[-1].mentions == named, text


async def test_a_reaction_is_counted_for_everyone_and_taken_back(
    t: TestApp, example: ModuleType
) -> None:
    async with t.open("/c/design", visitor="ada") as ada, t.open("/c/design", visitor="sam") as sam:
        await join(ada, "Ada Park")
        await join(sam, "Sam Okafor")
        message = example.CHAT.channels["design"].messages[0]
        row = ada.find(f"m{message.id}")
        await ada.choose(ada.find(ui.DropdownMenu, within=row), "heart")
        await sam.settle()
        assert message.reactions == {"heart": {"ada"}}
        # Sam presses the one that is there, and it counts two.
        await sam.click(sam.find("heart", within=sam.find(f"m{message.id}")))
        await ada.settle()
        assert ada.find("heart", within=ada.find(f"m{message.id}")).props["label"] == "2"
        # Pressed again it is taken back, and the last one takes it away.
        await sam.click(sam.find("heart", within=sam.find(f"m{message.id}")))
        await ada.click(ada.find("heart", within=ada.find(f"m{message.id}")))
        assert message.reactions == {}
        assert not ada.find_all("heart", within=ada.find(f"m{message.id}"))
        # A tab can send what the menu never offered, and that is no reaction.
        for sent in ("confetti", ["heart"], None):
            await sam.event(
                sam.find(ui.DropdownMenu, within=sam.find(f"m{message.id}")), "select", sent
            )
        assert message.reactions == {}
        await ada.settle()
        assert "New empty states are up." in ada.text()


async def test_a_message_is_held_to_its_length_whatever_sends_it(
    t: TestApp, example: ModuleType
) -> None:
    async with t.open("/c/general", visitor="ada") as ada:
        await join(ada, "Ada Park")
        await ada.event("say-general", "submit", "y" * (example.LONGEST + 500))
        assert len(example.CHAT.channels["general"].messages[-1].text) == example.LONGEST
