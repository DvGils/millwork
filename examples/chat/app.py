"""A team chat. Channels with unread counts, messages that arrive as they
are sent, who is typing and who is here right now.

    uv run millwork run examples/chat/app.py

A second browser, or a private window, is a second person.

What everyone shares is in ``chat.py``, outside every session. This file
is the pages that draw it and the handlers that change it.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from functools import partial

from chat import MENTION, Channel, Message, Person, seeded
from pydantic import BaseModel, Field

import millwork as mw
from millwork import ui

CHAT = seeded()

# A channel shows its latest messages. A page is drawn again at every
# change, and what is drawn should not grow with the years.
SHOWN = 200

# What someone can say of a message without a word, by the icon it shows.
REACTIONS = {"thumbs-up": "Agree", "heart": "Love it", "eye": "Seen", "rocket": "Ship it"}

# How long a message may be. The field stops there in a browser, and the
# session takes no longer text for it from anything else.
LONGEST = 2000


class State(BaseModel):
    # What is typed and not yet sent, by channel, so that it is still there
    # when its channel is opened again.
    drafts: dict[str, str] = {}
    # The messages that were new to this person when they opened the
    # channel, as the ids they come after and go up to.
    new: tuple[int, int] = (0, 0)
    creating: bool = False


class Join(BaseModel):
    name: str = Field(min_length=1, max_length=24, title="Your name")


class NewChannel(BaseModel):
    name: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]{1,19}$",
        description="2 to 20 lowercase letters, digits and dashes.",
    )
    topic: str = Field("", max_length=80)


# A browser is a person here. Nobody signs in, and a name is kept under
# the id of the browser that gave it.
app = mw.App("Commons", state=State, identify_visitors=True)


@app.on_startup
def start_clock() -> None:
    app.spawn(clock(), "the chat's clock")


async def clock() -> None:
    while True:
        await asyncio.sleep(1)
        CHAT.tick()


# -------------------------------------------------------------- handlers


def join(s: mw.Session[State], who: Join) -> None:
    name = " ".join(who.name.split())
    if not name:
        raise ui.FormIssues([("/name", "A name has a letter in it.")])
    CHAT.join(s.visitor.id, name)


def typed(s: mw.Session[State], text: str) -> None:
    here = CHAT.channels[s.params["name"]]
    s.state.drafts[here.name] = text
    if text:
        CHAT.typed(here, s.visitor.id)
    else:
        CHAT.stopped_typing(here, s.visitor.id)


def say(s: mw.Session[State], text: str) -> None:
    # The field empties itself and says so to ``typed``, which drops the draft.
    text = text.strip()
    if text:
        CHAT.post(CHAT.channels[s.params["name"]], CHAT.people[s.visitor.id], text)


def react(s: mw.Session[State], chosen: object, *, to: Message, reaction: str = "") -> None:
    """A reaction to a message, the one a pill stands for or the one chosen
    from the menu."""
    CHAT.react(CHAT.channels[s.params["name"]], to, s.visitor.id, reaction or str(chosen))


def new_channel(s: mw.Session[State], _: object) -> None:
    s.state.creating = True


def never_mind(s: mw.Session[State], _: object) -> None:
    s.state.creating = False


def create(s: mw.Session[State], new: NewChannel) -> None:
    if new.name in CHAT.channels:
        raise ui.FormIssues([("/name", f"There is a #{new.name} already.")])
    CHAT.add_channel(new.name, new.topic.strip())
    s.state.creating = False
    s.navigate(f"/c/{new.name}")


# ----------------------------------------------------------------- pages


@app.page("/")
def front(s: mw.Session[State]) -> ui.Component:
    return ui.Page()


@front.connect
def to_general(s: mw.Session[State]) -> None:
    s.navigate("/c/general")


@app.page("/c/{name}")
def channel(s: mw.Session[State]) -> ui.Component:
    here = CHAT.channels[s.params["name"]]
    me = CHAT.people.get(s.visitor.id)
    if me is None:
        return welcome(here)
    return ui.Page(
        sidebar(here, me),
        # A frame as high as the window. The messages scroll, and the field
        # under them stays where it is.
        ui.Stack(messages(s, here, me), composer(s, here), fill=True, gap=0),
        ui.Dialog(
            ui.Form(NewChannel, submit="Create", on_submit=create, key="new-channel"),
            open=s.state.creating,
            title="New channel",
            on_close=never_mind,
        ),
        title=f"#{here.name}",
        header=ui.Header(
            # A phone has room for the channel's name and not for its topic.
            ui.Text(here.topic, variant="muted", truncate=True, cls="hidden md:block"),
            title=f"#{here.name}",
        ),
        padding=False,
        gap=0,
    )


@channel.connect
def enter(s: mw.Session[State], name: str) -> None:
    here = CHAT.channels.get(name)
    if here is None:
        raise mw.NotFound()
    # The sidebar is drawn from what everyone shares. Who is typing and
    # the reactions are this channel's alone.
    s.follow(CHAT.changed)
    s.follow(here.changed)
    seen = CHAT.enter(here, s)
    last = here.messages[-1].id if here.messages else 0
    if s.visitor.id in CHAT.people:
        s.state.new = (seen, last)
    else:
        s.state.new = (last, last)
        s.focus("join")


@channel.close
def leave(s: mw.Session[State]) -> None:
    CHAT.leave(CHAT.channels[s.params["name"]], s)


def welcome(here: Channel) -> ui.Component:
    return ui.Page(
        ui.Stack(
            ui.Card(
                ui.Text(f"Pick a name to join #{here.name}.", variant="muted"),
                ui.Form(Join, submit="Join", on_submit=join, key="join"),
                title="Commons",
                cls="w-full max-w-sm",
            ),
            fill=True,
            align="center",
            justify="center",
        ),
        title="Commons",
    )


def sidebar(here: Channel, me: Person) -> ui.Component:
    channels = []
    for c in CHAT.channels.values():
        # The channel in front of someone has nothing they have not read.
        unread, mentioned = (0, False) if c is here else CHAT.unread(me.id, c)
        channels.append(
            ui.Link(
                label=c.name,
                href=f"/c/{c.name}",
                icon="hash",
                active=c is here,
                # A count, with an @ in front when one of them is for this person.
                badge=f"{'@' if mentioned else ''}{unread}" if unread else None,
                cls="font-semibold" if unread else None,
                key=c.name,
            )
        )
    # Whoever has a tab open, and after them the rest of the team, dimmed.
    online = CHAT.online()
    away = sorted((p for p in CHAT.people.values() if p not in online), key=lambda p: p.name)
    people = [
        ui.Row(
            avatar(p, small=True),
            ui.Text(f"{p.name} (you)" if p == me else p.name, truncate=True),
            None if p in online else ui.Text("away", cls="sr-only"),
            gap=2,
            cls="px-2 py-1" if p in online else "px-2 py-1 opacity-50",
            key=f"{'here' if p in online else 'away'}-{p.id}",
        )
        for p in online + away
    ]
    return ui.Sidebar(
        ui.SidebarGroup(
            *channels,
            ui.Button(
                "New channel",
                icon="plus",
                variant="ghost",
                size="sm",
                on_click=new_channel,
                cls="justify-start",
                key="new",
            ),
            label="Channels",
            collapsible=False,
        ),
        ui.SidebarGroup(*people, label="People", collapsible=False),
        title="Commons",
    )


def avatar(p: Person, small: bool = False) -> ui.Component:
    size = "size-6 text-[10px]" if small else "size-9 text-xs"
    return ui.Stack(
        ui.Text(p.initials, cls="font-semibold text-white"),
        align="center",
        justify="center",
        cls=f"{size} shrink-0 rounded-full bg-chart-{p.color}",
    )


def messages(s: mw.Session[State], here: Channel, me: Person) -> ui.Component:
    typists = [CHAT.people[pid] for pid in here.typists(but=me.id)]
    if not here.messages and not typists:
        return ui.Stack(
            ui.Empty(
                title=f"Nothing in #{here.name} yet",
                description="Say the first thing.",
                icon="message-square",
            ),
            fill=True,
            justify="center",
        )
    today = datetime.now(s.timezone).date()
    after, until = s.state.new
    rows: list[ui.Component] = []
    if len(here.messages) > SHOWN:
        rows.append(ui.Text(f"The latest {SHOWN} messages.", variant="caption", align="center"))
    last: Message | None = None
    # What is new may begin before what is shown, and then no line says where.
    marked = len(here.messages) > SHOWN and here.messages[-SHOWN - 1].id > after
    for m in here.messages[-SHOWN:]:
        # The viewer's clock, not the server's.
        at = m.at.astimezone(s.timezone)
        if last is None or last.at.astimezone(s.timezone).date() != at.date():
            rows.append(ui.Separator(label=day(at.date(), today), key=f"day-{m.id}", cls="py-3"))
            last = None
        new = after < m.id <= until and m.author != me
        if new and not marked:
            # A line above the first thing said since they were last here.
            rows.append(
                ui.Separator(label="New", key="new-line", cls="py-2 font-medium text-primary")
            )
            marked, last = True, None
        # A few lines from one person in a row read as one.
        follows = (
            last is not None and last.author == m.author and m.at - last.at < timedelta(minutes=5)
        )
        rows.append(message(m, at, me, follows, new))
        last = m
    rows += [typing(p) for p in typists]
    return ui.ScrollArea(
        ui.Stack(*rows, gap=0, cls="px-6 py-4"),
        fill=True,
        stick_to_end=True,
        # One for each channel, so that a channel that is opened starts at its end.
        key=f"messages-{here.name}",
    )


def message(m: Message, at: datetime, me: Person, follows: bool, new: bool) -> ui.Component:
    # The name of someone it mentions stands out in the text.
    names = {CHAT.people[pid].first.lower() for pid in m.mentions}
    text = MENTION.sub(lambda hit: f"**{hit[0]}**" if hit[1].lower() in names else hit[0], m.text)
    said: list[ui.Component] = [ui.Markdown(text, tight=True)]
    if not follows:
        byline = ui.Row(
            ui.Text(m.author.name, variant="label"),
            ui.Text(f"{at:%H:%M}", variant="caption"),
            gap=2,
            align="baseline",
        )
        said.insert(0, byline)
    if m.reactions:
        said.append(reactions(m, me))
    # What mentions the reader stands on a tint, and so does what is new to
    # them, until they leave the channel.
    mine = me.id in m.mentions and m.author != me
    tint = "bg-primary/10" if mine else "bg-accent/60" if new else ""
    return ui.Row(
        ui.Stack(cls="w-9 shrink-0") if follows else avatar(m.author),
        ui.Stack(*said, gap=0, grow=True, cls="min-w-0"),
        react_menu(m),
        gap=3,
        align="start",
        cls=f"group -mx-2 rounded-md px-2 {'py-0.5' if follows else 'mt-2 py-1'} {tint}",
        key=f"m{m.id}",
    )


def reactions(m: Message, me: Person) -> ui.Component:
    """A pill for each reaction a message has, with how many gave it. A
    press adds this person's, or takes it back."""
    return ui.Row(
        *(
            ui.Button(
                str(len(who)),
                icon=reaction,
                # Filled in when it is this person's own.
                variant="secondary" if me.id in who else "outline",
                size="sm",
                tooltip=REACTIONS[reaction],
                on_click=partial(react, to=m, reaction=reaction),
                cls="h-6 rounded-full px-2 text-xs",
                key=reaction,
            )
            for reaction, who in m.reactions.items()
        ),
        gap=1,
        cls="pt-1",
    )


