"""Chat: a turn records the user message, the reply streams chunks, the thread keeps the result."""

import asyncio
import json
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

import millwork as mw
from millwork import ui


def send(ws: Any, msg: dict[str, Any]) -> None:
    ws.send_text(json.dumps({"seq": 1, "msg": msg}))


def recv(ws: Any) -> dict[str, Any]:
    return json.loads(ws.receive_text())["msg"]


def collect(ws: Any, until: Any, limit: int = 80) -> list[dict[str, Any]]:
    out = []
    for _ in range(limit):
        m = recv(ws)
        out.append(m)
        if until(m):
            return out
    raise AssertionError(f"not reached: {[m.get('type') for m in out]}")


def make_app(tmp_path: Path) -> mw.App:
    app = mw.App("c", public=None, bundle_dir=tmp_path, secret="s")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        thread = s.chat("main")
        return ui.Page(
            ui.Chat(
                key="main",
                welcome="Hoi",
                on_message=answer,
                on_stop=stopped,
                attachments=ui.Accept(accept=[".txt"]),
            ),
            ui.Text(f"{len(thread.messages)} messages", key="count"),
        )

    async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
        async with turn.reply() as reply:
            if turn.text == "slow":
                await reply.text("thinking")
                await asyncio.sleep(5)
                return
            await asyncio.sleep(0.08)  # long enough for one render while the turn is busy
            async with reply.reasoning() as r:
                await r.text("let me see")
            tool = await reply.tool("search", {"q": turn.text})
            await tool.output({"hits": 2})
            await reply.source("Doc A", url="https://example.invalid/a", snippet="...")
            for word in ("Hello", " ", "**world**"):
                await reply.text(word)
            await reply.component(ui.Badge("inline", key="b"))
            await reply.suggestions(["More?"])

    async def stopped(s: mw.Session, _: Any) -> None:
        s.toast("stopped")

    return app


def test_turn_streams_and_records(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        recv(ws)
        mount = recv(ws)
        chat = mount["nodes"]["root/main"]
        assert chat["props"]["messages"] == [] and chat["props"]["busy"] is False
        assert chat["props"]["on_message"] is True and chat["props"]["on_stop"] is True

        send(
            ws, {"type": "event", "node": "root/main", "name": "message", "payload": {"text": "hi"}}
        )
        msgs = collect(ws, lambda m: m.get("type") == "stream" and m["chunk"]["type"] == "finish")
        chunks = [m["chunk"] for m in msgs if m["type"] == "stream"]
        types = [c["type"] for c in chunks]
        assert types[:2] == ["start", "start-step"]
        assert (
            "reasoning-start" in types and "reasoning-delta" in types and "reasoning-end" in types
        )
        tool = next(c for c in chunks if c["type"] == "tool-input-available")
        assert tool["toolName"] == "search" and tool["input"] == {"q": "hi"}
        assert next(c for c in chunks if c["type"] == "tool-output-available")["output"] == {
            "hits": 2
        }
        assert next(c for c in chunks if c["type"] == "source-url")["title"] == "Doc A"
        deltas = [c["delta"] for c in chunks if c["type"] == "text-delta"]
        assert "".join(deltas) == "Hello **world**"
        assert types.count("text-start") == 1 and types.count("text-end") == 1
        assert next(c for c in chunks if c["type"] == "data-component")["data"]["slot"]
        assert next(c for c in chunks if c["type"] == "data-suggestions")["data"]["items"] == [
            "More?"
        ]
        assert types[-2:] == ["finish-step", "finish"]

        # Across the turn's patches: busy while streaming, then both messages as props.
        final = collect(
            ws,
            lambda m: any(
                op.get("id") == "root/count" and op.get("props", {}).get("content") == "2 messages"
                for op in m.get("ops", [])
                if op["op"] == "set"
            ),
        )
        merged: dict[str, Any] = {}
        busy_seen: list[bool] = []
        for m in msgs + final:
            for op in m.get("ops", []):
                if op["op"] == "set" and op["id"] == "root/main":
                    merged.update(op["props"])
                    if "busy" in op["props"]:
                        busy_seen.append(op["props"]["busy"])
        assert busy_seen[0] is True and busy_seen[-1] is False
        assert len(merged["messages"]) == 2
        assert list(merged["inline"].values())[0]["$node"].startswith("root/main/@inline.")
        session = next(iter(app.sessions.values()))
        thread = session.chat("main")
        assert [m.role for m in thread.messages] == ["user", "assistant"]
        assert thread.messages[1].text == "Hello **world**"
        assert [p["type"] for p in thread.messages[1].parts][:3] == [
            "reasoning",
            "tool-search",
            "source-url",
        ]
        assert thread.busy is False


def test_stop_cancels_the_turn(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        recv(ws)
        recv(ws)
        send(
            ws,
            {"type": "event", "node": "root/main", "name": "message", "payload": {"text": "slow"}},
        )
        collect(ws, lambda m: m.get("type") == "stream" and m["chunk"]["type"] == "text-delta")
        send(ws, {"type": "event", "node": "root/main", "name": "stop"})
        # The stop hook's toast and the stream's finish arrive in no fixed order.
        seen: dict[str, Any] = {"toast": False, "finish": None}

        def both(m: dict[str, Any]) -> bool:
            if m.get("type") == "command" and m.get("name") == "toast":
                seen["toast"] = True
            if m.get("type") == "stream" and m["chunk"]["type"] == "finish":
                seen["finish"] = m["chunk"]["finishReason"]
            return bool(seen["toast"]) and seen["finish"] is not None

        collect(ws, both)
        assert seen["finish"] == "stopped"
        session = next(iter(app.sessions.values()))
        thread = session.chat("main")
        assert thread.busy is False and thread.messages[-1].text == "thinking"


async def test_a_second_message_before_the_reply_starts_waits(tmp_path: Path) -> None:
    from millwork.protocol import Event
    from millwork.testing import TestApp

    turns: list[str] = []
    app = mw.App("c2", public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Chat(key="main", on_message=answer))

    async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
        turns.append(turn.text)
        await asyncio.sleep(0.05)  # a lookup before the reply starts
        async with turn.reply() as r:
            await r.text("ok")

    def message(text: str) -> Event:
        return Event(
            node="root/main", name="message", payload={"text": text, "files": [], "command": None}
        )

    async with TestApp(app).open("/") as page:
        await page.session.dispatch(message("one"))
        await page.session.dispatch(message("two"))
        await page.settle()
        assert turns == ["one"]
        assert "Wait for the current reply to finish." in page.toasts
        assert page.find("main").props["busy"] is False
        assert [m["role"] for m in page.find("main").props["messages"]] == ["user", "assistant"]
