---
title: Chat
order: 9
description: A chat with streamed replies, parts, tools and feedback.
---

# Chat

`ui.Chat` is a conversation, with messages, a composer that takes
attachments and commands, and a streamed reply from Python. It needs a
`key`, which names the thread the session keeps for it, and an
`on_message` handler that gets a `mw.ChatTurn` and replies through it.
The chat fills whatever height it is given, so give it one with `cls`
inside a card. `attachments=ui.Accept(...)` says what a person may attach,
of which types, how many and how large. Without it the composer takes no
files. `max_chars` caps a message and `max_messages` the thread, as the
section below says. `tools=[...]` puts your own buttons in the composer.
The section below and the [Custom](/components/custom) page show what goes there.

## A streamed reply

`turn.text`, `turn.files` and `turn.command` are what the user sent. A
command chosen in the composer goes with the message, and is a message
without any text too, for a command that takes none.
Inside `async with turn.reply() as reply`, `reply.text(chunk)` streams
words, `reply.reasoning()` opens a thinking block, `reply.step(label)`
opens a tool step, `reply.status(text)` shows a transient marker, and
`reply.suggestions([...])` offers follow-up chips. The whole turn is a
task, so the stop button cancels it.

```python live
import asyncio


async def answer(s, turn):
    text = turn.text.strip() or "nothing"
    if turn.command == "shout":
        text = text.upper()
    async with turn.reply() as reply:
        async with reply.reasoning() as r:
            await r.text("Deciding what to say about ")
            await asyncio.sleep(0.3)
            await r.text(f"“{text}”.")
        async with reply.step("Looking it up") as step:
            await asyncio.sleep(0.4)
            await step.output({"hits": 3})
        for word in f"You said {text}, and I heard every word of it.".split(" "):
            await reply.text(word + " ")
            await asyncio.sleep(0.05)
        for f in turn.files:
            await reply.file(f)
        await reply.suggestions(["Say it again", "Try /shout"])


ui.Card(
    ui.Chat(
        key="demo",
        welcome="Ask anything. The reply streams back from Python.",
        suggestions=["What can you do?", "Write a haiku"],
        placeholder="Type a message",
        attachments=ui.Accept(accept=[".txt", ".md"], max_files=2),
        commands=[
            ui.Command(id="shout", label="Shout", icon="volume-2", description="Reply in capitals")
        ],
        on_message=answer,
        cls="h-[28rem]",
    ),
    padding=False,
)
```

## The thread

`s.chat(key)` is the thread. `messages` holds what was said, `clear()`
empties it, and `load(messages)` restores a stored conversation. `busy` is
true while a reply is streaming. The session keeps the last `max_messages`
of the Chat, 200 by default, each at most `max_chars` long, 16,000 by
default, so a thread holds a known amount whatever a visitor sends.
`s.drop_chat(key)` forgets a thread altogether, which suits an app that
keeps its threads in a store and only the open one in the session.

```python live
ui.Row(
    ui.Button(
        "Clear the chat above",
        variant="outline",
        icon="trash-2",
        on_click=lambda s, _: s.chat("demo").clear(),
    ),
    ui.Button(
        "Count messages",
        variant="outline",
        on_click=lambda s, _: s.toast(f"{len(s.chat('demo').messages)} messages"),
    ),
    gap=2,
    wrap=True,
)
```

## A floating assistant

`ui.Assistant` is a round button in a corner of the page that becomes a
window, for a chat that should be at hand wherever the reader is. It
takes the chat as its child and gives it the window's height. The reader
can drag the button about, and once it is open, drag the window by its
header and resize it from any edge. The window opens from where the
button is. Minimized, it is the button again, in the place it had, or at
the window's near corner once the window has been moved. The browser
remembers where the button is and how big the window was. `pinned=True`
keeps the button in its corner, where it cannot be dragged and where the
window always folds back to. On a phone the window is a sheet from the
bottom. `open` makes Python the owner of whether it is open, with
`on_toggle` reporting the clicks. Left alone, the browser holds that. The
button below adds one to this page, and it goes away with the page. Its
answers come from the manual's own search, with a link to each section it
finds.

```python live
from pydantic import BaseModel

from millwork.manual import search, sections


class Helper(BaseModel):
    shown: bool = False


async def look_up(s, turn):
    hits = search(sections(), turn.text, limit=3)
    async with turn.reply() as reply:
        if not hits:
            await reply.text("Nothing in the manual matches that.")
            return
        await reply.text("The manual has these sections on it:\n\n")
        for hit in hits:
            sec = hit.section
            await reply.text(f"- [{sec.heading}]({sec.page.slug}#{sec.anchor}) on {sec.page.title}\n")
        await reply.suggestions([h.section.heading for h in hits[:2]])


def example(s):
    st = s.state.helper
    return ui.Stack(
        ui.Button(
            "Take the assistant away" if st.shown else "Add an assistant to this page",
            variant="outline",
            on_click=lambda s, _: setattr(st, "shown", not st.shown),
            cls="self-start",
        ),
        ui.Assistant(
            ui.Chat(key="helper", welcome="Ask about anything in the manual.", placeholder="Ask the manual", on_message=look_up),
            label="Ask the manual",
            title="The manual",
        )
        if st.shown
        else None,
        gap=3,
    )
```

