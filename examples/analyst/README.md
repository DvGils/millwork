# Analyst

![Three questions about a shop's orders. Each answer comes with the query that was run, a chart of it is pinned to a board beside the chat, and for the third the analyst marks the month it is talking about on the chart. Then a CSV file is attached to a message and asked about.](analyst.gif)

A chat that answers questions about a table of orders. The answer shows
the query it ran, a chart or a table it wants you to see is pinned to
the board beside the conversation, and it points at a card when its
answer is about one. A CSV file attached to a message becomes one more
table to ask about.

```
uv run millwork run examples/analyst/app.py
```

That runs on a script that knows a few questions, so it needs nothing
else, and it is what the picture shows. With a key for the Anthropic API
a model answers, and any question about the data is a fair one:

```
ANTHROPIC_API_KEY=... uv run --with anthropic millwork run examples/analyst/app.py
```

The model is Claude Opus 5.5, or the one `ANALYST_MODEL` names. Each
question is a few requests to it, which the key's account pays for.

## What it shows

| In the app | Made with | In the manual |
|---|---|---|
| An answer that streams, with the model's reasoning folded above it | `turn.reply()` with `reply.text` and `reply.reasoning` | [A streamed reply](https://millwork-ui.com/components/chat#a-streamed-reply) |
| The query that was run, as a step of the answer | `reply.tool(name, input)` and its `output`, which `reply.step` is the plain form of | [Parts a reply can carry](https://millwork-ui.com/components/chat#parts-a-reply-can-carry) |
| A chart that appears while the answer is still coming | A tool that changes the session's state and calls `s.refresh()`, since a handler's own render comes when it ends | [A render from outside a handler](https://millwork-ui.com/state/accessing-the-session#a-render-from-outside-a-handler) |
| The analyst knows what is on the board | `s.outline(within="board", as_text=True)`, the page as data | [The page as data](https://millwork-ui.com/state/accessing-the-session#the-page-as-data) |
| A mark on the month the answer is about | `s.highlight("card-2-chart/2026-03")`, a chart's name and a value along its axis | [Highlight](https://millwork-ui.com/components/feedback#highlight) |
| A CSV file that becomes a table | `ui.Chat(attachments=ui.Accept(...))` and the turn's `files` | [Chat](https://millwork-ui.com/components/chat) |
| The board beside the chat, as high as the window | `ui.Stack(fill=True)` | [A page that fills the window](https://millwork-ui.com/components/layout#a-page-that-fills-the-window) |
| A dark look by default | `public/theme.json` with `"mode": "dark"` | [Theming](https://millwork-ui.com/theming) |
| Start over is off while an answer streams | `s.chat(key).busy` | [The thread](https://millwork-ui.com/components/chat#the-thread) |
| Pictures in an answer come from the app alone | `App(csp=...)` | [The page's security headers](https://millwork-ui.com/running/hosting-checklist#the-page-s-security-headers) |
| Tests of the model's loop without a model | A stand-in for the client, given to the app by the test | [Testing](https://millwork-ui.com/testing) |

## The files

- `app.py` is the page, with the board and the chat, and what a person
  can do to it besides asking.
- `analyst.py` is the analyst. It has the three tools, the loop that
  lets a model use them, and the script that stands in for the model.
- `dataset.py` is the data. Each session has a SQLite database of its
  own, in memory, with the orders in it and the tables that were added.
- `samples/returns.csv` is a file to attach.
- `public/theme.json` is the look. The font is Space Grotesk, under the
  SIL Open Font License that lies beside it.
- `test_analyst.py` drives the app without a browser and without a model.
- `record.py` makes the picture above.

## The tools, and who uses them

The analyst can do three things. `query` runs a SELECT and gives the
rows back, `show` pins a chart or a table of a query to the board, and
`point_at` puts a frame around a card or around one value of a chart on
it. Each is a Pydantic model of what it takes and a function of the same
name that does it. The model's docstring and fields are what the
language model reads, and the same model checks what the language model
sends before the function runs.
What does not fit, or a tool that fails, goes back to it in words, and
it tries again.

A tool changes the page the way a handler does, by changing the
session's state. That is why the script and the model can share them.
The script calls the same three tools with what it knows to ask, so
without a key the page behaves as it does with one.

## The model's side of the conversation

The chat keeps what the person sees. What the model sees is kept beside
it, in the session's state, as the list of messages the API takes. An
answer is kept as it came, the model's reasoning and its tool calls
included. The answer and the results of its calls are added together
once every tool has run, so a turn that is stopped in the middle, or a
tool that fails, never leaves a call without its result, which the API
would refuse from then on. An answer that was cut off or declined is not
kept at all. Nothing in the list is changed afterward, which the newer
models hold a conversation to.

Each question goes to the model with the tables there are and with the
board as `s.outline` gives it, so "what am I looking at?" has an answer.

The request asks for a summary of the model's reasoning, which the chat
shows folded above the answer. It reads what was sent before from the
cache. And it names a fallback, so a request the model declines is
answered by another model instead of ending the turn. When that happens
in the middle of an answer, the first model's reasoning and tool calls
are left out of what goes back, as the API asks.

## What a query may do

The SQL comes from a language model or from a script, about data that
may have come from a file a person added. None of it is trusted. A query
is one statement and it may only read. It is stopped when it runs longer
than a second, it gives back a few hundred rows at most, and no value in
it is longer than a hundred thousand characters, so it cannot ask for
more memory than the server has. It runs in a thread, so a slow one
holds up nobody else's page. A session's database is its own, so a table
one person adds is not in anyone else's.

Rows that come back from a file are read by the model as part of the
conversation, and a file can be written to steer it. The system prompt
says rows are data and not instructions, which lowers the odds and is
no guarantee. What bounds the damage is what the model can do. Its three
tools read this session's data and change this session's board, and
nothing else. Its words are the other way out. The chat draws Markdown,
and a picture in an answer would be fetched from wherever its address
points, with what the model read in that address. So the app sends a
content security policy of its own, `App(csp=...)`, under which a page
takes pictures from the app alone. A link in an answer still goes where
it points when a person clicks it.

## What it leaves out

Nothing is kept when the session ends. The board holds the newest twelve
cards, and the conversation with the model grows until Start over. There
is no limit on how many questions a visitor asks, so behind a public
address a key would pay for all of them. An app for many people keeps its data in a real database
with a role that can only read, counts what each person spends, and
keeps the conversation somewhere that outlives the tab.
