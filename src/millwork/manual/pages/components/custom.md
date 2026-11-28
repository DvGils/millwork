---
title: Custom components
order: 10
description: Your own React component in a .jsx file, driven from Python.
---

# Custom components
<!-- keywords: react, javascript, jsx, typescript, extend, plugin, own component -->

When the catalog has no component for something, an app writes one in
JSX. The file lives in the app's `components/` folder, gets compiled in
the browser, and composes the same primitives the catalog is built
from. Python reaches it by name with `ui.Custom`.

Compiling takes a moment, so a custom component mounts a little after
the rest of the page shows. One that listens on `window`, for keys say,
hears nothing until then.

## The contract

A component is a default export that receives `props` from Python, `emit`
to send an event back, `request` to ask one of its handlers and get the
answer as a promise, `fileUrl` to show a session file, and `children`
rendered from Python. The address `fileUrl` gives carries the file's type
when it is a picture, a PDF, plain text, Markdown, sound or film. Any
other file is plain bytes there, HTML among them, since its address
would be a page of the app.

```jsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sparkles } from "lucide-react";

export default function Hello({ props, emit, children }) {
  const [clicks, setClicks] = useState(0);
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-dashed border-primary/40 p-4">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-primary" />
        <span className="font-medium">Hello, {props.who}.</span>
        <Badge variant="secondary">server says {props.count}</Badge>
        <Badge variant="outline">local clicks {clicks}</Badge>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => setClicks((c) => c + 1)}>Local +1</Button>
        <Button size="sm" onClick={() => emit("wave", clicks)}>Wave to the server</Button>
      </div>
      {children}
    </div>
  );
}
```

`children` is an array, with one element for each child Python gave the
component, in the order they were given. A component that lays its
children out one by one, such as a list that can be dragged, wraps each. An
element's `key` is the child's id on the page, which ends in the `key`
it has in Python, `root/days/monday` for `key="monday"`.

```jsx
import { Children } from "react";

export default function Rows({ children }) {
  return (
    <ol className="flex flex-col gap-2">
      {Children.map(children, (child) => (
        <li className="rounded-lg border p-2">{child}</li>
      ))}
    </ol>
  );
}
```

## Using it from Python

`ui.Custom(name, props=, events=)` renders `components/<name>.jsx`. Events
the component emits reach the handler named in `events`, or `on_event` as
`(name, payload)`. A payload is whatever the tab sent, so a handler
checks it before using it.

```python live
from pydantic import BaseModel


class Waves(BaseModel):
    count: int = 0


def example(s):
    st = s.state.waves

    def waved(s, clicks):
        st.count += 1
        s.toast(f"Waved after {clicks} local clicks.")

    return ui.Custom(
        "Hello",
        ui.Text("Children from Python render inside the custom component.", variant="muted"),
        props={"who": "Ada", "count": st.count},
        events={"wave": waved},
        key="hello",
    )
```

