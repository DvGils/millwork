"""millwork.testing: a session driven without a socket, observed on its wire."""

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
        await page.event("menu", "select", "rm")
        dialog = page.find(ui.Dialog)
        assert dialog.props["title"] == "Remove?"
        await page.answer(False)
        assert page.state.asked is None
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