def react_menu(m: Message) -> ui.Component:
    """The button at a message's end that opens the reactions. It shows
    under the pointer and at the keyboard, and always on a touch screen."""
    return ui.DropdownMenu(
        trigger=ui.Button(
            icon="thumbs-up",
            variant="ghost",
            size="sm",
            tooltip="React",
            cls="size-7 opacity-0 group-hover:opacity-60 focus-visible:opacity-100"
            " aria-expanded:opacity-100 pointer-coarse:opacity-40",
        ),
        items=[ui.MenuItem(id=r, label=label, icon=r) for r, label in REACTIONS.items()],
        align="end",
        on_select=partial(react, to=m),
    )


def typing(p: Person) -> ui.Component:
    """Where someone's next message will be, three dots while they write it."""
    dot = "size-1.5 rounded-full bg-muted-foreground animate-bounce motion-reduce:animate-none"
    return ui.Row(
        avatar(p),
        ui.Row(*(ui.Stack(cls=f"{dot} [animation-delay:{i * 150}ms]") for i in range(3)), gap=1),
        # The same in words, for a screen reader.
        ui.Text(f"{p.name} is typing", cls="sr-only"),
        gap=3,
        cls="mt-2 py-1",
        key=f"typing-{p.id}",
    )


def day(of: date, today: date) -> str:
    if of == today:
        return "Today"
    if of == today - timedelta(days=1):
        return "Yesterday"
    return f"{of:%A} {of.day} {of:%B}"


def composer(s: mw.Session[State], here: Channel) -> ui.Component:
    return ui.Stack(
        ui.Input(
            default=s.state.drafts.get(here.name, ""),
            placeholder=f"Message #{here.name}",
            autofocus=True,
            clear_on_submit=True,
            max_length=LONGEST,
            # Every keystroke is told, where a field waits for a pause by
            # default, so that the others see the typing at its first letter.
            debounce_ms=0,
            on_change=typed,
            on_submit=say,
            # One for each channel, each with a draft of its own.
            key=f"say-{here.name}",
        ),
        cls="px-6 pt-2 pb-5",
    )
