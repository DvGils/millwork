"""The Chat component: one handler, one reply handle, messages the session owns."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from millwork import context
from millwork.nodes import Component


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    icon: str | None = None
    description: str | None = None


class Action(BaseModel):
    """A button under an assistant message; ``on_action`` receives its id."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    icon: str | None = None


class Accept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept: list[str] | None = None
    max_files: int = 5
    max_size_mb: int | None = None


class Chat(Component):
    type: ClassVar[str] = "Chat"
    wire_exclude: ClassVar[frozenset[str]] = frozenset()

    welcome: str | None = None
    suggestions: list[str] = []
    placeholder: str | None = None
    attachments: Accept | None = None
    max_chars: int = 64_000
    commands: list[Command] = []
    disabled: bool = False
    show_steps: Literal["full", "collapsed", "hidden"] = "collapsed"
    avatar: str | None = None
    # Under an assistant message: copy, thumbs up and down (with ``on_feedback``),
    # regenerate on the last one, the app's own ``actions``; a user message can
    # be edited and resent. Each is off without its handler or flag.
    copyable: bool = True
    regenerate: bool = True
    edit: bool = True
    actions: list[Action] = []
    on_message: Any = None
    on_stop: Any = None
    on_feedback: Any = None
    on_action: Any = None

    def wire_extra(self) -> dict[str, Any]:
        """The finished messages and the thread's live bits; the in-flight one is the stream's."""
        s = context.current()
        if s is None or self.key is None:
            return {"messages": [], "busy": False, "inline": {}}
        thread = s.chat(self.key)
        return {
            "messages": [m.model_dump(mode="json") for m in thread.messages],
            "busy": thread.busy,
            "live_suggestions": thread.suggestions,
            "inline": dict(thread.inline),
        }
