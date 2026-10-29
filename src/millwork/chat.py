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
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from millwork.files import FileRef

if TYPE_CHECKING:
    from millwork.nodes import Component
    from millwork.session import Session

log = logging.getLogger("millwork.chat")

Role = Literal["user", "assistant", "system"]


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


class Thread:
    """One Chat node's messages, kept by the session under the node's key."""

    def __init__(self) -> None:
        self.messages: list[UIMessage] = []
        self.inflight: UIMessage | None = None
        self.turn_task: asyncio.Task[Any] | None = None
        self.inline: dict[str, Component] = {}
        self.suggestions: list[str] = []

    @property
    def busy(self) -> bool:
        """From the moment a turn's handler starts until it ends, not only while it streams."""
        return self.inflight is not None or self.turn_task is not None

    def clear(self) -> None:
        self.messages.clear()
        self.inline.clear()
        self.suggestions.clear()

    def load(self, messages: list[UIMessage | dict[str, Any]]) -> None:
        self.messages = [m if isinstance(m, UIMessage) else UIMessage(**m) for m in messages]


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
            await reply.error(str(exc) or type(exc).__name__)
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
        self.message = UIMessage(id=secrets.token_urlsafe(8), role="assistant")
        self._text_id: str | None = None
        self._finished = False

    async def _send(self, chunk: dict[str, Any]) -> None:
        await self._s.stream(self._node, chunk)

    async def _start(self) -> None:
        self._thread.inflight = self.message
        self._thread.suggestions = []
        self._s.refresh()
        await self._send({"type": "start", "messageId": self.message.id})
        await self._send({"type": "start-step"})

    async def _finish(self, reason: str) -> None:
        if self._finished:
            return
        self._finished = True
        await self._end_text()
        await self._send({"type": "finish-step"})
        await self._send({"type": "finish", "finishReason": reason})
        self._thread.messages.append(self.message)
        self._thread.inflight = None
        self._s.refresh()

    # ------------------------------------------------------------- parts

    async def _end_text(self) -> None:
        if self._text_id is not None:
            await self._send({"type": "text-end", "id": self._text_id})
            self._text_id = None

    async def text(self, chunk: str) -> None:
        """Append text to the reply; consecutive calls extend one text part."""
        if not chunk:
            return
        if self._text_id is None:
            self._text_id = secrets.token_urlsafe(6)
            self.message.parts.append({"type": "text", "text": "", "state": "streaming"})
            await self._send({"type": "text-start", "id": self._text_id})
        self.message.parts[-1]["text"] += chunk
        await self._send({"type": "text-delta", "id": self._text_id, "delta": chunk})

    @contextlib.asynccontextmanager
    async def reasoning(self) -> AsyncIterator[ReasoningHandle]:
        await self._end_text()
        rid = secrets.token_urlsafe(6)
        part: dict[str, Any] = {"type": "reasoning", "text": "", "state": "streaming"}
        self.message.parts.append(part)
        await self._send({"type": "reasoning-start", "id": rid})
        try:
            yield ReasoningHandle(self, rid, part)
        finally:
            part["state"] = "done"
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
        await self._send(
            {
                "type": "tool-input-available",
                "toolCallId": call_id,
                "toolName": name,
                "input": input,
            }
        )
        return ToolHandle(self, call_id, part)

    @contextlib.asynccontextmanager
    async def step(self, label: str) -> AsyncIterator[ToolHandle]:
        """A labelled step in the transcript: a tool call without a tool."""
        handle = await self.tool("step", {"label": label})
        try:
            yield handle
        except Exception as exc:
            await handle.error(str(exc) or type(exc).__name__)
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
        await self._send({"type": "data-status", "data": {"text": text}, "transient": True})

    async def suggestions(self, items: list[str]) -> None:
        self._thread.suggestions = list(items)
        await self._send(
            {"type": "data-suggestions", "data": {"items": list(items)}, "transient": True}
        )

    async def data(self, kind: str, payload: Any, *, id: str | None = None) -> None:
        """A custom part rendered by the app's ``components/<kind>.jsx``."""
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

    async def error(self, text: str) -> None:
        await self._send({"type": "error", "errorText": text})


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
        self.part["state"] = "output-available"
        self.part["output"] = result
        await self._reply._send(
            {"type": "tool-output-available", "toolCallId": self.id, "output": result}
        )

    async def error(self, text: str) -> None:
        self.part["state"] = "output-error"
        self.part["errorText"] = text
        await self._reply._send(
            {"type": "tool-output-error", "toolCallId": self.id, "errorText": text}
        )
