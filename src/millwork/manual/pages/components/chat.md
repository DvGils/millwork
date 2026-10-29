---
title: Chat
order: 9
---

# Chat

`ui.Chat` is a conversation: messages, a composer with attachments and
commands, and a streamed reply from Python. It needs a `key`, which names
the thread the session keeps for it, and an `on_message` handler that gets a
`mw.ChatTurn` and replies through it. The chat fills whatever height it is
given, so give it one with `cls` inside a card. `attachments=ui.Accept(...)`
says what a person may attach, of which types, how many and how large;
without it the composer takes no files. `max_chars` caps a message.

## A streamed reply

`turn.text`, `turn.files` and `turn.command` are what the user sent. Inside
`async with turn.reply() as reply`, `reply.text(chunk)` streams words,
`reply.reasoning()` opens a thinking block, `reply.step(label)` a tool
step, `reply.status(text)` a transient marker, and `reply.suggestions([...])`
follow-up chips. The whole turn is a task: the stop button cancels it.

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

`s.chat(key)` is the thread: `messages` holds what was said, `clear()`
empties it, and `load(messages)` restores a stored conversation. `busy` is
true while a reply is streaming.

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
| `await reply.component(component)` | any catalogue component inside the message |
| `await reply.suggestions([...])` | follow-up chips |
| `await reply.error(text)` | an error line |

## Under a message

Hover an answer and a row of buttons appears: copy, thumbs up and down
when the chat has an `on_feedback` handler, regenerate on the latest
answer, and any `actions` of the app's own. A thumbs down asks for a
comment. The choice stays on the message, so it is there after a reload,
and millwork keeps nothing else: `on_feedback` gets the message, the value
and the comment, and the app stores them where it wants. A user message
has an edit button; the edited message is answered again and what followed
it goes. `regenerate=False`, `edit=False` and `copyable=False` switch each
off.

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
    state(Feedback).notes.append(note)


async def act(s, message, action):
    s.toast(f"{action}: {message.text}")


def example(s):
    notes = state(Feedback).notes
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
