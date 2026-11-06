"""The connection: it follows a session's outbox onto a socket, hands the
session what the tab sends, and carries nothing but a goodbye once closed."""

import asyncio
import json
from typing import Any

import pytest

from millwork import connection
from millwork.connection import LANE_FRAMES, PIPE_FRAMES, Connection, End, Pipe
from millwork.files import Reject
from millwork.outbox import Outbox
from millwork.protocol import Command, Reply, pack, pack_frame


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.hearing = asyncio.Event()
        self.hearing.set()
        self.dead = False
        self.closed_with: int | None = None

    async def send_text(self, data: str) -> None:
        await self.hearing.wait()
        if self.dead:
            raise OSError("the tab is gone")
        self.sent.append(json.loads(data))

    async def send_bytes(self, data: bytes) -> None:
        await self.hearing.wait()
        if self.dead:
            raise OSError("the tab is gone")
        self.sent.append(data)

    async def receive(self) -> dict[str, Any]:
        return await self.inbox.get()

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    def say(self, **msg: Any) -> None:
        self.inbox.put_nowait(
            {"type": "websocket.receive", "text": json.dumps({"seq": 1, "msg": msg})}
        )

    def kinds(self) -> list[str]:
        out = []
        for item in self.sent:
            if isinstance(item, bytes):
                out.append("bytes")
            else:
                msg = item["msg"]
                out.append(f"{msg['type']}:{msg.get('name', msg.get('message', ''))}")
        return out


class FakeSession:
    id = "S1"

    def __init__(self) -> None:
        self.outbox = Outbox(keep=5)
        self.drawn: str | None = None
        self.steps: list[Any] = []
        self.pipes: dict[str, Pipe | None] = {}

    def hello(self) -> str:
        return pack(self.outbox.seq, Command(name="hello"))

    def mounted(self) -> str | None:
        if self.drawn is None:
            return None
        return pack(self.outbox.seq, Command(name=f"mount of {self.drawn}"))

    def event(self, msg: Any) -> None:
        self.steps.append(("event", msg.node, msg.name))

    def answer(self, msg: Any) -> None:
        self.steps.append(("answer", msg.request))

    def navigate(self, path: str) -> None:
        self.steps.append(("navigate", path))

    def request(self, conn: Connection, msg: Any, pipe: Pipe | None) -> None:
        self.steps.append(("request", msg.request, msg.name))
        self.pipes[msg.request] = pipe

    def cancel(self, request: str) -> None:
        self.steps.append(("cancel", request))

    def post(self, name: str) -> None:
        self.outbox.post(Command(name=name))


async def started(
    cursor: int = 0,
) -> tuple[FakeSession, FakeSocket, Connection, asyncio.Task[None]]:
    session, socket = FakeSession(), FakeSocket()
    conn = Connection(socket, "test")
    conn.bind(session, cursor)
    return session, socket, conn, asyncio.ensure_future(conn.run())


async def settle() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


async def finish(conn: Connection, running: asyncio.Task[None]) -> None:
    conn.close()
    await asyncio.wait_for(running, 1.0)


async def test_it_says_which_session_and_then_follows_the_outbox_in_order() -> None:
    session, socket, conn, running = await started()
    session.post("one")
    session.post("two")
    await settle()
    session.post("three")
    await settle()
    assert socket.kinds() == ["command:hello", "command:one", "command:two", "command:three"]
    assert [m["seq"] for m in socket.sent[1:]] == [1, 2, 3] and conn.cursor == 3
    await finish(conn, running)


async def test_a_tab_that_comes_back_gets_what_it_missed_and_no_more() -> None:
    session = FakeSession()
    for name in ("one", "two", "three", "four"):
        session.post(name)
    socket = FakeSocket()
    conn = Connection(socket)
    conn.bind(session, 2)
    running = asyncio.ensure_future(conn.run())
    await settle()
    assert socket.kinds() == ["command:hello", "command:three", "command:four"]
    await finish(conn, running)


@pytest.mark.parametrize("cursor", [-1, 1, 99])
async def test_a_tab_that_cannot_be_caught_up_gets_the_page_as_it_stands(cursor: int) -> None:
    # Loaded anew, behind the window, or claiming more than there is.
    session = FakeSession()
    for n in range(8):
        session.post(f"m{n}")
    session.drawn = "the page"
    socket = FakeSocket()
    conn = Connection(socket)
    conn.bind(session, cursor)
    running = asyncio.ensure_future(conn.run())
    await settle()
    session.post("next")
    await settle()
    assert socket.kinds() == ["command:hello", "command:mount of the page", "command:next"]
    assert [m["seq"] for m in socket.sent[1:]] == [8, 9]
    await finish(conn, running)


