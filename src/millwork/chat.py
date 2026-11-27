"""Chat: messages the session owns, a turn, and the reply handle that streams.

On the wire a reply is the AI SDK UI message stream: ``text-start``,
``text-delta``, ``tool-input-available`` and so on, one chunk per
``Stream`` message addressed to the Chat node. The bundle parses that into
message parts and renders them. Between turns the finished messages travel
as a prop; the in-flight message is the stream's alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from millwork.files import FileRef

if TYPE_CHECKING:
    from millwork.nodes import Component
    from millwork.session import Session

log = logging.getLogger("millwork.chat")

Role = Literal["user", "assistant", "system"]


def _said(session: Session[Any], exc: BaseException) -> str:
    """What the transcript says of a reply or a step that raised. The words
    of an exception are for whoever runs the app: they can name a table, a
    host or a path. A reader gets the theme's own line, and the log has the
    rest. In debug mode the reader is the developer, and gets the words."""
    if session.app.debug:
        return str(exc) or type(exc).__name__
    return session.text("something_went_wrong")


class UIMessage(BaseModel):
    """The AI SDK message shape: a role and a list of parts."""

    model_config = ConfigDict(extra="allow")

    id: str
    role: Role
    parts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    @property
    def text(self) -> str:
        return "".join(p.get("text", "") for p in self.parts if p.get("type") == "text")


@dataclass
class Asked:
    """A question in a reply that waits for the person: where it stands,
    what it says, and the values it can be answered with."""

    node: str
    part: dict[str, Any]
    data: dict[str, Any]
    values: frozenset[str]
    future: asyncio.Future[str]


class Thread:
    """One Chat node's messages, kept by the session under the node's key."""

    def __init__(self) -> None:
        self.messages: list[UIMessage] = []
        self.inflight: UIMessage | None = None
        # The reply that is being streamed, which can say itself again.
        self.reply: Reply | None = None
        self.turn_task: asyncio.Task[Any] | None = None
        self.inline: dict[str, Component] = {}
        # The questions of the reply that wait for the person, by their id.
        self.asked: dict[str, Asked] = {}
        self.suggestions: list[str] = []
        # The most messages the session keeps for this thread; the oldest go.
        # The Chat's ``max_messages`` sets it, so a thread never outgrows what
        # the app asked for, whatever a visitor sends.
        self.limit = 200

    @property
    def busy(self) -> bool:
        """From the moment a turn's handler starts until it ends, not only while it streams."""
        return self.inflight is not None or self.turn_task is not None

    @property
    def asking(self) -> bool:
        """Whether the reply waits for the person to answer a question."""
        return any(not a.future.done() for a in self.asked.values())

    def clear(self) -> None:
        self.messages.clear()
        self.inline.clear()
        self.suggestions.clear()

    def load(self, messages: Sequence[UIMessage | dict[str, Any]]) -> None:
        self.messages = [m if isinstance(m, UIMessage) else UIMessage(**m) for m in messages]
        self._trim()

    def append(self, message: UIMessage) -> None:
        self.messages.append(message)
        self._trim()

    def _trim(self) -> None:
        extra = len(self.messages) - self.limit
        if extra > 0:
            del self.messages[:extra]
            self._sweep_inline()

    def find(self, message_id: str) -> int | None:
        return next((i for i, m in enumerate(self.messages) if m.id == message_id), None)

    def truncate(self, index: int) -> None:
        """Drop the messages from ``index`` on, and the inline components only they used."""
        del self.messages[index:]
        self._sweep_inline()
        self.suggestions.clear()

    def _sweep_inline(self) -> None:
        """Drop the inline components no remaining message uses."""
        kept = {
            p.get("data", {}).get("slot")
            for m in self.messages
            for p in m.parts
            if p.get("type") == "data-component"
        }
        for slot in [s for s in self.inline if s not in kept]:
            del self.inline[slot]


