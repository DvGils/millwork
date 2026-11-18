"""What only a browser shows: a form filled in the way a person does it. The
page tests hand a handler its payload as given, so what the tab makes of
what is typed is seen here."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, Field

import millwork as mw
from millwork import ui
from millwork.shot import _SETTLE, STILL, ShotError, _served, _Tab, find_browser, find_browsers
from millwork.theme import Theme


def _browser() -> str | None:
    try:
        return find_browser()
    except ShotError:
        return None


pytestmark = pytest.mark.skipif(
    _browser() is None, reason="no Chromium-family browser on this machine"
)


class Range(BaseModel):
    label: str = Field(min_length=1)
    upper: float | None = None


class Recode(BaseModel):
    type: Literal["recode"] = "recode"
    source: str = ""


class Bucket(BaseModel):
    type: Literal["bucket"] = "bucket"
    edges: str = ""


class Buckets(BaseModel):
    name: str = ""
    ranges: list[Range] = []
    steps: list[Annotated[Recode | Bucket, Field(discriminator="type")]] = []
    tags: list[str] = []


class Page:
    """A page of an app in a browser, for as long as the block runs."""

    def __init__(self, app: mw.App) -> None:
        self.app = app
        self.tab = _Tab(find_browsers())

    async def __aenter__(self) -> Page:
        self._served = _served(self.app)
        base = await self._served.__aenter__()
        try:
            await self.tab.__aenter__()
        except BaseException:
            await self._served.__aexit__(None, None, None)
            raise
        await self.tab.call("Page.enable")
        await self.tab.call("Page.navigate", url=base + "/")
        await self.rest()
        return self

    async def __aexit__(self, *exc: object) -> None:
        try:
            await self.tab.__aexit__(*exc)
        finally:
            await self._served.__aexit__(*exc)

    async def rest(self, at_most: int = 5000) -> None:
        """Wait for the page to stop changing, for ``at_most`` milliseconds.
        A page with a spinner on it never does, and is waited for that long."""
        await self.tab.value(_SETTLE % {"timeout": at_most, "still": STILL})

    async def read(self, script: str) -> Any:
        return await self.tab.value(script)

    async def fields(self) -> list[str]:
        """The place of every field the form has drawn."""
        found: list[str] = await self.read(
            "[...document.querySelectorAll('[data-field]')].map((e) => e.dataset.field)"
        )
        return found

    async def press(self, label: str, nth: int = 0) -> None:
        """Press the button that says ``label``, in words or to a screen
        reader, or the ``nth`` of them."""
        pressed = await self.read(
            "(() => { const b = [...document.querySelectorAll('button')]"
            ".filter((b) => (b.textContent.trim() || b.getAttribute('aria-label'))"
            f" === {json.dumps(label)})[{nth}];"
            " if (!b) return false; b.click(); return true; })()"
        )
        assert pressed, f"no button says {label!r}"
        await self.rest()

    async def click(self, selector: str, text: str | None = None, at_most: int = 5000) -> None:
        """Click with the mouse on what ``selector`` finds, the one that says
        ``text`` when there are several. A press and a release at its
        middle, which is what opens a select."""
        says = "true" if text is None else f"e.textContent.trim() === {json.dumps(text)}"
        at = await self.read(
            f"(() => {{ const e = [...document.querySelectorAll({json.dumps(selector)})]"
            f".find((e) => {says}); if (!e) return null;"
            " const r = e.getBoundingClientRect();"
            " return [r.x + r.width / 2, r.y + r.height / 2]; })()"
        )
        assert at, f"nothing at {selector} says {text!r}"
        for kind in ("mousePressed", "mouseReleased"):
            await self.tab.call(
                "Input.dispatchMouseEvent", type=kind, x=at[0], y=at[1], button="left", clickCount=1
            )
        await self.rest(at_most)

    async def on_top(self, selector: str, text: str | None = None) -> bool:
        """Whether what ``selector`` finds, the one that says ``text``, is
        what a press at its middle would land on."""
        says = "true" if text is None else f"e.textContent.trim() === {json.dumps(text)}"
        found: bool | None = await self.read(
            f"(() => {{ const e = [...document.querySelectorAll({json.dumps(selector)})]"
            f".find((e) => {says}); if (!e) return null;"
            " const r = e.getBoundingClientRect();"
            " const at = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
            " return !!at && (e === at || e.contains(at)); })()"
        )
        assert found is not None, f"nothing at {selector} says {text!r}"
        return found

    async def key(self, name: str, code: int) -> None:
        """Press a key that types nothing, such as Escape, where the keyboard is."""
        for kind in ("keyDown", "keyUp"):
            await self.tab.call(
                "Input.dispatchKeyEvent", type=kind, key=name, code=name, windowsVirtualKeyCode=code
            )
        await self.rest()

    async def type(self, field: str, text: str) -> None:
        """Type into a field, by its place in the form."""
        selector = json.dumps(f'[data-field="{field}"] input')
        focused = await self.read(
            f"(() => {{ const i = document.querySelector({selector});"
            " if (!i) return false; i.focus(); return true; })()"
        )
        assert focused, f"no field at {field}"
        await self.tab.call("Input.insertText", text=text)

    async def said_at(self, field: str | None) -> list[str]:
        """What is wrong, as it is said at a field, or at the foot of the form."""
        where = (
            f"document.querySelector({json.dumps(f'[data-field="{field}"]')})"
            if field is not None
            else "document.querySelector('form')"
        )
        own = "[data-slot=field-error]" if field is None else ":scope > [data-slot=field-error]"
        if field is None:
            # The foot: what is said in the form and under no field of it.
            script = (
                f"[...{where}.querySelectorAll('{own}')]"
                ".filter((e) => !e.closest('[data-field]')).map((e) => e.textContent)"
            )
        else:
            script = f"[...{where}.querySelectorAll('{own}')].map((e) => e.textContent)"
        said: list[str] = await self.read(script)
        return said


async def test_what_is_typed_in_a_row_of_a_list_is_what_the_form_submits() -> None:
    got: list[dict[str, Any]] = []
    app = mw.App("rows", public=None)

    def made(s: mw.Session, doc: Buckets) -> None:
        got.append(doc.model_dump())

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Form(Buckets, key="f", submit="Make", on_submit=made))

    async with Page(app) as page:
        await page.press("Add range")
        await page.press("Add range")
        await page.press("Add steps")
        fields = await page.fields()
        assert "/ranges/0/label" in fields and "/ranges/1/upper" in fields
        assert "/steps/0/source" in fields
        await page.type("/ranges/0/label", "Low")
        await page.type("/ranges/0/upper", "100")
        await page.type("/steps/0/source", "q1")
        # The second range has no label, and is told so at its own field.
        await page.press("Make")
        assert got == []
        assert await page.said_at("/ranges/1/label") == ["This is required."]
        assert await page.said_at("/ranges/0/label") == []
        # A row that is taken out takes what was said of it along.
        await page.press("Remove", nth=1)
        assert "/ranges/1/label" not in await page.fields()
        assert await page.said_at("/ranges") == []
        await page.press("Add range")
        await page.type("/ranges/1/label", "High")
        await page.press("Make")
    assert got == [
        {
            "name": "",
            "ranges": [{"label": "Low", "upper": 100.0}, {"label": "High", "upper": None}],
            "steps": [{"type": "recode", "source": "q1"}],
            "tags": [],
        }
    ]


async def test_an_issue_with_no_field_of_its_own_is_said_at_the_field_above_it() -> None:
    app = mw.App("issues", public=None)

    def refuse(s: mw.Session, doc: Buckets) -> None:
        raise ui.FormIssues(
            [("/tags/1", "No such tag."), ("/owner", "Nobody owns this."), ("/name", "Taken.")]
        )

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Form(Buckets, key="f", submit="Make", on_submit=refuse))

    async with Page(app) as page:
        await page.press("Make")
        assert await page.said_at("/name") == ["Taken."]
        assert await page.said_at("/tags") == ["No such tag."]
        assert await page.said_at(None) == ["Nobody owns this."]


async def test_the_button_that_adds_a_row_says_so_in_the_themes_words() -> None:
    theme = Theme(strings={"add_item": "{Item} toevoegen"})
    app = mw.App("words", public=None, theme=theme)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Form(Buckets, key="f", on_submit=lambda s, doc: None))

    async with Page(app) as page:
        await page.press("Range toevoegen")
        assert "/ranges/0/label" in await page.fields()


async def test_a_select_given_new_options_and_a_value_of_them_keeps_that_value() -> None:
    class Choice(BaseModel):
        options: list[str] = ["a", "b"]
        value: str | None = "a"

    picked: list[str | None] = []
    app = mw.App("select", state=Choice, public=None)

    def pick(s: mw.Session[Choice], value: str | None) -> None:
        picked.append(value)
        s.state.value = value

    def swap(s: mw.Session[Choice], _: Any) -> None:
        s.state.options = ["x", "y"]
        s.state.value = "x"

    def back(s: mw.Session[Choice], _: Any) -> None:
        # With the option the select began at among the new ones.
        s.state.options = ["a", "c"]
        s.state.value = "c"

    @app.page("/")
    def home(s: mw.Session[Choice]) -> ui.Component:
        return ui.Page(
            ui.Select(key="sel", options=s.state.options, value=s.state.value, on_change=pick),
            ui.Button("swap", key="swap", on_click=swap),
            ui.Button("back", key="back", on_click=back),
        )

    shown = "document.querySelector('[data-slot=select-value]').textContent.trim()"
    async with Page(app) as page:
        # A select the person has used, which is when it knows its options.
        await page.click("[role=combobox]")
        await page.click("[role=option]", "b")
        assert picked == ["b"] and await page.read(shown) == "b"
        await page.press("swap")
        # The page chose, and the select has nothing of its own to say.
        assert picked == ["b"]
        assert await page.read(shown) == "x"
        # A key on the closed select still picks the option it starts.
        await page.read("document.querySelector('[role=combobox]').focus()")
        for kind in ("keyDown", "keyUp"):
            await page.tab.call("Input.dispatchKeyEvent", type=kind, key="y", code="KeyY")
        await page.rest()
        assert picked == ["b", "y"] and await page.read(shown) == "y"
        await page.press("back")
        assert picked == ["b", "y"] and await page.read(shown) == "c"


async def test_copied_is_said_only_of_what_was_copied() -> None:
    app = mw.App("copy", public=None)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Button("Copy", key="copy", on_click=lambda s, _: s.clipboard("text")))

    def writes(how: str) -> str:
        # The browser's own answer is the machine's to give, so it is given here.
        return (
            "Object.defineProperty(navigator.clipboard, 'writeText',"
            f" {{ configurable: true, value: () => Promise.{how} }})"
        )

    said = "[...document.querySelectorAll('[data-slot=toast-title]')].map((e) => e.textContent)"
    async with Page(app) as page:
        await page.read(writes("reject(new Error('refused'))"))
        await page.press("Copy")
        assert await page.read(said) == ["Copying failed"]
        await page.read(writes("resolve()"))
        await page.press("Copy")
        assert "Copied" in await page.read(said)


async def test_a_reply_on_its_way_is_said_in_the_chat_and_on_the_assistants_button() -> None:
    import asyncio
    import threading

    # The server has a thread of its own, so the test holds a reply back
    # with an event of threads.
    hold = {"page": threading.Event(), "helper": threading.Event()}
    tidy = threading.Event()
    app = mw.App("waits", public=None)

    def answers(name: str) -> Any:
        async def answer(s: mw.Session, turn: mw.ChatTurn) -> None:
            await asyncio.to_thread(hold[name].wait, 20)
            async with turn.reply() as reply:
                await reply.text(f"Answer from the {name}.")
            if name == "page":
                # What a handler does after its reply, saving it say.
                await asyncio.to_thread(tidy.wait, 20)

        return answer

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Chat(key="page", on_message=answers("page"), waiting="dots", cls="h-[20rem]"),
            ui.Assistant(ui.Chat(key="helper", on_message=answers("helper")), key="a"),
        )

    async def say(page: Page, within: str, text: str) -> None:
        focused = await page.read(
            f"(() => {{ const t = document.querySelector({json.dumps(within + ' textarea')});"
            " if (!t) return false; t.focus(); return true; })()"
        )
        assert focused, f"no composer in {within}"
        await page.tab.call("Input.insertText", text=text)
        for kind in ("keyDown", "keyUp"):
            await page.tab.call(
                "Input.dispatchKeyEvent",
                type=kind,
                key="Enter",
                code="Enter",
                windowsVirtualKeyCode=13,
                text="\r" if kind == "keyDown" else "",
            )
        # A spinner turns from here on, so the page does not come to rest.
        await page.rest(800)

    waiting = (
        "[...document.querySelectorAll('[role=status]')].map((e) => e.ariaLabel || e.textContent)"
    )
    button = "document.querySelector('button[aria-expanded]')"
    async with Page(app) as page:
        # Wide enough for the assistant to be a window and not a sheet.
        await page.tab.call(
            "Emulation.setDeviceMetricsOverride",
            width=1100,
            height=700,
            deviceScaleFactor=1,
            mobile=False,
        )
        await page.rest()
        await say(page, "main", "A question")
        assert await page.read(waiting) == ["Thinking"]
        hold["page"].set()
        await page.rest()
        # The answer is there and its handler is not done: Stop still
        # shows, and nothing says that more is on its way.
        assert "Answer from the page." in await page.read("document.body.textContent")
        assert await page.read(
            "[...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Stop')"
        )
        assert await page.read(waiting) == []
        tidy.set()
        await page.rest()
        assert await page.read(waiting) == []

        await page.click("button[aria-expanded]")
        await say(page, "[role=dialog]", "Another")
        assert await page.read(waiting) == ["Thinking"]
        await page.click("button[aria-label=Minimize]", at_most=800)
        assert await page.read(f"{button}.ariaBusy") == "true"
        assert await page.read(f"{button}.ariaLabel") == "Assistant"
        hold["helper"].set()
        await page.rest()
        # The reply came while the window was minimized, which the button says.
        assert await page.read(f"{button}.ariaBusy") is None
        assert await page.read(f"{button}.ariaLabel") == "Assistant, New reply"
        await page.click("button[aria-expanded]")
        await page.click("button[aria-label=Minimize]")
        assert await page.read(f"{button}.ariaLabel") == "Assistant"

