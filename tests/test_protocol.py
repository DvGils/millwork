"""Every message type round-trips through the envelope; the client side is held to its half."""

import json

import pytest
from pydantic import ValidationError

from millwork.protocol import (
    AddOp,
    Answer,
    Ask,
    Cancel,
    ChildrenOp,
    Command,
    Envelope,
    Event,
    Head,
    Hello,
    Mount,
    Navigate,
    Node,
    Patch,
    RemoveOp,
    Reply,
    Request,
    ServerError,
    SessionInfo,
    SetOp,
    Stream,
    UnsetOp,
    pack,
    server_message,
    unpack_client,
)

node = Node(id="root/a", type="Text", props={"content": "x", "n": [1, {"k": None}]}, children=[])

SERVER = [
    Mount(
        root="root",
        nodes={"root": Node(id="root", type="Page", children=["root/a"]), node.id: node},
    ),
    Mount(root="root", nodes={}, title="T"),
    Patch(
        ops=[
            AddOp(node=node),
            SetOp(id="root/a", props={"content": "y", "gone": None}),
            UnsetOp(id="root/a", keys=["n"]),
            ChildrenOp(id="root", children=[]),
            RemoveOp(id="root/a"),
        ]
    ),
    Stream(node="root/chat", chunk={"type": "text-delta", "id": "1", "delta": "hi"}),
    Command(name="toast", args={"message": "m", "tone": "default", "title": None}),
    Command(name="reload"),
    SessionInfo(id="s", resume="r"),
    Ask(request="q", node="root/@ask:q", timeout=5.0),
    ServerError(message="no", fatal=True),
    Head(request="r", payload={"name": "a.txt", "mime": "text/plain", "size": 2}),
    Reply(request="r", payload=[{"value": "a"}]),
    Reply(request="r", error="unknown request"),
]
CLIENT = [
    Hello(path="/"),
    Hello(path="/x", session="s", resume="r", seq=4, protocol=3),
    Event(node="root/a", name="click"),
    Event(node="root/f", name="submit", payload={"a": [1, 2, {"b": None}]}),
    Answer(request="q", payload=True),
    Navigate(path="/y"),
    Request(node="root/c", name="search", request="r", payload="ad"),
    Request(node="root/up", name="upload", request="u", payload={"name": "a.txt"}, size=2),
    Cancel(request="u"),
]


@pytest.mark.parametrize("msg", SERVER + CLIENT, ids=lambda m: type(m).__name__)
def test_a_message_survives_the_wire(msg: object) -> None:
    text = pack(7, msg)  # type: ignore[arg-type]
    env = Envelope.model_validate_json(text)
    assert env.seq == 7 and env.msg == msg
    assert json.loads(text)["msg"]["type"] == msg.type
    if msg in CLIENT:
        assert unpack_client(text) == (7, msg)
    else:
        assert server_message.validate_python(json.loads(text)["msg"]) == msg


def test_the_client_half_is_narrow() -> None:
    # A client cannot speak server messages, send unknown types, or add fields.
    with pytest.raises(ValidationError):
        unpack_client(pack(1, Command(name="reload")))
    with pytest.raises(ValidationError):
        unpack_client(json.dumps({"seq": 1, "msg": {"type": "mount", "root": "r", "nodes": {}}}))
    with pytest.raises(ValidationError):
        unpack_client(
            json.dumps({"seq": 1, "msg": {"type": "event", "node": "n", "name": "c", "x": 1}})
        )
    with pytest.raises(ValidationError):
        unpack_client(json.dumps({"seq": "one", "msg": {"type": "hello", "path": "/"}}))
    with pytest.raises(ValidationError):
        Patch.model_validate({"type": "patch", "ops": [{"op": "move", "id": "a"}]})
    # Payloads are opaque: any JSON goes through untouched.
    _, msg = unpack_client(
        json.dumps(
            {
                "seq": 1,
                "msg": {"type": "answer", "request": "q", "payload": [1, "2", None, {"3": 4.5}]},
            }
        )
    )
    assert isinstance(msg, Answer) and msg.payload == [1, "2", None, {"3": 4.5}]


def test_binary_frames_carry_the_request_id() -> None:
    from millwork.protocol import pack_frame, unpack_frame

    frame = pack_frame("abc123", b"\x00payload")
    assert frame[0] == 6 and unpack_frame(frame) == ("abc123", b"\x00payload")
    assert unpack_frame(pack_frame("r", b"")) == ("r", b"")
    for bad in (b"", b"\x05ab", b"\x00abc", b"\xffabc"):
        with pytest.raises(ValueError):
            unpack_frame(bad)
    with pytest.raises(ValueError):
        pack_frame("x" * 33, b"")
