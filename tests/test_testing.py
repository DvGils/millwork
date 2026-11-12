"""millwork.testing: a session driven without a socket, observed on its wire."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

import millwork as mw
from millwork import progress, ui
from millwork.testing import TestApp


class Settings(BaseModel):
    project_name: str = Field(min_length=2)
    trap: bool = True
    attachment: mw.FileRef | None = None


class State(BaseModel):
    count: int = 0
    settings: Settings | None = None
    selected: list[int] = []
    uploaded: list[str] = []
    run: Any = None
    confirmed: bool | None = None
    asked: str | None = None
    connected: bool = False


def work(n: int) -> str:
    p = progress()
    for i in range(n):
        p.set((i + 1) / n, f"step {i + 1}")
    return f"done {n}"


def make_app(tmp_path: Path) -> mw.App:
    app = mw.App("t", state=State, public=None, bundle_dir=tmp_path, files=mw.Files(tmp_path))

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.Text(f"count {st.count}", key="count"),
            ui.Button("more", key="more", on_click=more),
            ui.Button("wipe", key="wipe", confirm="Wipe?", on_click=wipe),
            ui.Button("ask", key="ask", on_click=ask_name),
            ui.Button("run", key="run", on_click=lambda s, _: s.task(work, 3, label="Work")),
            ui.Form(Settings, key="settings", on_submit=save, disabled=not st.connected),
            ui.Table(
                rows=[{"id": 1, "n": "a"}, {"id": 2, "n": "b"}],
                key="rows",
                selection="rows",
                selected=st.selected,
                on_select=lambda s, keys: s.state.__setattr__("selected", keys),
                row_actions=[ui.MenuItem(id="rm", label="Remove")],
                on_action=lambda s, p: s.toast(f"removed {p[1]}"),
            ),
            ui.FileUpload(key="up", accept=[".txt"], on_upload=uploaded),
            ui.Chat(key="chat", on_message=reply),
            ui.Text(f"answer {st.asked}", key="answer"),
            ui.Text("saved" if st.settings else "unsaved", key="saved"),
        )

    @home.connect
    async def connect(s: mw.Session[State]) -> None:
        s.state.connected = True

    @app.page("/other", public=True)
    def other(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("elsewhere", key="where"))

    return app


async def more(s: mw.Session[State], _: Any) -> None:
    s.state.count += 1


async def wipe(s: mw.Session[State], _: Any) -> None:
    s.state.count = -1


async def ask_name(s: mw.Session[State], _: Any) -> None:
    class Name(BaseModel):
        name: str = Field(min_length=2)

    answer = await s.ask(ui.Dialog(ui.Form(Name, key="q"), title="Name?"))
    s.state.asked = answer.name if answer else "none"


async def save(s: mw.Session[State], value: Settings) -> None:
    if value.project_name == "taken":
        raise ui.FormIssues([("/project_name", "already used")])
    s.state.settings = value


async def uploaded(s: mw.Session[State], refs: list[mw.FileRef]) -> None:
    s.state.uploaded = [r.name for r in refs]


async def reply(s: mw.Session[State], turn: mw.ChatTurn) -> None:
    async with turn.reply() as r:
        await r.text(f"you said {turn.text}")


async def test_open_click_and_patch(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with TestApp(app).open("/") as page:
        assert page.state.connected is True
        assert page.find("count").props["content"] == "count 0"
        assert page.messages[0].type == "session" and page.messages[1].type == "mount"
        await page.click(page.find("more"))
        assert page.find("count").props["content"] == "count 1"
        patch = page.last_patch
        assert patch is not None and any(
            op.op == "set" and op.id.endswith("/count") for op in patch.ops
        )
        assert page.find(ui.Button).type == "Button" and len(page.find_all(ui.Button)) == 4
        with pytest.raises(LookupError):
            page.find("nope")
    assert app.sessions == {}


async def test_state_skips_connect_and_navigate(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with TestApp(app).open("/", state=State(count=7)) as page:
        assert page.state.connected is False and "count 7" in page.text()
        await page.navigate("/other")
        assert page.find("where").props["content"] == "elsewhere"
        assert page.commands[-1].name == "navigate" and page.commands[-1].args["path"] == "/other"


async def test_form_table_upload_and_download(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    async with TestApp(app).open("/") as page:
        form = page.find(ui.Form)
        await page.submit(form, {"project_name": "x"})
        assert page.commands[-1].name == "form_issues"
        assert page.commands[-1].args["issues"][0]["pointer"] == "/project_name"
        assert page.state.settings is None
        ref = await page.upload(form, tmp_path / "a.txt", field="/attachment")
        await page.submit(form, Settings(project_name="fine", attachment=ref))
        assert page.state.settings is not None
        assert page.state.settings.attachment is not None
        assert page.state.settings.attachment.path.read_text() == "hello"
        assert page.find("saved").props["content"] == "saved"

        table = page.find(ui.Table)
        assert table.rows[1]["n"] == "b"
        await page.select(table, [2])
        assert page.state.selected == [2]
        await page.action(table, "rm", 2)
        assert page.toasts[-1] == "removed 2"

        await page.upload("up", tmp_path / "a.txt")
        assert page.state.uploaded == ["a.txt"]
        with pytest.raises(mw.files.Reject):
            await page.upload("up", tmp_path / "b.bin")


async def test_task_ask_confirm_and_chat(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with TestApp(app).open("/") as page:
        await page.click("run")
        task = page.session.tasks[-1]
        assert task.ok and task.result == "done 3"
        assert task.progress == 1.0

        # A confirm leaves the handler waiting; the test answers it.
        await page.click("wipe")
        assert page.state.count == 0 and page.find(ui.Dialog).props["title"] == "Wipe?"
        await page.answer(False)
        assert page.state.count == 0 and not page.find_all(ui.Dialog)
        await page.click("wipe")
        await page.answer(True)
        assert page.state.count == -1

        await page.click("ask")
        assert page.find(ui.Dialog).props["title"] == "Name?"
        await page.answer({"name": "A"})  # too short: the ask stays open
        assert page.commands[-1].name == "form_issues" and page.find_all(ui.Dialog)
        await page.answer({"name": "Ada"})
        assert page.state.asked == "Ada" and page.find("answer").props["content"] == "answer Ada"
        await page.click("ask")
        await page.answer(None)
        assert page.state.asked == "none"

        await page.send("chat", "hi")
        kinds = [c["type"] for c in page.stream]
        assert kinds[0] == "start" and "text-delta" in kinds and kinds[-1] == "finish"
        assert "".join(c.get("delta", "") for c in page.stream) == "you said hi"
        messages = page.find("chat").props["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]


async def test_settle_leaves_delayed_tasks_and_tasks_waiting_on_the_user(tmp_path: Path) -> None:
    app = mw.App("st", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("later", key="later", on_click=later),
            ui.Button("ask", key="ask", on_click=asker),
        )

    async def later(s: mw.Session[State], _: Any) -> None:
        s.state.run = s.later(600, lambda: None)

    async def asker(s: mw.Session[State], _: Any) -> None:
        async def work() -> None:
            s.state.confirmed = await s.confirm("Go?")

        s.state.run = s.task(work(), label="asking")

    async with TestApp(app).open("/") as page:
        await page.click("later")
        assert page.state.run.status == "pending"
        await page.click("ask")
        assert page.find(ui.Dialog).props["title"] == "Go?"
        await page.answer(True)
        assert page.state.confirmed is True and page.state.run.ok


async def test_menu_items_confirm_everywhere(tmp_path: Path) -> None:
    app = mw.App("m", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.DropdownMenu(
                key="menu",
                trigger=ui.Button("More"),
                items=[
                    ui.MenuItem(id="rm", label="Remove", destructive=True),
                    ui.MenuItem(id="archive", label="Archive", confirm="Archive the file?"),
                    ui.MenuItem(id="open", label="Open"),
                ],
                on_select=lambda s, item: s.state.__setattr__("asked", item),
            ),
            ui.Table(
                rows=[{"id": 1}],
                key="rows",
                row_actions=[
                    ui.MenuItem(id="rm", label="Remove", destructive=True, confirm="Drop row?")
                ],
                on_action=lambda s, p: s.state.__setattr__("asked", f"row {p[1]}"),
            ),
        )

    async with TestApp(app).open("/") as page:
        # A destructive look asks nothing by itself; a confirm does.
        await page.event("menu", "select", "rm")
        assert not page.find_all(ui.Dialog) and page.state.asked == "rm"
        await page.event("menu", "select", "archive")
        assert page.find(ui.Dialog).props["title"] == "Archive the file?"
        await page.answer(False)
        assert page.state.asked == "rm"
        await page.event("menu", "select", "archive")
        assert page.find(ui.Dialog).props["title"] == "Archive the file?"
        await page.answer(True)
        assert page.state.asked == "archive"
        await page.event("menu", "select", "open")
        assert not page.find_all(ui.Dialog) and page.state.asked == "open"
        await page.event("rows", "action", ["rm", 1])
        assert page.find(ui.Dialog).props["title"] == "Drop row?"
        await page.answer(True)
        assert page.state.asked == "row 1"


async def test_find_sees_a_keyed_component_in_a_slot(tmp_path: Path) -> None:
    app = mw.App("slot", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Card("body", footer=ui.Button("Import", key="import", on_click=more)))

    def more(s: mw.Session[State], _: Any) -> None:
        s.state.count += 1

    async with TestApp(app).open("/") as page:
        assert page.find("import").id == "root/0:Card/@footer"
        await page.click("import")
        assert page.state.count == 1


async def test_strict_harness_raises_what_the_app_raised(tmp_path: Path) -> None:
    app = mw.App("strict", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        if s.state.count > 1:
            raise RuntimeError("no page for that")
        return ui.Page(ui.Button("more", key="more", on_click=more))

    def more(s: mw.Session[State], _: Any) -> None:
        s.state.count += 1
        if s.state.count == 1:
            raise ValueError("the handler broke")

    with pytest.raises(ValueError, match="the handler broke") as caught:
        async with TestApp(app).open("/") as page:
            await page.click("more")
    assert any("click handler" in note for note in caught.value.__notes__)

    # Not strict: the failure stays in the log and on the page, as a running app has it.
    async with TestApp(app, strict=False).open("/") as page:
        await page.click("more")
        assert page.state.count == 1 and page.toasts == ["Something went wrong."]
        await page.click("more")
        assert [where for where, _ in page.failures] == [
            "the click handler on root/more",
            "the page function of /",
        ]
        assert isinstance(page.failures[1][1], RuntimeError)


async def test_a_page_that_fails_to_render_raises_in_the_test(tmp_path: Path) -> None:
    app = mw.App("strict2", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("x", on_click=lambda s: None))  # type: ignore[arg-type]

    with pytest.raises(TypeError, match=r"on_click takes a handler of \(session, payload\)"):
        async with TestApp(app).open("/"):
            pass


async def test_settle_skips_a_quiet_task_and_names_what_still_runs(tmp_path: Path) -> None:
    import asyncio

    app = mw.App("quiet", state=State, public=None, bundle_dir=tmp_path)
    changed = asyncio.Event()

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Text(f"count {s.state.count}", key="count"),
            ui.Button("loud", key="loud", on_click=loud),
        )

    def loud(s: mw.Session[State], _: Any) -> None:
        s.task(asyncio.sleep(30), label="sleep")

    @home.connect
    def follow(s: mw.Session[State]) -> None:
        s.task(watch(s), label="Following", quiet=True)

    async def watch(s: mw.Session[State]) -> None:
        while True:
            await changed.wait()
            changed.clear()
            s.state.count += 1
            s.refresh()

    async with TestApp(app).open("/") as page:
        assert page.find("count").props["content"] == "count 0"
        changed.set()
        await page.settle()
        assert page.find("count").props["content"] == "count 1"
        # A loud task is waited for, so the click is dispatched without settling.
        from millwork.protocol import Event

        session = page.session
        session.event(Event(node=page.find("loud").id, name="click"))
        with pytest.raises(RuntimeError, match="did not settle in 0.2 s; still running: task "):
            await page.settle(timeout=0.2)
        page.session.tasks[-1].cancel()
        await page.settle()


async def test_a_toast_action_can_be_pressed(tmp_path: Path) -> None:
    app = mw.App("toast", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("delete", key="delete", on_click=delete))

    def delete(s: mw.Session[State], _: Any) -> None:
        s.state.count -= 1
        s.toast(
            "Deleted.", action=("Undo", lambda s, _: setattr(s.state, "count", s.state.count + 1))
        )

    async with TestApp(app).open("/") as page:
        await page.click("delete")
        assert page.state.count == -1
        await page.toast_action("Undo")
        assert page.state.count == 0
        with pytest.raises(LookupError, match="no toast with a 'Redo' button"):
            await page.toast_action("Redo")


async def test_a_failed_task_is_reported_and_a_toast_button_presses_once(tmp_path: Path) -> None:
    app = mw.App("fail", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("boom", key="boom", on_click=boom),
            ui.Button("delete", key="delete", on_click=delete),
        )

    def boom(s: mw.Session[State], _: Any) -> None:
        s.task(explode, label="Explode")  # not awaited: the failure is nobody's but the task's

    def explode() -> None:
        raise ValueError("the task broke")

    def delete(s: mw.Session[State], _: Any) -> None:
        s.toast("Deleted.", action=("Undo", lambda s, _: setattr(s.state, "count", 1)))

    with pytest.raises(ValueError, match="the task broke") as caught:
        async with TestApp(app).open("/") as page:
            await page.click("boom")
    assert any("the task 'Explode'" in note for note in caught.value.__notes__)

    async with TestApp(app, strict=False).open("/") as page:
        await page.click("boom")
        assert page.toasts == ["Explode failed: the task broke"]
        assert [where for where, _ in page.failures] == ["the task 'Explode'"]
        await page.click("delete")
        await page.toast_action("Undo")
        assert page.state.count == 1
        with pytest.raises(LookupError, match="already pressed"):
            await page.toast_action("Undo")


async def test_a_click_on_a_download_downloads_and_text_skips_choices(tmp_path: Path) -> None:
    app = mw.App("dl", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Download(label="Report", filename="report.csv", content="a,b\n", key="dl"),
            ui.Text("Quarterly numbers", variant="heading", align="center", tone="muted"),
            ui.Button("Go", variant="outline", size="sm", key="go", on_click=lambda s, _: None),
        )

    async with TestApp(app).open("/") as page:
        await page.click("dl")
        assert [c.name for c in page.commands] == ["download"]
        assert page.commands[0].args["filename"] == "report.csv"
        text = page.text()
        assert "Quarterly numbers" in text and "Report" in text and "Go" in text
        for choice in ("heading", "center", "muted", "outline", "sm"):
            assert choice not in text.split("\n"), choice


async def test_a_handler_that_ends_its_session_lets_the_close_hook_finish(tmp_path: Path) -> None:
    app = mw.App("end", state=State, public=None, bundle_dir=tmp_path)
    seen: list[str] = []

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Button("leave", key="leave", on_click=leave))

    @home.close
    async def closed(s: mw.Session[State]) -> None:
        seen.append("close started")
        await asyncio.sleep(0)
        seen.append("close finished")

    async def leave(s: mw.Session[State], _: Any) -> None:
        await s.end("Done here.")
        seen.append("handler went on")

    async def work(s: mw.Session[State]) -> None:
        await asyncio.sleep(0)
        await s.end("The work is done.")
        seen.append("work went on")

    # Nothing after the line that ends the session runs in the handler, and
    # the page's close hook runs to its end all the same.
    async with TestApp(app).open("/") as page:
        await page.click("leave")
        assert seen == ["close started", "close finished"]
        assert page.session.closed and page.session.gone.done()
        assert page.messages[-1].message == "Done here." and page.messages[-1].fatal

    # The same goes for a task that ends its session.
    seen.clear()
    async with TestApp(app).open("/") as page:
        task = page.session.task(work(page.session), label="Work")
        await page.settle()
        assert seen == ["close started", "close finished"]
        assert task.status == "cancelled"


async def test_a_close_hook_that_raises_fails_a_strict_test(tmp_path: Path) -> None:
    app = mw.App("hook", state=State, public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("home"))

    @home.close
    def closed(s: mw.Session[State]) -> None:
        raise RuntimeError("close hook broke")

    with pytest.raises(RuntimeError, match="close hook broke") as caught:
        async with TestApp(app).open("/"):
            pass
    assert any("the close hook of /" in note for note in caught.value.__notes__)

    async with TestApp(app, strict=False).open("/") as page:
        pass
    assert [where for where, _ in page.failures] == ["the close hook of /"]


async def test_finding_inside_a_node_custom_components_and_menu_choices(tmp_path: Path) -> None:
    app = mw.App("f", state=State, public=None, bundle_dir=tmp_path, components=None)

    def card(name: str) -> ui.Component:
        return ui.Card(
            ui.Text(name, key="title"),
            key=name,
            footer=ui.Button(
                "Save", key="save", on_click=lambda s, _: setattr(s.state, "asked", name)
            ),
        )

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            card("first"),
            card("second"),
            ui.Custom("Gauge", key="gauge", props={"value": 3}),
            ui.Custom("Dial", ui.Text("inside", key="title")),
            ui.DropdownMenu(
                key="menu",
                trigger=ui.Button("More"),
                items=[
                    ui.MenuItem(id="open", label="Open"),
                    ui.MenuItem(id="archive", label="Archive it", confirm="Archive?"),
                    ui.MenuItem(id="locked", label="Locked", disabled=True),
                ],
                on_select=lambda s, item: setattr(s.state, "asked", item),
            ),
        )

    async with TestApp(app).open("/") as page:
        # Both cards have a "save" and a "title": the card to look in tells them apart.
        assert len(page.find_all("save")) == 2
        await page.click(page.find("save", within="second"))
        assert page.state.asked == "second"
        first = page.find("first")
        assert page.find("title", within=first).props["content"] == "first"
        assert [b.id for b in page.find_all(ui.Button, within=first)] == [
            page.find("save", within="first").id
        ]
        with pytest.raises(LookupError, match="no nope in 'first'"):
            page.find("nope", within="first")
        # A custom component is found by the class it is written with, and
        # its type is the name it goes by.
        assert [c.type for c in page.find_all(ui.Custom)] == ["Gauge", "Dial"]
        assert page.find(ui.Custom).props["value"] == 3
        dial = page.find_all(ui.Custom)[1]
        assert page.find("title", within=dial).props["content"] == "inside"
        # A menu choice, by id or by label, with the question an item asks first.
        await page.choose("menu", "open")
        assert page.state.asked == "open"
        await page.choose("menu", "Archive it")
        assert page.find(ui.Dialog).props["title"] == "Archive?"
        await page.answer(True)
        assert page.state.asked == "archive"
        with pytest.raises(LookupError, match="has no item 'nope'"):
            await page.choose("menu", "nope")
        with pytest.raises(LookupError, match="is disabled"):
            await page.choose("menu", "locked")
        assert page.state.asked == "archive"


async def test_confirm_buttons_speak_the_themes_language(tmp_path: Path) -> None:
    from millwork.theme import Theme

    app = mw.App(
        "c",
        state=State,
        public=None,
        bundle_dir=tmp_path,
        theme=Theme(strings={"ok": "Doe het", "cancel": "Laat maar"}),
    )

    async def own_words(s: mw.Session[State], _: Any) -> None:
        await s.confirm("Sure?", ok="Yes", cancel="No")

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Button("Wipe", key="wipe", confirm="Wipe it?", on_click=lambda s, _: None),
            ui.Button("Ask", key="ask", on_click=own_words),
        )

    async with TestApp(app).open("/") as page:
        await page.click("wipe")
        labels = [b.props["label"] for b in page.find_all(ui.Button, within=page.find(ui.Dialog))]
        assert labels == ["Laat maar", "Doe het"]
        await page.answer(False)
        # Words given to the call win over the theme's.
        await page.click("ask")
        labels = [b.props["label"] for b in page.find_all(ui.Button, within=page.find(ui.Dialog))]
        assert labels == ["No", "Yes"]
        await page.answer(True)


async def test_finding_by_a_prop_and_asking_for_the_print_dialog(tmp_path: Path) -> None:
    app = mw.App("p", state=State, public=None, bundle_dir=tmp_path)

    def print_expanded(s: mw.Session[State], _: Any) -> None:
        s.state.count = 1
        s.print()

    @app.page("/other")
    def other(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("the other page", key="t"))

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Card(ui.Button("Delete", key="a", on_click=lambda s, _: None), title="First"),
            ui.Button("Go", href="/other", key="go"),
            ui.Button("Out", href="https://example.com", key="out"),
            ui.Link(label="Elsewhere", href="/other", key="link"),
            ui.Card(
                ui.Button("Delete", key="b", variant="destructive", on_click=lambda s, _: None),
                ui.Button("Print", on_click=print_expanded),
                ui.Text("expanded", key="x") if s.state.count else None,
                title="Second",
            ),
            ui.Select(options=["1", "2"], placeholder="Score", key="score"),
        )

    async with TestApp(app).open("/") as page:
        assert page.find(ui.Button, label="Print").props["label"] == "Print"
        assert len(page.find_all(ui.Button, label="Delete")) == 2
        assert page.find(ui.Button, label="Delete", variant="destructive").id.endswith("/b")
        assert page.find(ui.Select, placeholder="Score").id.endswith("/score")
        second = page.find(ui.Card, title="Second")
        assert page.find(ui.Button, label="Delete", within=second).id.endswith("/b")
        with pytest.raises(LookupError, match="no Button with label='Nope' on the page"):
            page.find(ui.Button, label="Nope")
        assert page.find_all(ui.Button, label="Delete", size="lg") == []
        # The dialog is asked for after the page was drawn again, so what
        # the handler changed first is on the page that prints.
        await page.click(page.find(ui.Button, label="Print"))
        assert [m.type for m in page.messages[-2:]] == ["patch", "command"]
        assert page.commands[-1].name == "print" and page.find_all("x")
        # A button that leaves the app does nothing to the session, and one
        # that goes to a page of the app takes the session there, like a link.
        await page.click("out")
        assert page.session.path == "/" and not page.failures
        await page.click("go")
        assert page.session.path == "/other"
        await page.navigate("/")
        await page.click("link")
        assert page.find("t").props["content"] == "the other page"


class Acts(BaseModel):
    box: bool = False
    held: list[bool] = []
    switch: bool = False
    refused: list[dict[str, str]] = []
    uploaded: list[str] = []
    clicks: int = 0
    hidden: bool = False
    tab: str = "a"
    heard: list[str] = []


class Note(BaseModel):
    text: str = ""
    file: mw.FileRef | None = None


def acting_app(tmp_path: Path) -> mw.App:
    app = mw.App("acts", state=Acts, public=None, bundle_dir=tmp_path, files=mw.Files(tmp_path))

    def uploaded(s: mw.Session[Acts], refs: list[mw.FileRef]) -> None:
        s.state.uploaded += [r.name for r in refs]

    def hear(what: str) -> Any:
        return lambda s, _: s.state.heard.append(what)

    @app.page("/")
    def home(s: mw.Session[Acts]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.Checkbox(
                checked=st.box, on_change=lambda s, v: setattr(s.state, "box", v), key="box"
            ),
            # It keeps its own value, in the tab, for as long as it is on the page.
            None
            if st.hidden
            else ui.Checkbox(
                default_checked=True, on_change=lambda s, v: s.state.held.append(v), key="held"
            ),
            ui.Button(
                "hide", key="hide", on_click=lambda s, _: setattr(s.state, "hidden", not st.hidden)
            ),
            ui.Switch(
                checked=st.switch, on_change=lambda s, v: setattr(s.state, "switch", v), key="sw"
            ),
            ui.Checkbox(key="deaf"),
            ui.Text("words", key="words"),
            ui.Button("off", key="off", disabled=True, on_click=count_click),
            ui.Button("gone", key="gone", disabled=True, href="/other"),
            ui.Button("on", key="on", on_click=count_click),
            ui.Button("spins", key="spins", loading=True, on_click=count_click),
            ui.Button("unseen", key="unseen", hidden=True, on_click=count_click),
            ui.Custom("Ping", events={"ping": hear("pinged")}, hidden=True, key="ping"),
            ui.FileUpload(key="veiled", hidden=True, on_upload=uploaded),
            ui.Chat(key="unheard", hidden=True, attachments=ui.Accept(), on_message=hear("told")),
            ui.Chat(key="mute"),
            ui.Button("save", key="save", form="note"),
            ui.Form(Note, key="note", on_submit=hear("note saved")),
            ui.Tabs(
                ui.Tab("a", id="a", label="A"),
                ui.Tab("b", id="b", label="B"),
                value=st.tab,
                key="stuck",
            ),
            ui.FileUpload(
                accept=[".txt"],
                max_size_mb=1,
                on_upload=uploaded,
                on_reject=lambda s, r: s.state.refused.append(r),
                key="told",
            ),
            ui.FileUpload(accept=[".txt"], on_upload=uploaded, key="untold"),
            ui.FileUpload(accept=[".txt"], key="kept"),
            ui.FileUpload(
                disabled=True, on_reject=lambda s, r: s.state.refused.append(r), key="shut"
            ),
            ui.Chat(key="plain", on_message=hear("message")),
            ui.Chat(key="busy", disabled=True, on_message=hear("message"), on_stop=hear("stop")),
            ui.Form(
                Note, key="shown", read_only=True, cancel="Close", on_cancel=hear("shown closed")
            ),
            ui.Form(
                Note, key="frozen", disabled=True, cancel="Close", on_cancel=hear("frozen closed")
            ),
        )

    def count_click(s: mw.Session[Acts], _: Any) -> None:
        s.state.clicks += 1

    @app.page("/other")
    def other(s: mw.Session[Acts]) -> ui.Component:
        return ui.Page(ui.Text("other"))

    return app


async def test_a_click_toggles_a_checkbox_and_a_switch(tmp_path: Path) -> None:
    async with TestApp(acting_app(tmp_path)).open("/") as page:
        await page.click("box")
        assert page.state.box is True
        await page.click("box")
        assert page.state.box is False
        await page.click("sw")
        assert page.state.switch is True
        # One that keeps its own value holds it in the tab, where a test
        # cannot read it. The test says what it turns to.
        with pytest.raises(LookupError, match=r"keeps its own value.*page\.change"):
            await page.click("held")
        await page.change("held", False)
        await page.change("held", True)
        assert page.state.held == [False, True]


async def test_an_action_the_page_does_not_take_fails_the_test(tmp_path: Path) -> None:
    async with TestApp(acting_app(tmp_path)).open("/") as page:
        with pytest.raises(LookupError, match=r"<Text root/words> has no handler for click"):
            await page.click("words")
        with pytest.raises(LookupError, match="has no handler for change"):
            await page.change("deaf", True)
        with pytest.raises(LookupError, match="has no handler for wave"):
            await page.event("on", "wave")
        with pytest.raises(LookupError, match=r"<Button root/off> is disabled"):
            await page.click("off")
        # A disabled button that is a link goes nowhere.
        with pytest.raises(LookupError, match=r"<Button root/gone> is disabled"):
            await page.click("gone")
        assert page.session.path == "/"
        # Nor can a button that shows a spinner be pressed, or one that is hidden.
        with pytest.raises(LookupError, match="is loading"):
            await page.click("spins")
        with pytest.raises(LookupError, match="is hidden"):
            await page.click("unseen")
        # A chat that hears no message has its field switched off in a tab.
        with pytest.raises(LookupError, match="has no handler for message"):
            await page.send("mute", "hello")
        assert page.state.clicks == 0
        # Tabs whose choice the page holds, with nothing to hear a change.
        with pytest.raises(LookupError, match="has no handler for change"):
            await page.change("stuck", "b")
        # A button that submits a form: the draft is the test's to give.
        with pytest.raises(LookupError, match=r"submits the form note.*page\.submit"):
            await page.click("save")
        await page.click("on")
        assert page.state.clicks == 1
    # Not a matter of strictness, which is about what the app's code raises.
    async with TestApp(acting_app(tmp_path), strict=False).open("/") as page:
        with pytest.raises(LookupError):
            await page.click("words")


async def test_what_a_disabled_chat_and_a_form_that_takes_no_submit_still_take(
    tmp_path: Path,
) -> None:
    async with TestApp(acting_app(tmp_path)).open("/") as page:
        # A disabled chat starts no reply, and its reply can still be stopped:
        # the tab shows the button, and an app disables a chat while it replies.
        with pytest.raises(LookupError, match="is disabled"):
            await page.send("busy", "hello")
        with pytest.raises(LookupError, match="is disabled"):
            await page.event("busy", "regenerate", {"id": "m1"})
        await page.stop("busy")
        # A form that takes no submit can still be left.
        with pytest.raises(LookupError, match="is read-only"):
            await page.submit("shown", {"text": "x"})
        await page.event("shown", "cancel")
        with pytest.raises(LookupError, match="is disabled"):
            await page.submit("frozen", {"text": "x"})
        await page.event("frozen", "cancel")
        assert page.state.heard == ["stop", "shown closed", "frozen closed"]


async def test_a_custom_component_that_is_hidden_can_still_emit(tmp_path: Path) -> None:
    async with TestApp(acting_app(tmp_path)).open("/") as page:
        # A tab keeps a hidden component running, so what it emits arrives.
        await page.event("ping", "ping", "hello")
        assert page.state.heard == ["pinged"]
        # An event it has no handler for is still one the page does not take.
        with pytest.raises(LookupError, match="has no handler for wave"):
            await page.event("ping", "wave")


async def test_a_hidden_node_takes_no_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    async with TestApp(acting_app(tmp_path)).open("/") as page:
        with pytest.raises(LookupError, match="is hidden"):
            await page.upload("veiled", tmp_path / "a.txt")
        with pytest.raises(LookupError, match="is hidden"):
            await page.send("unheard", "see this", files=[tmp_path / "a.txt"])
        # Nothing was kept of a file that could not have been sent.
        assert page.state.uploaded == [] and page.state.heard == []
        assert not list(page.session.files.all())


async def test_a_refused_upload_is_told_to_on_reject_and_to_the_test(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    (tmp_path / "big.txt").write_text("x" * (1024 * 1024 + 1))
    async with TestApp(acting_app(tmp_path)).open("/") as page:
        # The app is told as a tab tells it, and the test is told as well.
        with pytest.raises(mw.files.Reject, match="not accepted"):
            await page.upload("told", tmp_path / "b.bin")
        assert page.state.refused == [
            {"name": "b.bin", "reason": "this type of file is not accepted; expected .txt"}
        ]
        # The size the component allows counts, as it does for a tab.
        with pytest.raises(mw.files.Reject, match="larger than 1 MB"):
            await page.upload("told", tmp_path / "big.txt")
        assert page.state.refused[-1] == {
            "name": "big.txt",
            "reason": "the file is larger than 1 MB",
        }
        ref = await page.upload("told", tmp_path / "a.txt")
        assert ref.name == "a.txt" and page.state.uploaded == ["a.txt"]
        with pytest.raises(mw.files.Reject, match="not accepted"):
            await page.upload("untold", tmp_path / "b.bin")
        assert len(page.state.refused) == 2
        # A disabled one takes no file, and nothing is told to anyone.
        with pytest.raises(LookupError, match="is disabled"):
            await page.upload("shut", tmp_path / "a.txt")
        assert len(page.state.refused) == 2
        # Without on_upload a tab stores the file and says nothing of it.
        kept = await page.upload("kept", tmp_path / "a.txt")
        assert kept.name == "a.txt" and page.state.uploaded == ["a.txt"]
        # What a tab could not send is refused here too: a file to a form's
        # field that takes none, and one to a chat without attachments.
        with pytest.raises(mw.files.Reject, match="no file field"):
            await page.upload("note", tmp_path / "a.txt", field="/text")
        assert (await page.upload("note", tmp_path / "a.txt", field="/file")).name == "a.txt"
        with pytest.raises(mw.files.Reject, match="no upload component"):
            await page.send("plain", "see this", files=[tmp_path / "a.txt"])


class Asked(BaseModel):
    got: list[str] = []


class Who(BaseModel):
    name: str


def asking_app(tmp_path: Path) -> mw.App:
    app = mw.App("asks", state=Asked, public=None, bundle_dir=tmp_path)
    questions: dict[str, Any] = {
        "form": lambda: ui.Form(Who, key="who"),
        "words": lambda: ui.Stack(ui.Text("Sure?"), ui.Button("Yes", key="ok")),
        "sheet": lambda: ui.Sheet(ui.Form(Who, key="who"), title="Who?"),
        "dialog": lambda: ui.Dialog(ui.Form(Who, key="who"), title="Who?", size="lg"),
        "inside": lambda: ui.Stack(ui.Dialog(ui.Form(Who, key="who"), title="Who?")),
        "shown": lambda: ui.Form(Who, key="who", read_only=True, cancel="Close"),
    }

    async def ask(s: mw.Session[Asked], _: Any, which: str) -> None:
        answer = await s.ask(questions[which]())
        s.state.got.append(getattr(answer, "name", str(answer)))

    @app.page("/")
    def home(s: mw.Session[Asked]) -> ui.Component:
        return ui.Page(
            *(
                ui.Button(which, key=which, on_click=lambda s, p, which=which: ask(s, p, which))
                for which in questions
            )
        )

    return app


async def test_a_question_that_is_no_dialog_is_asked_in_one(tmp_path: Path) -> None:
    async with TestApp(asking_app(tmp_path)).open("/") as page:

        def asked() -> Any:
            ask = next(iter(page.session._asks.values()))
            return page.find(page.session._ask_root(ask.request))

        # A bare form would sit at the foot of the page, out of sight under
        # whatever the page is long with. It is asked in a dialog.
        await page.click("form")
        assert asked().type == "Dialog" and asked().props["open"] is True
        (form,) = page.find_all(ui.Form, within=asked())
        # Its Cancel is wired like its submit, or the button would be dead in a tab.
        assert form.props["on_submit"] is True and form.props["on_cancel"] is True
        await page.answer({"name": "Ada"})
        await page.click("form")
        await page.answer(None)
        await page.click("words")
        assert asked().type == "Dialog"
        await page.answer(True)
        assert page.state.got == ["Ada", "None", "True"]

        # A dialog or a sheet is the app's own choice of one, and is shown as given.
        await page.click("dialog")
        assert asked().type == "Dialog" and asked().props["size"] == "lg"
        assert len(page.find_all(ui.Dialog)) == 1
        await page.answer({"name": "Bo"})
        await page.click("sheet")
        assert asked().type == "Sheet" and asked().props["open"] is True
        assert not page.find_all(ui.Dialog)
        await page.answer({"name": "Cy"})
        await page.click("inside")
        assert asked().type == "Stack" and len(page.find_all(ui.Dialog)) == 1
        await page.answer({"name": "Di"})
        # A form that takes no submit takes none as a question either, and
        # can be left.
        await page.click("shown")
        with pytest.raises(LookupError, match="is read-only"):
            await page.answer({"name": "Ed"})
        (form,) = page.find_all(ui.Form, within=asked())
        await page.event(form, "cancel")
        assert page.state.got[3:] == ["Bo", "Cy", "Di", "None"]