async def test_with_no_page_drawn_yet_a_new_tab_waits_for_one() -> None:
    # Loaded anew while the page is still being opened: what was said
    # meanwhile is not for it, and the page comes when there is one.
    session, socket, conn, running = await started(cursor=-1)
    session.post("meanwhile")
    await settle()
    assert socket.kinds() == ["command:hello"]
    session.drawn = "the page"
    session.post("mount")
    await settle()
    assert socket.kinds() == ["command:hello", "command:mount of the page"]
    assert conn.cursor == session.outbox.seq
    await finish(conn, running)


async def test_replies_and_the_bytes_of_a_file_go_out_in_the_order_given() -> None:
    session, socket, conn, running = await started()
    await settle()
    assert conn.say(Reply(request="r1", payload=1))
    assert await conn.frame(b"aa")
    assert await conn.frame(b"bb")
    assert conn.say(Reply(request="r1", payload=2))
    await settle()
    assert socket.kinds()[1:] == ["reply:", "bytes", "bytes", "reply:"]
    assert all(m["seq"] == 0 for m in socket.sent if not isinstance(m, bytes))
    await finish(conn, running)


async def test_a_file_waits_for_its_own_tab_and_holds_up_nothing_else() -> None:
    session, socket, conn, running = await started()
    await settle()
    socket.hearing.clear()
    sent = 0

    async def download() -> None:
        nonlocal sent
        for _ in range(LANE_FRAMES + 6):
            if not await conn.frame(b"x" * 10):
                return
            sent += 1

    sending = asyncio.ensure_future(download())
    await settle()
    # One frame is with the socket, the lane is full, and the request waits.
    assert sent == LANE_FRAMES + 1 and not sending.done()
    # The session is not held up by any of it.
    session.post("meanwhile")
    assert conn.say(Reply(request="other", payload=None))
    socket.hearing.set()
    await asyncio.wait_for(sending, 1.0)
    await settle()
    assert socket.kinds().count("bytes") == LANE_FRAMES + 6
    assert "command:meanwhile" in socket.kinds()
    await finish(conn, running)


async def test_closed_with_an_end_it_says_goodbye_and_nothing_else() -> None:
    session, socket, conn, running = await started()
    await settle()
    session.post("too late")
    conn.close(End("Signed out.", to="/login"))
    assert not conn.say(Reply(request="r", payload=None))
    assert not await conn.frame(b"x")
    session.post("after")
    await asyncio.wait_for(running, 1.0)
    assert socket.kinds() == ["command:hello", "command:leave", "error:Signed out."]
    assert socket.sent[1]["msg"]["args"] == {"to": "/login"}
    assert socket.sent[2]["msg"]["fatal"] is True
    assert conn.code == connection.REPLACED and session.outbox.poke is None


async def test_the_goodbye_waits_for_a_destination_that_is_still_being_asked() -> None:
    session, socket, conn, running = await started()
    await settle()
    asking: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
    conn.close(End("Signed out.", to="/login", asking=asking))
    await settle()
    assert socket.kinds() == ["command:hello"] and not running.done()
    asking.set_result("https://idp.example/bye")
    await asyncio.wait_for(running, 1.0)
    assert socket.sent[1]["msg"]["args"] == {"to": "https://idp.example/bye"}


async def test_a_destination_that_was_never_found_falls_back() -> None:
    session, socket, conn, running = await started()
    await settle()
    asking: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
    asking.set_result(None)
    conn.close(End("Signed out.", to="/login", asking=asking))
    await asyncio.wait_for(running, 1.0)
    assert socket.sent[1]["msg"]["args"] == {"to": "/login"}


async def test_an_end_with_nowhere_to_go_only_says_why() -> None:
    session, socket, conn, running = await started()
    await settle()
    conn.close(End("Made room."))
    await asyncio.wait_for(running, 1.0)
    assert socket.kinds() == ["command:hello", "error:Made room."]


async def test_a_tab_that_does_not_read_is_let_go_when_its_time_is_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connection, "END_NOTICE_SECONDS", 0.05)
    session, socket, conn, running = await started()
    await settle()
    socket.hearing.clear()
    session.post("stuck in the socket")
    await settle()
    conn.close(End("Signed out.", to="/login"))
    await asyncio.wait_for(running, 1.0)
    # It heard nothing, and the endpoint closes the socket now.
    assert socket.kinds() == ["command:hello"]


