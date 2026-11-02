"""The Chat component: one handler, one reply handle, messages the session owns."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from millwork import context
from millwork.icons import check_icon
from millwork.nodes import Component


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    icon: str | None = None
    description: str | None = None

    @field_validator("icon")
    @classmethod
    def _known_icon(cls, name: str | None) -> str | None:
        return check_icon(name)


class Action(BaseModel):
    """A button under an assistant message; ``on_action`` receives its id."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    icon: str | None = None

    @field_validator("icon")
    @classmethod
    def _known_icon(cls, name: str | None) -> str | None:
        return check_icon(name)


class Accept(BaseModel):
    """What the composer takes: the extensions, how many per message, how large.
    ``capture`` opens the camera or the microphone straight away on a phone;
    ``paperclip=False`` hides the attach button while uploads from the chat's
    ``tools`` still go by these limits."""

    model_config = ConfigDict(extra="forbid")

    accept: list[str] | None = None
    max_files: int = 5
    max_size_mb: int | None = None
    capture: Literal["user", "environment"] | None = None
    paperclip: bool = True


class Chat(Component):
    type: ClassVar[str] = "Chat"
    wire_exclude: ClassVar[frozenset[str]] = frozenset()

    welcome: str | None = None
    suggestions: list[str] = []
    placeholder: str | None = None
    attachments: Accept | None = None
    # The longest message and the most of them the session keeps for the
    # thread, the oldest going first: together they bound what a thread can
    # hold, whatever is sent.
    max_chars: int = 16_000
    max_messages: int = 200
    commands: list[Command] = []
    disabled: bool = False
    show_steps: Literal["full", "collapsed", "hidden"] = "collapsed"
    # Reading aids, each off by default: the assistant's picture beside its
    # messages, a name and a time above each message (on hover, always without
    # a mouse), and how long a reply and each of its steps took.
    avatar: str | None = None
    assistant_name: str | None = None
    names: bool = False
    timestamps: bool = False
    durations: bool = False
    # Under an assistant message: copy, thumbs up and down (with ``on_feedback``),
    # regenerate on the last one, the app's own ``actions``; a user message can
    # be edited and resent. Each is off without its handler or flag.
    copyable: bool = True
    regenerate: bool = True
    edit: bool = True
    actions: list[Action] = []
    # Components in the composer, left of Send: a Button with a handler, or a
    # Custom component, which receives ``chat`` with upload, send and busy.
    tools: list[Component] = []
    handler_args: ClassVar[dict[str, tuple[str, ...]]] = {
        "on_feedback": ("message", "value", "comment"),
        "on_action": ("message", "action"),
    }
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
