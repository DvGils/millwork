"""The wire protocol between a session on the server and a tab in the browser.

Every message is JSON inside an envelope ``{"seq": n, "msg": {...}}``. The
server numbers what it sends so a reconnecting tab can say how far it got;
the client numbers its own messages the same way for logging. ``msg.type``
discriminates the payload.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 3


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node(Wire):
    """One node of a page. Children are ids, so a page is a flat table."""

    id: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)
    children: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- server -> client


class Mount(Wire):
    type: Literal["mount"] = "mount"
    root: str
    nodes: dict[str, Node]
    title: str | None = None


class SetOp(Wire):
    op: Literal["set"] = "set"
    id: str
    props: dict[str, Any]


class UnsetOp(Wire):
    op: Literal["unset"] = "unset"
    id: str
    keys: list[str]


class ChildrenOp(Wire):
    op: Literal["children"] = "children"
    id: str
    children: list[str]


class AddOp(Wire):
    op: Literal["add"] = "add"
    node: Node


class RemoveOp(Wire):
    op: Literal["remove"] = "remove"
    id: str


PatchOp = Annotated[SetOp | UnsetOp | ChildrenOp | AddOp | RemoveOp, Field(discriminator="op")]


class Patch(Wire):
    type: Literal["patch"] = "patch"
    ops: list[PatchOp]


class Stream(Wire):
    """A chunk of the chat stream addressed to a Chat node. Never touches the tree."""

    type: Literal["stream"] = "stream"
    node: str
    chunk: dict[str, Any]


class Command(Wire):
    type: Literal["command"] = "command"
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class SessionInfo(Wire):
    type: Literal["session"] = "session"
    id: str
    resume: str
    protocol: int = PROTOCOL_VERSION
    # Custom component versions, so a tab that outlived a deploy fetches fresh sources.
    components: dict[str, str] = Field(default_factory=dict)


class Ask(Wire):
    type: Literal["ask"] = "ask"
    request: str
    node: str
    timeout: float | None = None


class ServerError(Wire):
    type: Literal["error"] = "error"
    message: str
    fatal: bool = False


class Head(Wire):
    """A byte stream for a request starts: its metadata. Binary frames follow, then
    the ``reply``."""

    type: Literal["head"] = "head"
    request: str
    payload: Any = None


class Reply(Wire):
    """The end of a request: what it produced, or why it failed. Unnumbered: a
    request lives within one socket connection and is never replayed."""

    type: Literal["reply"] = "reply"
    request: str
    payload: Any = None
    error: str | None = None


ServerMessage = Annotated[
    Mount | Patch | Stream | Command | SessionInfo | Ask | ServerError | Head | Reply,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------- client -> server


class Hello(Wire):
    type: Literal["hello"] = "hello"
    path: str
    session: str | None = None
    resume: str | None = None
    seq: int = 0
    protocol: int = PROTOCOL_VERSION


class Event(Wire):
    type: Literal["event"] = "event"
    node: str
    name: str
    payload: Any = None


class Answer(Wire):
    type: Literal["answer"] = "answer"
    request: str
    payload: Any = None


class Navigate(Wire):
    type: Literal["navigate"] = "navigate"
    path: str


# Printable ASCII, short: it goes into every binary frame's header as is.
RequestId = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[\x21-\x7e]+$")]


class Request(Wire):
    """Something the session answers over the socket without a render: a handler's
    return value (a Combobox ``search``), a file (``file``), or an upload (``upload``,
    where ``size`` bytes follow as binary frames). The ``reply`` carries ``request``."""

    type: Literal["request"] = "request"
    node: str
    name: str
    request: RequestId
    payload: Any = None
    size: int | None = Field(default=None, ge=0)


class Cancel(Wire):
    type: Literal["cancel"] = "cancel"
    request: RequestId


ClientMessage = Annotated[
    Hello | Event | Answer | Navigate | Request | Cancel, Field(discriminator="type")
]


class Envelope(Wire):
    seq: int
    msg: ServerMessage | ClientMessage


server_message = TypeAdapter(ServerMessage)
client_message = TypeAdapter(ClientMessage)


def pack(seq: int, msg: BaseModel) -> str:
    """Serialise one message for the wire."""
    return Envelope(seq=seq, msg=msg).model_dump_json()  # type: ignore[arg-type]


def unpack_client(text: str) -> tuple[int, Hello | Event | Answer | Navigate | Request | Cancel]:
    """Parse one message from the browser. Raises ``pydantic.ValidationError``."""
    env = Envelope.model_validate_json(text)
    msg = client_message.validate_python(env.msg.model_dump())
    return env.seq, msg


# ---------------------------------------------------------------- binary frames

# A chunk of a request's byte stream, either direction: one byte with the length
# of the request id, the id in ASCII, then the bytes. Ids are short and ASCII by
# construction (the tab makes them), so the header is at most 33 bytes.
MAX_REQUEST_ID = 32


def pack_frame(request: str, data: bytes) -> bytes:
    rid = request.encode("ascii")
    if not 0 < len(rid) <= MAX_REQUEST_ID:
        raise ValueError("request id must be 1 to 32 ASCII characters")
    return bytes([len(rid)]) + rid + data


def unpack_frame(frame: bytes) -> tuple[str, bytes]:
    """Raises ``ValueError`` for a frame that is not ours."""
    if not frame:
        raise ValueError("empty frame")
    n = frame[0]
    if not 0 < n <= MAX_REQUEST_ID or len(frame) < 1 + n:
        raise ValueError("bad frame header")
    return frame[1 : 1 + n].decode("ascii"), bytes(frame[1 + n :])
