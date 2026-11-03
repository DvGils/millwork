"""Tasks: sync and async work, progress into patches, cancellation, failure, ask."""

import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

import millwork as mw
from millwork import progress, ui


class State(BaseModel):
    run: Any = None
    partial: list[int] = []
    result: str | None = None
    asked: str | None = None
    confirmed: bool | None = None


def send(ws: Any, msg: dict[str, Any]) -> None:
    ws.send_text(json.dumps({"seq": 1, "msg": msg}))


def recv(ws: Any) -> dict[str, Any]:
    return json.loads(ws.receive_text())["msg"]


def hello(ws: Any) -> None:
    send(ws, {"type": "hello", "path": "/"})
    assert recv(ws)["type"] == "session"
    assert recv(ws)["type"] == "mount"


def drain_until(ws: Any, pred: Any, limit: int = 40) -> list[dict[str, Any]]:
    seen = []
    for _ in range(limit):
        m = recv(ws)
        seen.append(m)
        if pred(m):
            return seen
    raise AssertionError(f"not found in {seen}")


def slow_sync(n: int, pause: float = 0.01) -> str:
    p = progress()
    p.plan(["Lezen", "Rekenen"])
    with p.step("Lezen") as st:
        st.note(f"{n} items")
    with p.step("Rekenen"):
        for i in range(n):
            p.check()
            p.set((i + 1) / n, f"item {i + 1}")
            time.sleep(pause)
    return f"done {n}"


async def wipe(s: mw.Session[State], _: Any) -> None:
    s.state.result = "wiped"


def make_app(tmp_path: Path) -> mw.App:
    app = mw.App("t", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.Button("sync", key="sync", on_click=start_sync),
            ui.Button("async", key="async", on_click=start_async),
            ui.Button("fail", key="fail", on_click=start_failing),
            ui.Button("cancel", key="cancel", on_click=lambda s, _: s.state.run.cancel()),
            ui.Button("wipe", key="wipe", confirm="Wipe it?", on_click=wipe),
            ui.Table(
                rows=[{"id": 1, "n": "a"}],
                key="t",
                row_actions=[
                    ui.MenuItem(id="rm", label="Remove", destructive=True, confirm="Remove?")
                ],
                on_action=lambda s, p: s.state.__setattr__("result", f"rm {p[1]}"),
            ),
            ui.Button("ask", key="ask", on_click=do_ask),
            ui.Button("confirm", key="confirm", on_click=do_confirm),
            ui.Progress(key="p", task=st.run) if st.run else None,
            ui.Steps(key="steps", task=st.run) if st.run else None,
            ui.Text(st.result or "", key="result"),
            ui.Text(str(st.partial), key="partial"),
            ui.Text(st.asked or "", key="asked"),
            ui.Text(str(st.confirmed), key="confirmed"),
        )

    async def start_sync(s: mw.Session[State], _: Any) -> None:
        s.state.run = s.task(slow_sync, 5, 0.04, label="Sync work")
        s.state.result = await s.state.run

    async def start_async(s: mw.Session[State], _: Any) -> None:
        async def work() -> str:
            p = progress()
            for i in range(50):
                s.state.partial.append(i)
                p.set(i / 50)
                await __import__("asyncio").sleep(0.01)
            return "never"

        s.state.run = s.task(work(), label="Async work", key="async", replace=True)

    async def start_failing(s: mw.Session[State], _: Any) -> None:
        def boom() -> None:
            raise ValueError("kaput")

        s.state.run = s.task(boom, label="Breaking")

    async def do_ask(s: mw.Session[State], _: Any) -> None:
        class Answer(BaseModel):
            name: str

        answer = await s.ask(ui.Dialog(ui.Form(Answer, key="f"), title="Who?"))
        s.state.asked = answer.name if answer else "closed"

    async def do_confirm(s: mw.Session[State], _: Any) -> None:
        s.state.confirmed = await s.confirm("Sure?", description="Really.")

    return app


def node_props(msgs: list[dict[str, Any]], node: str) -> list[dict[str, Any]]:
    out = []
    for m in msgs:
        if m.get("type") == "patch":
            for op in m["ops"]:
                if op["op"] == "set" and op["id"] == node:
                    out.append(op["props"])
                if op["op"] == "add" and op["node"]["id"] == node:
                    out.append(op["node"]["props"])
    return out