async def test_closed_without_an_end_it_just_stops() -> None:
    session, socket, conn, running = await started()
    await settle()
    conn.close(code=connection.REPLACED)
    await asyncio.wait_for(running, 1.0)
    assert socket.kinds() == ["command:hello"] and conn.code == connection.REPLACED


async def test_a_connection_that_was_replaced_leaves_the_outbox_to_the_new_one() -> None:
    session, socket, old, running = await started()
    await settle()
    new_socket = FakeSocket()
    new = Connection(new_socket)
    old.close(code=connection.REPLACED)
    new.bind(session, old.cursor)
    newer = asyncio.ensure_future(new.run())
    await asyncio.wait_for(running, 1.0)
    session.post("for the new one")
    await settle()
    assert new_socket.kinds() == ["command:hello", "command:for the new one"]
    assert socket.kinds() == ["command:hello"]
    await finish(new, newer)


async def test_a_tab_that_goes_away_ends_the_connection() -> None:
    session, socket, conn, running = await started()
    await settle()
    socket.inbox.put_nowait({"type": "websocket.disconnect", "code": 1001})
    await asyncio.wait_for(running, 1.0)
    assert conn.closed


async def test_a_socket_that_fails_ends_the_connection_quietly() -> None:
    session, socket, conn, running = await started()
    await settle()
    socket.dead = True
    session.post("into the void")
    await asyncio.wait_for(running, 1.0)
    assert conn.closed


async def test_what_the_tab_says_reaches_the_sessions_steps() -> None:
    session, socket, conn, running = await started()
    socket.say(type="event", node="root/b", name="click")
    socket.inbox.put_nowait({"type": "websocket.receive", "text": "not json"})
    socket.say(type="navigate", path="/there")
    socket.say(type="request", request="r1", node="root/c", name="search", payload="a")
    socket.say(type="cancel", request="r1")
    socket.say(type="request", request="u1", node="root/u", name="upload", size=4)
    await settle()
    assert session.steps == [
        ("event", "root/b", "click"),
        ("navigate", "/there"),
        ("request", "r1", "search"),
        ("cancel", "r1"),
        ("request", "u1", "upload"),
    ]
    assert session.pipes["r1"] is None and isinstance(session.pipes["u1"], Pipe)
    await finish(conn, running)


async def test_upload_bytes_go_down_a_pipe_that_holds_the_socket_back() -> None:
    session, socket, conn, running = await started()
    frames = PIPE_FRAMES + 4
    socket.say(type="request", request="u1", node="root/u", name="upload", size=frames)
    for _ in range(frames):
        socket.inbox.put_nowait({"type": "websocket.receive", "bytes": pack_frame("u1", b"x")})
    socket.say(type="event", node="root/b", name="click")
    await settle()
    pipe = session.pipes["u1"]
    assert pipe is not None
    # The pipe is full and the reader waits: the click behind it is not read.
    assert ("event", "root/b", "click") not in session.steps
    got = 0
    while await asyncio.wait_for(pipe.get(), 1.0) is not None:
        got += 1
    await settle()
    assert got == frames and ("event", "root/b", "click") in session.steps
    await finish(conn, running)


async def test_a_request_that_is_done_lets_go_of_the_bytes_still_coming() -> None:
    session, socket, conn, running = await started()
    socket.say(type="request", request="u1", node="root/u", name="upload", size=100)
    for _ in range(PIPE_FRAMES + 4):
        socket.inbox.put_nowait({"type": "websocket.receive", "bytes": pack_frame("u1", b"x")})
    socket.say(type="event", node="root/b", name="click")
    await settle()
    pipe = session.pipes["u1"]
    assert pipe is not None
    conn.forget("u1")
    await settle()
    # The reader is free again, and what follows for that request is dropped.
    assert ("event", "root/b", "click") in session.steps
    with pytest.raises(Reject):
        await pipe.get()
    await finish(conn, running)


async def test_closing_fails_every_pipe() -> None:
    session, socket, conn, running = await started()
    socket.say(type="request", request="u1", node="root/u", name="upload", size=100)
    await settle()
    pipe = session.pipes["u1"]
    assert pipe is not None
    conn.close()
    with pytest.raises(Reject):
        await pipe.get()
    await asyncio.wait_for(running, 1.0)