## Parts a reply can carry

| Call | Shows as |
| --- | --- |
| `await reply.text(chunk)` | streamed Markdown |
| `async with reply.reasoning() as r` | a folded thinking block, `r.text(...)` inside |
| `async with reply.step(label) as step` | a tool step with `step.output(...)` |
| `await reply.source(title, url, snippet)` | a source chip |
| `await reply.file(ref)` and `reply.image(ref)` | an attachment, an inline image |
| `await reply.status(text)` | a marker that disappears when the reply ends |
| `await reply.component(component)` | any catalog component inside the message |
| `await reply.suggestions([...])` | follow-up chips |
| `await reply.error(text)` | an error line |

## Reading aids

Four things are off until asked for, since a chat is often clean enough
without them. `avatar` puts a picture beside the assistant's messages.
`names=True` and `timestamps=True` write who said it and when above each
message, on hover, or always on a touch screen, and `assistant_name` sets
the name. `durations=True` shows how long the reply took and how long
each step ran. The times are kept on the messages, so a loaded thread
shows them too.

```python live
import asyncio


async def answer(s, turn):
    async with turn.reply() as reply:
        async with reply.step("Checking the archive") as step:
            await asyncio.sleep(0.6)
            await step.output({"found": 2})
        await reply.text(f"Two notes mention {turn.text.strip() or 'nothing'}.")


ui.Card(
    ui.Chat(
        key="aids",
        welcome="Hover a message for its name and time.",
        avatar="/public/mark.svg",
        assistant_name="Archivist",
        names=True,
        timestamps=True,
        durations=True,
        on_message=answer,
        cls="h-[20rem]",
    ),
    padding=False,
)
```

## Tools in the composer

`tools=[...]` renders components left of Send. A `ui.Button` there is an
ordinary button with a handler in Python, and nothing says it must touch
the conversation. This gear opens a `ui.Dialog` that lives next to the
chat, the dialog changes state, and the next reply reads it. Nothing is
sent and no message appears. A custom component in the slot gets a `chat`
prop to upload and send with. The [Custom](/components/custom) page builds a voice note
button on it.

```python live
from pydantic import BaseModel


class Settings(BaseModel):
    open: bool = False
    tone: str = "plain"
    sign: bool = False


async def answer(s, turn):
    st = s.state.settings
    async with turn.reply() as reply:
        text = turn.text.upper() if st.tone == "shout" else turn.text
        await reply.text(f"You said: {text}" + (" (sent from the manual)" if st.sign else ""))


def example(s):
    st = s.state.settings

    def opened(value):
        def handler(s, _):
            st.open = value

        return handler

    return ui.Stack(
        ui.Card(
            ui.Chat(
                key="settings-demo",
                welcome="The gear in the composer opens the settings.",
                tools=[
                    ui.Button(
                        key="gear",
                        icon="settings",
                        variant="ghost",
                        size="sm",
                        tooltip="Settings",
                        on_click=opened(True),
                    )
                ],
                on_message=answer,
                cls="h-[20rem]",
            ),
            padding=False,
        ),
        ui.Dialog(
            ui.Field(
                ui.Select(
                    key="tone",
                    options=["plain", "shout"],
                    value=st.tone,
                    on_change=lambda s, v: setattr(st, "tone", v or "plain"),
                ),
                label="Tone",
            ),
            ui.Switch(
                key="sign",
                label="Sign the replies",
                checked=st.sign,
                on_change=lambda s, v: setattr(st, "sign", bool(v)),
            ),
            key="settings",
            open=st.open,
            title="Chat settings",
            on_close=opened(False),
            footer=ui.Button("Done", on_click=opened(False)),
        ),
    )
```

## Under a message

Hover an answer and a row of buttons appears. There is copy, thumbs up
and down when the chat has an `on_feedback` handler, regenerate on the
latest answer, and any `actions` of the app's own. A thumbs down asks for
a comment. The choice stays on the message, so it is there after a
reload, and millwork keeps nothing else. `on_feedback` gets the message,
the value and the comment, and the app stores them where it wants. A user
message has an edit button. The edited message is answered again and
whatever followed it goes. `regenerate=False`, `edit=False` and
`copyable=False` switch each of these off.

```python live
from pydantic import BaseModel


class Feedback(BaseModel):
    notes: list[str] = []


async def echo(s, turn):
    async with turn.reply() as reply:
        await reply.text(f"You said: {turn.text}")


async def rated(s, message, value, comment):
    what = "cleared" if value is None else value
    note = f"{what}: {message.text[:30]}" + (f" ({comment})" if comment else "")
    s.state.feedback.notes.append(note)


async def act(s, message, action):
    s.toast(f"{action}: {message.text}")


def example(s):
    notes = s.state.feedback.notes
    return ui.Stack(
        ui.Card(
            ui.Chat(
                key="rated",
                welcome="Say something, then rate the answer or edit your message.",
                on_message=echo,
                on_feedback=rated,
                on_action=act,
                actions=[ui.Action(id="save", label="Save", icon="bookmark")],
                cls="h-[22rem]",
            ),
            padding=False,
        ),
        ui.Text("Feedback so far: " + ("; ".join(notes) or "none")),
    )
```
