"""An analyst for a table of orders. Ask a question in the chat, and the
answer comes with the query it ran. A chart or a table it wants to show
is pinned to the board beside the conversation, and it can point at one.
A CSV file attached to a message becomes one more table to ask about.

    uv run millwork run examples/analyst/app.py

That runs on a script that knows a few questions. With a key it is a
model that answers:

    ANTHROPIC_API_KEY=... uv run --with anthropic millwork run examples/analyst/app.py

The data is in ``dataset.py`` and the analyst in ``analyst.py``. This
file is the page, with the board and the chat.
"""

from __future__ import annotations

import asyncio
import sqlite3
from functools import partial
from typing import Any

import analyst
import dataset
from analyst import Pinned
from pydantic import BaseModel

import millwork as mw
from millwork import ui


class State(BaseModel):
    # What the analyst pinned to the board, and how many cards it has made
    # in all, which gives each one an id no other had.
    cards: list[Pinned] = []
    made: int = 0
    # The conversation as the model sees it, when there is a model.
    history: list[dict[str, Any]] = []


# An answer is drawn as Markdown, and a file can be written to talk the
# model into a picture whose address carries what it read. So this app's
# pages take pictures, media and frames from the app alone, where the
# policy millwork sends by default takes them from anywhere.
POLICY = (
    "default-src 'self'; script-src {scripts}; style-src 'self' 'unsafe-inline'{styles}; "
    "img-src 'self' data: blob:; font-src 'self' data:{fonts}; connect-src 'self'; "
    "worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'self'"
)

app = mw.App("Analyst", state=State, csp=POLICY)

# Each session's database. A connection is no state a page can draw from,
# so it is kept here by the session's id, from when the page is opened
# until it is closed.
DATA: dict[str, sqlite3.Connection] = {}


# -------------------------------------------------------------- handlers


async def answer(s: mw.Session[State], turn: mw.ChatTurn) -> None:
    db = DATA[s.id]
    async with turn.reply() as reply:
        # A file that comes with the message is a table before it is answered.
        added = []
        for file in turn.files:
            try:
                text = file.path.read_text(encoding="utf-8", errors="replace")
                table, _ = await asyncio.to_thread(dataset.load_csv, db, file.name, text)
            except dataset.Refused as error:
                await reply.error(f"{file.name} was not added. {error}")
                return
            added.append(table)
        think = analyst.with_model if analyst.CLIENT else analyst.scripted
        await think(s, db, turn, reply, added)


def start_over(s: mw.Session[State], _: object) -> None:
    s.state.cards, s.state.history = [], []
    s.chat("analyst").clear()


def take_down(s: mw.Session[State], _: object, *, card: str) -> None:
    s.state.cards = [c for c in s.state.cards if c.id != card]


# ------------------------------------------------------------------ page


@app.page("/", title="Analyst")
def desk(s: mw.Session[State]) -> ui.Component:
    tables = dataset.tables(DATA[s.id])
    return ui.Page(
        # The board and the chat side by side, as high as the window. On a
        # narrow screen the board lies above the chat and takes less of it.
        ui.Stack(
            board(s),
            ui.Chat(
                welcome="Ask about the orders. What I look up is shown with the answer."
                if analyst.CLIENT
                else "Ask about the orders. I am running on a script that knows a few questions.",
                suggestions=analyst.QUESTIONS,
                placeholder="Ask about the data, or attach a CSV file",
                attachments=ui.Accept(accept=[".csv"], max_files=1, max_size_mb=2),
                on_message=answer,
                # The model's history is kept beside the chat's, and a message
                # that was edited or answered again would not be in it.
                edit=False,
                regenerate=False,
                cls="min-w-0 md:border-l",
                key="analyst",
            ),
            fill=True,
            gap=0,
            cls="md:flex-row",
        ),
        header=ui.Header(
            ui.Row(
                *(ui.Badge(name, icon="table", tone="muted", key=name) for name in tables),
                gap=1,
                cls="hidden md:flex",
            ),
            ui.Button(
                "Start over",
                icon="rotate-ccw",
                variant="ghost",
                # Not in the middle of an answer, which would go on writing.
                disabled=s.chat("analyst").busy,
                on_click=start_over,
                key="over",
            ),
            title="Analyst",
        ),
        padding=False,
    )


@desk.connect
def open_data(s: mw.Session[State]) -> None:
    DATA[s.id] = dataset.fresh()


@desk.close
def close_data(s: mw.Session[State]) -> None:
    DATA.pop(s.id).close()


def board(s: mw.Session[State]) -> ui.Component:
    """What the analyst pinned, the newest first."""
    # Beside the chat it has the larger part of the width. Above it, on a
    # narrow screen, it has under half of the height, and none while empty.
    place = "min-h-0 md:w-[58%] md:shrink-0"
    if not s.state.cards:
        return ui.Stack(
            ui.Empty(
                title="Nothing pinned yet",
                description="A chart or a table the analyst shows you stays here.",
                icon="bar-chart-3",
            ),
            justify="center",
            cls=f"{place} max-md:hidden",
            key="board",
        )
    return ui.ScrollArea(
        ui.Stack(*(pinned(card) for card in reversed(s.state.cards)), gap=4, cls="p-4"),
        cls=f"{place} max-md:max-h-[45%] max-md:border-b",
        key="board",
    )


def pinned(card: Pinned) -> ui.Component:
    if card.kind == "table":
        shown: ui.Component = ui.Table(rows=card.rows, height=260, summary=False)
    else:
        chart = {"bar": ui.BarChart, "line": ui.LineChart, "area": ui.AreaChart}[card.kind]
        # The chart has a name of its own, for the analyst to point into it.
        shown = chart(
            card.rows, x=card.x, y=card.y, legend=False, height=220, key=f"{card.id}-chart"
        )
    return ui.Card(
        shown,
        title=card.title,
        footer=ui.Row(
            ui.Code(card.sql, cls="min-w-0 truncate text-xs"),
            ui.Button(
                icon="x",
                variant="ghost",
                size="sm",
                tooltip="Take it down",
                on_click=partial(take_down, card=card.id),
            ),
            justify="between",
            cls="w-full",
        ),
        key=card.id,
    )
