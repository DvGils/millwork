"""What everyone on the chat shares, which is the channels, their messages,
who has read what and who is typing. It is kept outside every session, in
one ``Chat``, and a ``mw.Signal`` stands next to each thing that changes by
itself, so the pages that show it are drawn again when it does."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import millwork as mw

# How long after a keystroke someone still counts as typing, in seconds.
TYPING_FOR = 4.0
# Someone is mentioned by their first name behind an @ that starts a word,
# so the @ in an address or a link names nobody.
MENTION = re.compile(r"(?<!\S)@(\w[\w'-]*)")


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    # Which of the theme's five chart colors their picture has.
    color: int

    @property
    def first(self) -> str:
        return self.name.split()[0]

    @property
    def initials(self) -> str:
        words = self.name.split()
        return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


@dataclass
class Message:
    id: int
    author: Person
    text: str
    at: datetime
    # The ids of the people it mentions.
    mentions: frozenset[str] = frozenset()
    # Who reacted with what, as the ids of the people by the reaction's name.
    reactions: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class Channel:
    name: str
    topic: str = ""
    messages: list[Message] = field(default_factory=list)
    # Who is typing, by their id, and until when that counts.
    typing: dict[str, float] = field(default_factory=dict)
    # Fired for what only the pages on this channel show, which is who is
    # typing here and the reactions to its messages. No other page follows
    # it, so a keystroke draws nobody else's page.
    changed: mw.Signal = field(default_factory=mw.Signal)
    # The sessions that have this channel open, for knowing who is looking.
    watching: set[Any] = field(default_factory=set)

    def typists(self, but: str) -> list[str]:
        return sorted(pid for pid in self.typing if pid != but)


class Chat:
    def __init__(self) -> None:
        self.channels: dict[str, Channel] = {}
        self.people: dict[str, Person] = {}
        # The last message someone has seen in a channel, by person and channel.
        self.last_seen: dict[tuple[str, str], int] = {}
        # Fired when a message is posted, a channel is made or someone comes
        # or goes, which is what every page shows in its sidebar.
        self.changed = mw.Signal()
        self._ids = 0
        self._online: frozenset[str] = frozenset()

    # ------------------------------------------------------------ people

    def join(self, pid: str, name: str) -> Person:
        # The colors go around, so the first five people each have their own.
        person = self.people[pid] = Person(pid, name, len(self.people) % 5 + 1)
        # Someone new starts with nothing to catch up on.
        for channel in self.channels.values():
            self._seen(pid, channel)
        self.changed.fire()
        return person

    def online(self) -> list[Person]:
        """Everyone who has given a name and has a tab open, by name."""
        here = {s.visitor.id for c in self.channels.values() for s in c.watching if s.connected}
        return sorted((self.people[p] for p in here if p in self.people), key=lambda p: p.name)

    # ---------------------------------------------------------- channels

    def add_channel(self, name: str, topic: str = "") -> Channel:
        channel = self.channels[name] = Channel(name, topic)
        self.changed.fire()
        return channel

    def enter(self, channel: Channel, session: Any) -> int:
        """A session has the channel open. Gives the last message its person
        had seen there before, for telling them what is new."""
        pid = session.visitor.id
        seen = self.last_seen.get((pid, channel.name), 0)
        channel.watching.add(session)
        self._seen(pid, channel)
        self.changed.fire()
        return seen

    def leave(self, channel: Channel, session: Any) -> None:
        channel.watching.discard(session)
        self.stopped_typing(channel, session.visitor.id)
        self.changed.fire()

    def unread(self, pid: str, channel: Channel) -> tuple[int, bool]:
        """How many messages someone has not seen in a channel, and whether
        one of those mentions them."""
        seen = self.last_seen.get((pid, channel.name), 0)
        count, mentioned = 0, False
        for message in reversed(channel.messages):
            if message.id <= seen:
                break
            count += message.author.id != pid
            mentioned = mentioned or pid in message.mentions
        return count, mentioned

    def _seen(self, pid: str, channel: Channel) -> None:
        if channel.messages:
            self.last_seen[(pid, channel.name)] = channel.messages[-1].id

    # ---------------------------------------------------------- messages

    def post(self, channel: Channel, author: Person, text: str, at: datetime | None = None) -> None:
        self._ids += 1
        named = {name.lower() for name in MENTION.findall(text)}
        mentions = frozenset(p.id for p in self.people.values() if p.first.lower() in named)
        channel.messages.append(Message(self._ids, author, text, at or datetime.now(UTC), mentions))
        # Whoever has the channel in front of them has read it.
        for session in channel.watching:
            if session.connected:
                self._seen(session.visitor.id, channel)
        self.stopped_typing(channel, author.id)
        self.changed.fire()

    def react(self, channel: Channel, message: Message, pid: str, reaction: str) -> None:
        """Someone's reaction to a message, or its taking back when it was
        there already."""
        who = message.reactions.setdefault(reaction, set())
        if pid in who:
            who.remove(pid)
        else:
            who.add(pid)
        if not who:
            del message.reactions[reaction]
        channel.changed.fire()

    # ------------------------------------------------------------ typing

    def typed(self, channel: Channel, pid: str) -> None:
        new = pid not in channel.typing
        channel.typing[pid] = time.monotonic() + TYPING_FOR
        if new:
            channel.changed.fire()

    def stopped_typing(self, channel: Channel, pid: str) -> None:
        if channel.typing.pop(pid, None) is not None:
            channel.changed.fire()

    def tick(self) -> None:
        """Once a second. Someone who stopped typing without sending is no
        longer typing, and a tab that went away is noticed, since nothing
        says so when it happens."""
        now = time.monotonic()
        for channel in self.channels.values():
            for pid in [p for p, until in channel.typing.items() if until < now]:
                self.stopped_typing(channel, pid)
        online = frozenset(p.id for p in self.online())
        if online != self._online:
            self._online = online
            self.changed.fire()


def seeded() -> Chat:
    """A chat with a few days of a small team's talk in it, so that the
    first person to open it has something to read."""
    chat = Chat()
    for name in ("Mara Lind", "Ito Vance", "Quinn Abara"):
        chat.join(f"seed:{name.split()[0].lower()}", name)
    mara, ito, quinn = chat.people.values()
    now = datetime.now(UTC)

    def said(channel: Channel, who: Person, text: str, days: int, minutes: int) -> None:
        chat.post(channel, who, text, now - timedelta(days=days, minutes=minutes))

    general = chat.add_channel("general", "What the whole team should know")
    said(general, mara, "Morning. The release notes are in review, two comments left.", 2, 190)
    said(general, ito, "I'll take the one about the migration.", 2, 186)
    said(general, quinn, "Staging is on the new build. Shout if anything looks off.", 1, 240)
    said(general, mara, "Looks good from here. The import is **noticeably** faster.", 1, 231)
    said(general, ito, "Lunch at one? The place on the corner has soup again.", 0, 95)
    said(general, quinn, "In. I need ten minutes to finish a review first.", 0, 93)
    chat.react(general, general.messages[3], ito.id, "rocket")
    chat.react(general, general.messages[4], mara.id, "thumbs-up")
    chat.react(general, general.messages[4], quinn.id, "thumbs-up")

    design = chat.add_channel("design", "Screens, words and the things between them")
    said(design, quinn, "New empty states are up. I went with one line and one button.", 1, 400)
    said(
        design,
        mara,
        "Much calmer. Can the button say what it does? `Add a claim`, not `New`.",
        1,
        396,
    )
    said(design, quinn, "Done. Same change on the phone layout.", 1, 380)

    launch = chat.add_channel("launch", "Thursday, 10:00")
    said(launch, ito, "Checklist is at 14 of 17.", 0, 300)
    said(launch, mara, "What are the three?", 0, 298)
    said(launch, ito, "DNS, the status page and a second pair of eyes on pricing.", 0, 297)
    return chat