class ChatTurn:
    """What ``on_message`` receives: the user's message and a way to reply."""

    def __init__(
        self,
        session: Session[Any],
        node_id: str,
        thread: Thread,
        message: UIMessage,
        files: list[FileRef],
        command: str | None,
    ) -> None:
        self.session = session
        self.node_id = node_id
        self.thread = thread
        self.message = message
        self.files = files
        self.command = command

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def history(self) -> list[UIMessage]:
        """Every message before this turn's, oldest first."""
        return [m for m in self.thread.messages if m.id != self.message.id]

    @contextlib.asynccontextmanager
    async def reply(self) -> AsyncIterator[Reply]:
        reply = Reply(self.session, self.node_id, self.thread)
        await reply._start()
        try:
            yield reply
        except asyncio.CancelledError:
            await reply._finish("stopped")
            raise
        except Exception as exc:
            log.exception("chat turn failed")
            await reply.error(_said(self.session, exc))
            await reply._finish("error")
            raise
        else:
            await reply._finish("stop")


class Reply:
    """Streams one assistant message. Each call is a chunk on the wire and a part in the message."""

    def __init__(self, session: Session[Any], node_id: str, thread: Thread) -> None:
        self._s = session
        self._node = node_id
        self._thread = thread
        # When the reply began and how long it took, kept in the message's metadata
        # so the time shows on a reload too; the tab reads them when asked to.
        self.message = UIMessage(
            id=secrets.token_urlsafe(8), role="assistant", metadata={"at": time.time()}
        )
        self._text_id: str | None = None
        # The text part that is being written, between its start and its end.
        self._text_part: dict[str, Any] | None = None
        # The thoughts that are being written, by the id their chunks carry.
        self._reasoning: dict[str, dict[str, Any]] = {}
        # What the reply last said it is doing, which no part holds.
        self._status: str | None = None
        self._finished = False
        self._started = time.monotonic()
        # How long the reply has waited for the person, which is no part
        # of how long it took, nor of how long a step did that waited. Two
        # questions open at once wait once: the time runs from the first
        # that opens until none is open.
        self._waited = 0.0
        self._asking = 0
        self._asking_since = 0.0
        self._tool_started: dict[str, tuple[float, float]] = {}

    async def _send(self, chunk: dict[str, Any]) -> None:
        await self._s.stream(self._node, chunk)

    def _waited_now(self) -> float:
        """How long the reply has waited for the person so far."""
        open_for = time.monotonic() - self._asking_since if self._asking else 0.0
        return self._waited + open_for

    def _start_chunk(self) -> dict[str, Any]:
        start = {"type": "start", "messageId": self.message.id}
        return {**start, "messageMetadata": self.message.metadata}

    async def _start(self) -> None:
        self._thread.inflight = self.message
        self._thread.reply = self
        self._thread.suggestions = []
        self._s.refresh()
        await self._send(self._start_chunk())
        await self._send({"type": "start-step"})

    async def _finish(self, reason: str) -> None:
        if self._finished:
            return
        self._finished = True
        # A question that is still open has nobody left to answer to: one
        # asked from a thread or from a task of the handler's own, which
        # the end of the reply does not reach by itself.
        for ask_id, asked in list(self._thread.asked.items()):
            part = self._close(ask_id, None)
            asked.future.cancel()
            if part is not None:
                await self._send(part)
        await self._end_text()
        took = round(max(0.0, time.monotonic() - self._started - self._waited_now()), 3)
        self.message.metadata = {**(self.message.metadata or {}), "took": took}
        await self._send({"type": "message-metadata", "messageMetadata": {"took": took}})
        await self._send({"type": "finish-step"})
        await self._send({"type": "finish", "finishReason": reason})
        self._thread.append(self.message)
        self._thread.inflight = None
        self._thread.reply = None
        self._s.refresh()

    def said(self) -> list[dict[str, Any]]:
        """The reply as far as it has come, in chunks that make it from
        nothing: for a tab that has none of it, or has missed some. What is
        still being written keeps the id its next chunks carry."""
        chunks: list[dict[str, Any]] = [self._start_chunk(), {"type": "start-step"}]
        open_ids = {id(part): rid for rid, part in self._reasoning.items()}
        if self._text_id is not None and self._text_part is not None:
            open_ids[id(self._text_part)] = self._text_id
        for part in self.message.parts:
            kind = part["type"]
            if kind in ("text", "reasoning"):
                wire_id = open_ids.get(id(part)) or secrets.token_urlsafe(6)
                chunks.append({"type": f"{kind}-start", "id": wire_id})
                if part.get("text"):
                    chunks.append({"type": f"{kind}-delta", "id": wire_id, "delta": part["text"]})
                if id(part) not in open_ids:
                    chunks.append({"type": f"{kind}-end", "id": wire_id})
            elif kind.startswith("tool-"):
                call = {"toolCallId": part["toolCallId"]}
                chunks.append(
                    {
                        "type": "tool-input-available",
                        **call,
                        "toolName": kind[5:],
                        "input": part.get("input"),
                    }
                )
                took = {"took": part.get("took")}
                if part.get("state") == "output-available":
                    out = {"type": "tool-output-available", **call, "output": part.get("output")}
                    chunks.append({**out, **took})
                elif part.get("state") == "output-error":
                    out = {"type": "tool-output-error", **call, "errorText": part.get("errorText")}
                    chunks.append({**out, **took})
            else:
                # A source, a file, an error and a data part are each one
                # chunk, which is the part.
                chunks.append(dict(part))
        if self._status is not None:
            status = {"type": "data-status", "data": {"text": self._status}}
            chunks.append({**status, "transient": True})
        return chunks

    # ------------------------------------------------------------- parts

    async def _end_text(self) -> None:
        if self._text_id is not None and self._text_part is not None:
            # No longer the text being written by the time its end is sent:
            # a send can wait, and the reply may be said again meanwhile.
            text_id, self._text_part["state"] = self._text_id, "done"
            self._text_id = self._text_part = None
            await self._send({"type": "text-end", "id": text_id})

    async def text(self, chunk: str) -> None:
        """Append text to the reply; consecutive calls extend one text part."""
        if not chunk:
            return
        if self._text_id is None:
            self._text_id = secrets.token_urlsafe(6)
            self._text_part = {"type": "text", "text": "", "state": "streaming"}
            self.message.parts.append(self._text_part)
            await self._send({"type": "text-start", "id": self._text_id})
        assert self._text_part is not None
        self._text_part["text"] += chunk
        await self._send({"type": "text-delta", "id": self._text_id, "delta": chunk})

    @contextlib.asynccontextmanager
    async def reasoning(self) -> AsyncIterator[ReasoningHandle]:
        await self._end_text()
        rid = secrets.token_urlsafe(6)
        part: dict[str, Any] = {"type": "reasoning", "text": "", "state": "streaming"}
        self.message.parts.append(part)
        self._reasoning[rid] = part
        await self._send({"type": "reasoning-start", "id": rid})
        try:
            yield ReasoningHandle(self, rid, part)
        finally:
            part["state"] = "done"
            del self._reasoning[rid]
            await self._send({"type": "reasoning-end", "id": rid})

    async def tool(self, name: str, input: Any = None) -> ToolHandle:
        """A tool call: its input now, its output or error through the handle."""
        await self._end_text()
        call_id = secrets.token_urlsafe(6)
        part: dict[str, Any] = {
            "type": f"tool-{name}",
            "toolCallId": call_id,
            "state": "input-available",
            "input": input,
        }
        self.message.parts.append(part)
        self._tool_started[call_id] = (time.monotonic(), self._waited_now())
        await self._send(
            {
                "type": "tool-input-available",
                "toolCallId": call_id,
                "toolName": name,
                "input": input,
            }
        )
        return ToolHandle(self, call_id, part)

    def _took(self, call_id: str) -> float:
        started = self._tool_started.pop(call_id, None)
        if started is None:
            return 0.0
        began, waited = started
        return round(max(0.0, time.monotonic() - began - (self._waited_now() - waited)), 3)

    @contextlib.asynccontextmanager
    async def step(self, label: str) -> AsyncIterator[ToolHandle]:
        """A labelled step in the transcript: a tool call without a tool."""
        handle = await self.tool("step", {"label": label})
        try:
            yield handle
        except Exception as exc:
            await handle.error(_said(self._s, exc))
            raise
        else:
            if handle.part["state"] == "input-available":
                await handle.output(None)

    async def source(
        self, title: str, url: str | None = None, snippet: str | None = None, **meta: Any
    ) -> None:
        await self._end_text()
        sid = secrets.token_urlsafe(6)
        if url:
            part = {
                "type": "source-url",
                "sourceId": sid,
                "url": url,
                "title": title,
                **({"snippet": snippet} if snippet else {}),
                **meta,
            }
            self.message.parts.append(part)
            await self._send(part)
        else:
            part = {
                "type": "source-document",
                "sourceId": sid,
                "mediaType": meta.pop("media_type", "text/plain"),
                "title": title,
                **({"snippet": snippet} if snippet else {}),
                **meta,
            }
            self.message.parts.append(part)
            await self._send(part)

    async def file(
        self, content: FileRef | bytes | str, name: str | None = None, mime: str | None = None
    ) -> FileRef:
        """A file in the reply, stored on the session; the tab fetches it by id."""
        from millwork.files import content_to_file

        ref = (
            content
            if isinstance(content, FileRef)
            else content_to_file(self._s, content, name or "file", mime)
        )
        await self._end_text()
        part = {
            "type": "file",
            "mediaType": ref.mime,
            "url": "",
            "filename": ref.name,
            "fileId": ref.id,
        }
        self.message.parts.append(part)
        await self._send(part)
        return ref

    async def image(
        self, content: FileRef | bytes, name: str = "image.png", mime: str = "image/png"
    ) -> FileRef:
        return await self.file(content, name, mime)

    async def status(self, text: str) -> None:
        """A transient marker under the message while it streams."""
        self._status = text
        await self._send({"type": "data-status", "data": {"text": text}, "transient": True})

    async def suggestions(self, items: list[str]) -> None:
        self._thread.suggestions = list(items)
        await self._send(
            {"type": "data-suggestions", "data": {"items": list(items)}, "transient": True}
        )

    async def data(self, kind: str, payload: Any, *, id: str | None = None) -> None:
        """A custom part rendered by the app's ``components/<kind>.jsx``."""
        if kind == "ask":
            raise ValueError(
                "the kind 'ask' is the part of reply.ask, and a part of your own needs another name"
            )
        await self._end_text()
        part: dict[str, Any] = {"type": f"data-{kind}", "data": payload}
        if id:
            part["id"] = id
            for i, existing in enumerate(self.message.parts):
                if existing.get("type") == part["type"] and existing.get("id") == id:
                    self.message.parts[i] = part
                    break
            else:
                self.message.parts.append(part)
        else:
            self.message.parts.append(part)
        await self._send(part)

    async def component(self, component: Component) -> str:
        """A catalogue (or custom) component inside the message, patched like any node."""
        await self._end_text()
        part_id = secrets.token_urlsafe(6)
        self._thread.inline[part_id] = component
        part = {"type": "data-component", "id": part_id, "data": {"slot": part_id}}
        self.message.parts.append(part)
        self._s.refresh()
        await self._send(part)
        return part_id

    async def ask(
        self,
        question: str,
        description: str | None = None,
        *,
        options: Sequence[Any] | Mapping[str, str],
        primary: str | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> str | None:
        """Ask the person a question in the reply and wait for the answer:
        the value of the option they pressed.

        ``options`` are what a ``Select`` takes, strings, ``(value, label)``
        pairs or ``ui.Option``s, or a mapping of each value to its label.
        ``primary`` is the value of the one that stands out. The answer is
        ``None`` when nobody gave one in ``timeout`` seconds. A reply that
        is stopped is cancelled as it waits, like any work of the turn, and
        its question ends as one nobody answered.

        Once answered, the question says what was chosen and can not be
        answered again. It is a part of the message, so a thread that is
        kept and loaded again shows it as it ended. The time it waited is
        left out of how long the reply took.
        """
        from millwork.ui import as_options

        offered = as_options(list(options.items()) if isinstance(options, Mapping) else options)
        values = [o.value for o in offered]
        if not values:
            raise ValueError("a question needs at least one option to answer it with")
        if len(set(values)) != len(values):
            raise ValueError(f"the options of a question each need a value of their own: {values}")
        if primary is not None and primary not in values:
            raise ValueError(f"primary={primary!r} is not one of the options {values}")
        await self._end_text()
        ask_id = secrets.token_urlsafe(6)
        data: dict[str, Any] = {
            "question": question,
            "options": [
                {"value": o.value, "label": o.label or o.value}
                | ({"icon": o.icon} if o.icon else {})
                for o in offered
            ],
            "open": True,
            "answer": None,
        }
        if description:
            data["description"] = description
        if primary is not None:
            data["primary"] = primary
        if self._finished:
            raise RuntimeError("the reply is over, and asks nothing more")
        part: dict[str, Any] = {"type": "data-ask", "id": ask_id, "data": data}
        self.message.parts.append(part)
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._thread.asked[ask_id] = Asked(self._node, part, data, frozenset(values), future)
        if not self._asking:
            self._asking_since = time.monotonic()
        self._asking += 1
        answer: str | None = None
        try:
            self._s.refresh()
            await self._send(part)
            if timeout is None:
                answer = await future
            else:
                answer = await asyncio.wait_for(future, timeout)
        except TimeoutError:
            answer = None
        finally:
            self._asking -= 1
            if not self._asking:
                self._waited += time.monotonic() - self._asking_since
            if self._close(ask_id, answer) is not None:
                self._s.refresh()
                await self._send(part)
        return answer

    def _close(self, ask_id: str, answer: str | None) -> dict[str, Any] | None:
        """End a question with its answer, or with none. Gives its part as
        it is from now on, or nothing for a question that had ended."""
        asked = self._thread.asked.pop(ask_id, None)
        if asked is None:
            return None
        # A new dict, not a change to the one that was sent: the question
        # as it ended takes the place of the open one.
        asked.part["data"] = {**asked.data, "open": False, "answer": answer}
        return asked.part

    async def error(self, text: str) -> None:
        """Say that the reply failed, in words for the person. It is kept
        with the message, so it is there after a reload as well."""
        await self._end_text()
        part = {"type": "error", "errorText": text}
        self.message.parts.append(part)
        await self._send(part)


class ReasoningHandle:
    def __init__(self, reply: Reply, rid: str, part: dict[str, Any]) -> None:
        self._reply = reply
        self._id = rid
        self._part = part

    async def text(self, chunk: str) -> None:
        if not chunk:
            return
        self._part["text"] += chunk
        await self._reply._send({"type": "reasoning-delta", "id": self._id, "delta": chunk})


class ToolHandle:
    def __init__(self, reply: Reply, call_id: str, part: dict[str, Any]) -> None:
        self._reply = reply
        self.id = call_id
        self.part = part

    async def output(self, result: Any) -> None:
        took = self._reply._took(self.id)
        self.part["state"] = "output-available"
        self.part["output"] = result
        self.part["took"] = took
        await self._reply._send(
            {"type": "tool-output-available", "toolCallId": self.id, "output": result, "took": took}
        )

    async def error(self, text: str) -> None:
        took = self._reply._took(self.id)
        self.part["state"] = "output-error"
        self.part["errorText"] = text
        self.part["took"] = took
        await self._reply._send(
            {"type": "tool-output-error", "toolCallId": self.id, "errorText": text, "took": took}
        )
