---
title: Custom components
order: 10
---

# Custom components

When the catalogue has no component for something, an app writes one in
JSX. The file lives in the app's `components/` folder, gets compiled in
the browser, and composes the same primitives the catalogue is built
from. Python reaches it by name with `ui.Custom`.

## The contract

A component is a default export that receives `props` from Python, `emit`
to send an event back, `request` to ask one of its handlers and get the
answer as a promise, `fileUrl` to show a session file, and `children`
rendered from Python.

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

## Using it from Python

`ui.Custom(name, props=, events=)` renders `components/<name>.jsx`. Events
the component emits reach the handler named in `events`, or `on_event` as
`(name, payload)`.

```python live
from pydantic import BaseModel


class Waves(BaseModel):
    count: int = 0


def example(s):
    st = state(Waves)

    def waved(s, clicks):
        st.count += 1
        s.toast(f"Waved after {clicks} local clicks.")

    return ui.Custom(
        "Hello",
        ui.Text("Children from Python render inside the custom component.", variant="muted"),
        props={"who": "Ada", "count": st.count},
        events={"wave": waved},
    )
```

A custom component can import React, lucide icons, and every
`@/components/ui/*` module the catalogue uses. Tailwind classes work, and
ones the bundle never saw are compiled in the browser on first use.

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