def test_sync_task_reports_progress_and_result(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        send(ws, {"type": "event", "node": "root/sync", "name": "click"})
        msgs = drain_until(
            ws,
            lambda m: any(
                op.get("id") == "root/result" and op.get("props", {}).get("content") == "done 5"
                for op in m.get("ops", [])
                if op["op"] == "set"
            ),
        )
        snapshots = [p["task"] for p in node_props(msgs, "root/p") if "task" in p]
        assert snapshots[0]["status"] == "running" and snapshots[0]["label"] == "Sync work"
        last = snapshots[-1]
        assert last["status"] == "done" and last["progress"] == 1.0 and last["message"] == "item 5"
        assert [s["label"] for s in last["steps"]] == ["Lezen", "Rekenen"]
        assert last["steps"][0]["status"] == "done" and last["steps"][0]["note"] == "5 items"
        assert last["steps"][1]["status"] == "done"


def test_cancel_keeps_partial_state_and_replace_dedupes(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        send(ws, {"type": "event", "node": "root/async", "name": "click"})
        drain_until(ws, lambda m: "root/p" in json.dumps(m))
        time.sleep(0.08)
        send(ws, {"type": "event", "node": "root/cancel", "name": "click"})
        msgs = drain_until(
            ws,
            lambda m: any(
                op.get("props", {}).get("task", {}).get("status") == "cancelled"
                for op in m.get("ops", [])
                if op["op"] == "set"
            ),
        )
        partial = [p["content"] for p in node_props(msgs, "root/partial") if "content" in p]
        assert partial and partial[-1] != "[]"
        session = next(iter(app.sessions.values()))
        assert session.state.run.status == "cancelled" and len(session.state.partial) > 0
        assert session.state.partial == list(range(len(session.state.partial)))
        # Starting again with the same key replaces the old task.
        send(ws, {"type": "event", "node": "root/async", "name": "click"})
        drain_until(ws, lambda m: "root/p" in json.dumps(m))
        send(ws, {"type": "event", "node": "root/async", "name": "click"})
        time.sleep(0.05)
        running = [t for t in session.tasks if t.status == "running"]
        assert len(running) == 1


def test_unobserved_failure_toasts(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        send(ws, {"type": "event", "node": "root/fail", "name": "click"})
        msgs = drain_until(ws, lambda m: m.get("type") == "command" and m.get("name") == "toast")
        toast = msgs[-1]["args"]
        assert toast["tone"] == "destructive" and "Breaking failed: kaput" in toast["message"]
        session = next(iter(app.sessions.values()))
        assert session.state.run.status == "failed" and session.state.run.error.type == "ValueError"


def test_ask_and_confirm(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)
        send(ws, {"type": "event", "node": "root/ask", "name": "click"})
        msgs = drain_until(
            ws,
            lambda m: any(
                op["op"] == "add" and "@ask" in op["node"]["id"] for op in m.get("ops", [])
            ),
        )
        dialog = next(
            op["node"]
            for op in msgs[-1]["ops"]
            if op["op"] == "add" and op["node"]["type"] == "Dialog"
        )
        form = next(
            op["node"]
            for op in msgs[-1]["ops"]
            if op["op"] == "add" and op["node"]["type"] == "Form"
        )
        assert dialog["props"]["open"] is True and dialog["props"]["on_close"] is True
        # While the ask is open, other handlers still run (the lock is released).
        send(ws, {"type": "event", "node": "root/confirm", "name": "click"})
        msgs = drain_until(
            ws,
            lambda m: any(
                op["op"] == "add" and op["node"]["props"].get("title") == "Sure?"
                for op in m.get("ops", [])
            ),
        )
        confirm_dialog = next(
            op["node"]
            for op in msgs[-1]["ops"]
            if op["op"] == "add" and op["node"]["props"].get("title") == "Sure?"
        )
        ok_button = next(
            op["node"]["id"]
            for op in msgs[-1]["ops"]
            if op["op"] == "add" and op["node"]["props"].get("label") == "OK"
        )
        send(ws, {"type": "event", "node": ok_button, "name": "click"})
        drain_until(
            ws,
            lambda m: any(
                op.get("id") == "root/confirmed" and op.get("props", {}).get("content") == "True"
                for op in m.get("ops", [])
                if op["op"] == "set"
            ),
        )
        assert confirm_dialog["id"] != dialog["id"]
        # A form submit inside the ask answers it with a validated model.
        send(
            ws, {"type": "event", "node": form["id"], "name": "submit", "payload": {"name": "Ada"}}
        )
        msgs = drain_until(
            ws,
            lambda m: any(
                op.get("id") == "root/asked" and op.get("props", {}).get("content") == "Ada"
                for op in m.get("ops", [])
                if op["op"] == "set"
            ),
        )
        assert any(
            op["op"] == "remove" and op["id"] == dialog["id"]
            for m in msgs
            for op in m.get("ops", [])
        )
        # Closing answers None.
        send(ws, {"type": "event", "node": "root/ask", "name": "click"})
        msgs = drain_until(
            ws,
            lambda m: any(
                op["op"] == "add" and op["node"]["type"] == "Dialog" for op in m.get("ops", [])
            ),
        )
        dialog2 = next(
            op["node"]
            for op in msgs[-1]["ops"]
            if op["op"] == "add" and op["node"]["type"] == "Dialog"
        )
        send(ws, {"type": "event", "node": dialog2["id"], "name": "close"})
        drain_until(
            ws,
            lambda m: any(
                op.get("id") == "root/asked" and op.get("props", {}).get("content") == "closed"
                for op in m.get("ops", [])
                if op["op"] == "set"
            ),
        )


def test_button_confirm_and_destructive_action_ask_first(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        hello(ws)

        def dialog_with(title: str) -> tuple[str, str]:
            msgs = drain_until(
                ws,
                lambda m: any(
                    op["op"] == "add" and op["node"]["props"].get("title") == title
                    for op in m.get("ops", [])
                ),
            )
            labels = {
                op["node"]["props"].get("label"): op["node"]["id"]
                for op in msgs[-1]["ops"]
                if op["op"] == "add" and op["node"]["type"] == "Button"
            }
            return labels["OK"], labels["Cancel"]

        # Cancel: the handler never runs; the dialog goes away.
        send(ws, {"type": "event", "node": "root/wipe", "name": "click"})
        ok, cancel = dialog_with("Wipe it?")
        send(ws, {"type": "event", "node": cancel, "name": "click"})
        drain_until(
            ws,
            lambda m: any(op["op"] == "remove" and "@ask" in op["id"] for op in m.get("ops", [])),
        )
        assert app.sessions and next(iter(app.sessions.values())).state.result is None
        # OK: the handler runs after the answer.
        send(ws, {"type": "event", "node": "root/wipe", "name": "click"})
        ok, cancel = dialog_with("Wipe it?")
        send(ws, {"type": "event", "node": ok, "name": "click"})
        drain_until(ws, lambda m: next(iter(app.sessions.values())).state.result == "wiped")
        # A row action with a confirm asks it, as a destructive dialog for a destructive item.
        send(ws, {"type": "event", "node": "root/t", "name": "action", "payload": ["rm", 1]})
        ok, cancel = dialog_with("Remove?")
        send(ws, {"type": "event", "node": ok, "name": "click"})
        drain_until(ws, lambda m: next(iter(app.sessions.values())).state.result == "rm 1")


async def test_parallel_steps_stay_siblings_and_a_timeout_stops_the_worker(tmp_path: Path) -> None:
    import asyncio

    from millwork.testing import TestApp

    app = mw.App("ps", state=State, public=None, bundle_dir=tmp_path)
    ticks: list[int] = []

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("go", key="go", on_click=go), ui.Button("slow", key="slow", on_click=slow)
        )

    async def council() -> None:
        p = progress()

        async def model(name: str) -> None:
            with p.step(name):
                await asyncio.sleep(0.01)
                with p.step(f"{name} child"):
                    p.log("line")

        with p.step("council"):
            await asyncio.gather(model("a"), model("b"))

    async def go(s: mw.Session[State], _: Any) -> None:
        s.state.run = s.task(council(), label="Council")

    def grind() -> None:
        p = progress()
        for i in range(100):
            p.check()
            ticks.append(i)
            time.sleep(0.01)

    async def slow(s: mw.Session[State], _: Any) -> None:
        s.state.run = s.task(grind, label="Grind", timeout=0.05)

    # The timeout is a failure nobody awaits, which a strict harness would raise.
    async with TestApp(app, strict=False).open("/") as page:
        await page.click("go")
        task = page.state.run
        assert task.ok
        [root] = task.steps
        assert root.label == "council" and sorted(c.label for c in root.children) == ["a", "b"]
        for child in root.children:
            assert [g.label for g in child.children] == [f"{child.label} child"]
            assert child.children[0].lines == ["line"] and child.status == "done"

        await page.click("slow")
        task = page.state.run
        assert task.status == "failed" and task.cancelled and task.error.type == "TimeoutError"
        await asyncio.sleep(0.03)
        n = len(ticks)
        await asyncio.sleep(0.1)  # the thread is the thing under test: it stopped at its check
        assert len(ticks) == n and n < 100


async def test_a_task_may_live_in_a_state_model(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    class Holder(BaseModel):
        job: mw.Task | None = None

    app = mw.App("th", state=Holder, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[Holder]) -> ui.Component:
        return ui.Page(ui.Button("go", key="go", on_click=start))

    def start(s: mw.Session[Holder], _: Any) -> None:
        s.state.job = s.task(lambda: 1, label="One")

    async with TestApp(app).open("/") as page:
        await page.click("go")
        assert page.state.job is not None and page.state.job.ok
        dumped = json.loads(page.state.model_dump_json())
        assert dumped["job"]["label"] == "One" and dumped["job"]["status"] == "done"
    with pytest.raises(ValueError):
        Holder(job="not a task")  # type: ignore[arg-type]