A custom component can import React, the lucide icons the bundle
carries, every `@/components/ui/*` module the catalog uses, and from
`millwork` the pieces under
[Rows that are dragged](#rows-that-are-dragged-and-text-that-is-typed-over). Those
icons are the ones in `mw.ICONS`, by lucide's own names, so `trash-2`
there is `Trash2` here, and the name lucide gives one today imports it
too. A component that asks for another one is not
drawn, and says which icon it asked for. An icon of your own is an SVG
file under `public/`. Tailwind classes work, and
ones the bundle never saw are compiled in the browser on first use.

A test does not run the JSX. It sees the component as a node whose
props are the ones it was given in `props=`, with `on_<name>: True` for
each of its events. So for the one above `page.find("hello").props["who"]`
is `"Ada"`, and there is no `props["props"]`.
`await page.event("hello", "wave", 3)` sends one of its events by name.
[Testing](/testing) has more.

## Asking a handler
<!-- keywords: request, promise, fetch, rpc, load on demand, lookup -->

`emit` says that something happened, and the page is drawn again when
its handler is done. It gives a promise that is over at that moment,
for a component that shows something of its own until then. The promise
is also over when no handler took the event, when the session is
another one, and after half a minute without a word. It never fails and
carries nothing, so what the page gave the component is how it knows
whether the change was taken. `request(name, payload)` asks for something the
component wants to know, such as the rows behind a preview or whether a
name is free. It reaches the handler that `events` has under that name
and gives a promise of what the handler returns.

```jsx
const rows = await request("preview", { table: "orders" });
```

```python
ui.Custom("Preview", key="orders", events={"preview": lambda s, asked: load_rows(asked["table"])})
```

The answer goes to the component as the handler gave it. That is a
dict, a list, a string, a number or `None`, and a model, a dataclass, a
date or a `Decimal` as the JSON it makes, the last two as text. The page
is not drawn for a request and other handlers do not wait for it, so the
handler reads and leaves state alone. A handler that raises rejects the
promise. So does an answer that cannot be made into JSON, and a name
that `events` does not have. In a test,
`await page.request("orders", "preview", {"table": "orders"})` gives the
answer.

## Rows that are dragged and text that is typed over
<!-- keywords: reorder, drag and drop, sortable rows, grip, inline edit, editable cell, rename in place, useRowDrag, Editable, RowGrip -->

A component that draws its own list or table borrows two things from
`millwork`. `useRowDrag` lets its rows be dragged into another order by
a grip, or moved a place at a time with Alt and an arrow key on the
grip. `Editable` is a text that becomes a field when it is pressed.
Enter or leaving the field says the new text, and Escape leaves it as
it was.

Both show what was done at once and leave the last word to the page.
A callback that returns the promise `emit` gives, as the two below do,
has its row or its text set back the moment a handler did not take the
change. Try an empty title. A callback that returns nothing is waited
for until the page gives another value, or four seconds.

```python live
from pydantic import BaseModel


class Song(BaseModel):
    key: str
    title: str
    length: str


class Setlist(BaseModel):
    songs: list[Song] = [
        Song(key="a", title="Opening theme", length="3:10"),
        Song(key="b", title="Harbor lights", length="4:25"),
        Song(key="c", title="Slow one", length="5:02"),
        Song(key="d", title="The loud one", length="2:48"),
        Song(key="e", title="Encore", length="6:30"),
    ]


def example(s):
    songs = s.state.setlist.songs

    def move(s, asked):
        at = next((i for i, song in enumerate(songs) if song.key == asked.get("key")), None)
        to = asked.get("to")
        if at is not None and isinstance(to, int) and 0 <= to < len(songs):
            songs.insert(to, songs.pop(at))

    def rename(s, asked):
        title = str(asked.get("title", "")).strip()[:60]
        song = next((song for song in songs if song.key == asked.get("key")), None)
        if song is None or not title:
            s.toast("A song has a title.", tone="warning")
            return
        song.title = title

    return ui.Custom(
        "Setlist",
        props={"songs": [song.model_dump() for song in songs]},
        events={"move": move, "rename": rename},
        key="setlist",
    )
```

```jsx
import { memo } from "react";
import { useRowDrag, RowGrip, Editable } from "millwork";

const Song = memo(function Song({ song, row, grip, emit }) {
  return (
    <li {...row} className="flex items-center gap-2 rounded-lg border bg-card px-2 py-1.5 text-sm">
      <RowGrip {...grip} label={`Move ${song.title}`} />
      <div className="min-w-0 grow">
        <Editable
          value={song.title}
          label="Title"
          placeholder="No title"
          onCommit={(title) => emit("rename", { key: song.key, title })}
        />
      </div>
      <span className="text-muted-foreground tabular-nums">{song.length}</span>
    </li>
  );
});

export default function Setlist({ props, emit }) {
  const songs = new Map(props.songs.map((song) => [song.key, song]));
  const drag = useRowDrag({
    keys: props.songs.map((song) => song.key),
    onMove: (key, to) => emit("move", { key, to }),
  });
  return (
    <ol ref={drag.list} className="flex max-w-md flex-col gap-1.5">
      {drag.order.map((key) => (
        <Song key={key} song={songs.get(key)} row={drag.row(key)} grip={drag.grip(key)} emit={emit} />
      ))}
    </ol>
  );
}
```

`useRowDrag({ keys, onMove })` takes the keys of the rows in the order
the page gave them and gives back four things.

| | |
|---|---|
| `list` | a ref for the element whose children are the rows |
| `order` | the keys in the order to draw them, which after a move is the moved order until the page has answered |
| `row(key)` | what goes on a row |
| `grip(key)` | what goes on its grip, a `RowGrip` or a button of your own |

`onMove(key, to)` is called once for each move, a drop or a place by the
keyboard, with the row's new place counted from 0. `disabled` turns the
grips off. `inset={{ top, bottom }}` says how many pixels of the box
that scrolls are covered by a header or a footer that stays, so a row
held near what is left of an edge scrolls the box. The rows can be the
rows of a table. Rows that have no grip, such as a total at the foot, go
in another parent and stay where they are. A row moves by a transform
while it is held and only the rows it passes are touched, so the page is
laid out once, at the drop.

`Editable` takes `value`, `onCommit(text)`, a `label` for a screen
reader, a `placeholder` for a text that is empty, `disabled` and a
`className`. `onCommit` gets the text as it was typed, also when
`value` is a number. It is as wide as what holds it and one line high,
and a text that is right-aligned stays so in the field. Each one is a
button on the page, so it suits the names of a few hundred rows and not
every cell of a large grid.

## A large component
<!-- keywords: performance, memo, slow, re-render, many rows -->

A component is drawn again when one of its props changes. Python sends
only the props that changed, and of a prop that is a list of sixteen
rows or more, only the rows that changed, as long as that is under half
of them. The rows that were not sent are the same objects in the browser
as they were. In a list of two hundred rows where one changed, the other
rows are the objects they were. So a component with many rows gets them
as a prop of their own, draws each row in a component of its own wrapped
in React's `memo`, and a change to one row draws that row. `emit` and
`request` are the same functions at every drawing, so a row can be
handed them.

## In a chat's composer

`ui.Chat(tools=[...])` puts components in the composer, left of Send.
That can be a `ui.Button` with a handler in Python, or a custom component,
which then receives a `chat` prop with `upload(file)`, `send(text, files)`
and `busy`. That is enough for anything the browser can capture. This
voice note button records with the browser's own recorder, uploads the
clip under the chat's `attachments` limits and sends it, and the handler
gets it as `turn.files[0]`. `paperclip=False` keeps the attach button
away when the tool is the only way files come in, and
`capture="environment"` on `Accept` makes the paperclip open the camera
on a phone.

```python live
async def heard(s, turn):
    async with turn.reply() as reply:
        if turn.files:
            clip = turn.files[0]
            await reply.text(f"A voice note of {clip.size // 1024} KB. Here it is back:")
            await reply.file(clip)
        else:
            await reply.text("Press the microphone and say something.")


ui.Card(
    ui.Chat(
        key="voice",
        welcome="Record a voice note with the microphone button.",
        attachments=ui.Accept(accept=[".webm", ".ogg", ".mp4", ".m4a"], paperclip=False),
        tools=[ui.Custom("Voice")],
        on_message=heard,
        cls="h-[20rem]",
    ),
    padding=False,
)
```

```jsx
// components/Voice.jsx
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Mic, Square } from "lucide-react";

export default function Voice({ chat }) {
  const [recorder, setRecorder] = useState(null);
  const chunks = useRef([]);
  if (!chat) return null;

  async function start() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const r = new MediaRecorder(stream);
    chunks.current = [];
    r.ondataavailable = (e) => chunks.current.push(e.data);
    r.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks.current, { type: r.mimeType || "audio/webm" });
      const ref = await chat.upload(new File([blob], "voice.webm", { type: blob.type }));
      chat.send("", [ref]);
    };
    r.start();
    setRecorder(r);
  }

  return (
    <Button type="button" size="icon-sm" variant={recorder ? "destructive" : "ghost"}
      onClick={recorder ? () => { recorder.stop(); setRecorder(null); } : start}>
      {recorder ? <Square /> : <Mic />}
    </Button>
  );
}
```
