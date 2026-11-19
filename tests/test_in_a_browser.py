"""What only a browser shows: a form filled in the way a person does it. The
page tests hand a handler its payload as given, so what the tab makes of
what is typed is seen here."""

from __future__ import annotations

import asyncio
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

    async def middle(self, selector: str) -> tuple[float, float]:
        """The middle of what ``selector`` finds, in the window."""
        at = await self.read(
            f"(() => {{ const e = document.querySelector({json.dumps(selector)});"
            " if (!e) return null; const r = e.getBoundingClientRect();"
            " return [r.x + r.width / 2, r.y + r.height / 2]; })()"
        )
        assert at, f"nothing at {selector}"
        return at[0], at[1]

    async def drag(
        self, selector: str, to: tuple[float, float], *, let_go: bool = True, steps: int = 6
    ) -> None:
        """Press the mouse on what ``selector`` finds, carry it to a point
        of the window in a few steps, and let go there."""
        x0, y0 = await self.middle(selector)
        mouse = {"button": "left", "clickCount": 1}
        await self.tab.call("Input.dispatchMouseEvent", type="mousePressed", x=x0, y=y0, **mouse)
        for i in range(1, steps + 1):
            x, y = x0 + (to[0] - x0) * i / steps, y0 + (to[1] - y0) * i / steps
            await self.tab.call(
                "Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, buttons=1, **mouse
            )
        if let_go:
            await self.let_go(to)

    async def let_go(self, at: tuple[float, float]) -> None:
        await self.tab.call(
            "Input.dispatchMouseEvent",
            type="mouseReleased",
            x=at[0],
            y=at[1],
            button="left",
            clickCount=1,
        )
        await self.rest()

    async def key(self, name: str, code: int, *, alt: bool = False) -> None:
        """Press a key that types nothing, such as Escape, where the keyboard is."""
        for kind in ("keyDown", "keyUp"):
            await self.tab.call(
                "Input.dispatchKeyEvent",
                type=kind,
                key=name,
                code=name,
                windowsVirtualKeyCode=code,
                modifiers=1 if alt else 0,
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


async def test_the_assistant_is_at_hand_over_a_dialog_and_under_no_highlight() -> None:
    class Order(BaseModel):
        customer: str = ""
        amount: float | None = None

    class Desk(BaseModel):
        ordering: bool = False
        asked: list[str] = []

    app = mw.App("layers", state=Desk, public=None)

    async def answer(s: mw.Session[Desk], turn: mw.ChatTurn) -> None:
        s.state.asked.append(turn.text)
        async with turn.reply() as reply:
            await reply.text("The amount comes next.")
        s.highlight("order/amount")

    def order(s: mw.Session[Desk], _: Any) -> None:
        s.state.ordering = True

    def done(s: mw.Session[Desk], _: Any = None) -> None:
        s.state.ordering = False

    @app.page("/")
    def home(s: mw.Session[Desk]) -> ui.Component:
        return ui.Page(
            ui.Button("New order", key="new", on_click=order),
            ui.Button("Mark", key="mark", on_click=lambda s, _: s.highlight("wide")),
            # Wide enough to lie partly under the assistant's window.
            ui.Card(ui.Text("An order. " * 60), key="wide", title="Orders"),
            ui.Text(f"asked {len(s.state.asked)}", key="asked"),
            ui.Dialog(
                ui.Form(Order, key="order", on_submit=done),
                key="dialog",
                title="New order",
                open=s.state.ordering,
                on_close=done,
            ),
            ui.Assistant(
                ui.Select(key="tone", options=["Brief", "Thorough"], default="Brief"),
                ui.Chat(key="helper", on_message=answer),
                key="a",
            ),
        )

    now = """(() => {
      const over = document.querySelector('[role=dialog][data-mw-over]');
      return {
        dialog: !!document.querySelector('[data-slot=dialog-content]'),
        assistant: !!over && !over.hidden,
        heard: !document.querySelector('button[data-mw-over], [role=dialog][data-mw-over]')
          ?.closest('[aria-hidden=true]'),
        frames: [...document.querySelectorAll('.mw-mark')]
          .filter((m) => m.style.display !== 'none').map((m) => Number(m.style.zIndex)),
        window: over ? Number(getComputedStyle(over).zIndex) : null,
        asked: document.body.textContent.includes('asked 1'),
      };
    })()"""
    async with Page(app) as page:
        await page.tab.call(
            "Emulation.setDeviceMetricsOverride",
            width=1100,
            height=700,
            deviceScaleFactor=1,
            mobile=False,
        )
        await page.rest()
        # A highlight on the page lies under the window that covers part of it.
        await page.click("button[data-mw-over]")
        await page.press("Mark")
        await page.rest(1500)
        seen = await page.read(now)
        assert seen["assistant"] and len(seen["frames"]) == 1
        assert seen["frames"][0] < seen["window"]
        # What a field in the window opens lies over the window.
        await page.click("[data-mw-over] [role=combobox]", at_most=1500)
        on_top = await page.read(
            "(() => { const o = [...document.querySelectorAll('[role=option]')]"
            ".find((o) => o.textContent.trim() === 'Thorough'); if (!o) return 'no list';"
            " const r = o.getBoundingClientRect();"
            " const at = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
            " return at && at.closest('[role=option]') ? 'the option' : 'something else'; })()"
        )
        assert on_top == "the option"
        await page.click("[role=option]", "Thorough", at_most=1500)
        await page.click("button[aria-label=Minimize]", at_most=1500)

        # With a dialog open the button is there to press, and pressing it
        # is no press outside the dialog.
        await page.press("New order")
        await page.click("button[data-mw-over]")
        seen = await page.read(now)
        assert seen["dialog"] and seen["assistant"] and seen["heard"]

        # What is asked there arrives, and the field it points at in the
        # dialog is framed over the dialog and under the window.
        await page.read("document.querySelector('[data-mw-over] textarea').focus()")
        await page.tab.call("Input.insertText", text="What comes next?")
        for kind in ("keyDown", "keyUp"):
            await page.tab.call(
                "Input.dispatchKeyEvent",
                type=kind,
                key="Enter",
                code="Enter",
                windowsVirtualKeyCode=13,
                text="\r" if kind == "keyDown" else "",
            )
        await page.rest(1500)
        seen = await page.read(now)
        assert seen["asked"] and seen["dialog"] and seen["assistant"]
        assert len(seen["frames"]) == 1 and 50 < seen["frames"][0] < seen["window"]

        # Escape in the window minimizes the window, and in the dialog
        # closes the dialog.
        await page.read("document.querySelector('[data-mw-over] textarea').focus()")
        await page.key("Escape", 27)
        seen = await page.read(now)
        assert seen["dialog"] and not seen["assistant"]
        await page.click('[data-field="/customer"] input', at_most=1500)
        await page.key("Escape", 27)
        assert not (await page.read(now))["dialog"]


async def test_a_question_and_a_dialog_that_cannot_be_dismissed_lie_over_the_assistant() -> None:
    class Desk(BaseModel):
        ordering: bool = False
        agreeing: bool = False
        wiped: bool = False

    app = mw.App("urgent", state=Desk, public=None)

    def set_to(name: str, value: bool) -> Any:
        return lambda s, _=None: setattr(s.state, name, value)

    @app.page("/")
    def home(s: mw.Session[Desk]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.Button("New order", key="new", on_click=set_to("ordering", True)),
            ui.Button("Terms", key="terms", on_click=set_to("agreeing", True)),
            ui.Text(f"wiped {st.wiped}", key="wiped"),
            ui.Dialog(
                ui.Text("An order."),
                key="order",
                title="New order",
                open=st.ordering,
                on_close=set_to("ordering", False),
            ),
            ui.Dialog(
                ui.Button("Agree", key="agree", on_click=set_to("agreeing", False)),
                key="must",
                title="The terms",
                open=st.agreeing,
                dismissable=False,
            ),
            ui.Assistant(
                ui.Select(key="tone", options=["Brief", "Thorough"], default="Brief"),
                ui.Button(
                    "Wipe", key="wipe", confirm="Delete everything?", on_click=set_to("wiped", True)
                ),
                key="a",
            ),
        )

    heard = "!document.querySelector('[role=dialog][data-mw-over]').closest('[aria-hidden=true]')"
    dialogs = "document.querySelectorAll('[data-slot=dialog-content]').length"
    async with Page(app) as page:
        await page.tab.call(
            "Emulation.setDeviceMetricsOverride",
            width=1000,
            height=700,
            deviceScaleFactor=1,
            mobile=False,
        )
        await page.rest()
        await page.click("button[data-mw-over]")

        # A question asked from the window lies over the window, all of it.
        await page.press("Wipe")
        assert await page.on_top("[data-slot=dialog-content] button", "OK")
        assert not await page.read(heard)
        await page.click("[data-slot=dialog-content] button", "OK")
        assert "wiped True" in await page.read("document.body.textContent")
        assert await page.read(heard)

        # Escape in a list the window opened closes the list, and leaves a
        # dialog of the page as it is.
        await page.press("New order")
        await page.click("[data-mw-over] [role=combobox]")
        assert await page.on_top("[role=option]", "Thorough")
        await page.key("Escape", 27)
        assert await page.read(dialogs) == 1
        assert not await page.read("document.querySelector('[role=option]')?.checkVisibility()")
        # Nor does dragging the window by its header close the dialog.
        at = await page.read(
            "(() => { const r = document.querySelector('[role=dialog][data-mw-over]')"
            ".getBoundingClientRect(); return [r.x + 60, r.y + 20]; })()"
        )
        for kind, x in (
            ("mousePressed", at[0]),
            ("mouseMoved", at[0] - 30),
            ("mouseReleased", at[0] - 30),
        ):
            await page.tab.call(
                "Input.dispatchMouseEvent",
                type=kind,
                x=x,
                y=at[1],
                button="left",
                buttons=1,
                clickCount=1,
            )
        await page.rest()
        assert await page.read(dialogs) == 1
        # With the keyboard nowhere, Escape is the dialog's again, though
        # the assistant was what the person used last.
        await page.read("document.activeElement.blur()")
        assert await page.read("document.activeElement === document.body")
        await page.key("Escape", 27)
        assert await page.read(dialogs) == 0

        # A dialog that cannot be dismissed keeps the assistant under it.
        await page.press("Terms")
        assert not await page.on_top("[role=dialog][data-mw-over] [role=combobox]")
        assert not await page.read(heard)
        await page.click("[data-slot=dialog-content] button", "Agree")
        assert await page.on_top("[role=dialog][data-mw-over] [role=combobox]")
        assert await page.read(heard)


async def test_on_a_phone_the_assistants_sheet_opens_over_a_dialog() -> None:
    class Desk(BaseModel):
        ordering: bool = True

    app = mw.App("phone", state=Desk, public=None)

    def done(s: mw.Session[Desk], _: Any = None) -> None:
        s.state.ordering = False

    @app.page("/")
    def home(s: mw.Session[Desk]) -> ui.Component:
        return ui.Page(
            ui.Dialog(
                ui.Text("An order."),
                key="order",
                title="New order",
                open=s.state.ordering,
                on_close=done,
            ),
            ui.Assistant(ui.Chat(key="helper", on_message=lambda s, turn: None), key="a"),
        )

    async with Page(app) as page:
        await page.tab.call(
            "Emulation.setDeviceMetricsOverride",
            width=390,
            height=800,
            deviceScaleFactor=1,
            mobile=True,
        )
        await page.rest()
        assert await page.on_top("button[data-mw-over]")
        await page.click("button[data-mw-over]")
        assert await page.on_top("[data-mw-over] textarea")
        assert not await page.read(
            "!!document.querySelector('[data-mw-over] textarea').closest('[aria-hidden=true]')"
        )
        assert (
            await page.read("document.querySelectorAll('[data-slot=dialog-content]').length") == 1
        )


async def test_a_toasts_action_takes_the_toast_with_it() -> None:
    class Bin(BaseModel):
        undone: int = 0

    app = mw.App("undo", state=Bin, public=None)

    def undo(s: mw.Session[Bin], _: Any) -> None:
        s.state.undone += 1

    @app.page("/")
    def home(s: mw.Session[Bin]) -> ui.Component:
        return ui.Page(
            ui.Button(
                "Delete",
                key="del",
                on_click=lambda s, _: s.toast("Deleted.", action=("Undo", undo)),
            ),
            ui.Text(f"undone {s.state.undone}", key="count"),
        )

    toasts = "document.querySelectorAll('[data-slot=toast]').length"
    async with Page(app) as page:
        await page.press("Delete")
        assert await page.read(toasts) == 1
        await page.click("[data-slot=toast-action]")
        assert "undone 1" in await page.read("document.body.textContent")
        # Nothing is left to press a second time.
        assert await page.read(toasts) == 0


# ------------------------------------------------------------- rows that are dragged

ROWS = """Object.fromEntries([...document.querySelectorAll('[data-sortable]')].map((l) => [
  l.dataset.sortable.split('/').pop(),
  [...l.querySelectorAll(':scope > [data-sortable-row]')]
    .filter((r) => r.checkVisibility()).map((r) => r.dataset.sortableRow.split('/').pop()),
]))"""
COPIES = "document.querySelectorAll('.mw-sortable-copy').length"


def grip(row: str) -> str:
    return f'[data-sortable-row$="/{row}"] [data-sortable-grip]'


class Camp(BaseModel):
    lists: dict[str, list[str]] = {"todo": ["tent", "water", "map", "stove"], "doing": ["food"]}
    done: list[str] = []
    full: bool = False
    slow: bool = False
    renamed: int = 0


def camp() -> mw.App:
    app = mw.App("camp", state=Camp, public=None)

    async def moved(s: mw.Session[Camp], move: ui.Move) -> None:
        st = s.state
        every = {**st.lists, "done": st.done}
        if move.target == "done" and st.full:
            # The list is full, so the row is left where it was.
            return
        if st.slow:
            await asyncio.sleep(2.2)
        every[move.source].remove(move.key)
        every[move.target].insert(move.to, move.key)

    def rename(s: mw.Session[Camp], _: Any) -> None:
        s.state.renamed += 1

    def rows(name: str, keys: list[str]) -> ui.Component:
        return ui.Stack(
            ui.Text(name, variant="heading"),
            ui.Sortable(
                *[ui.Card(title=key.capitalize(), key=key) for key in keys],
                key=name,
                group="tasks",
                label=f"{name} {mw.session().state.renamed}",
                empty="Nothing here yet",
                on_move=moved,
            ),
            key=f"col-{name}",
        )

    @app.page("/")
    def home(s: mw.Session[Camp]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.Grid(*[rows(n, k) for n, k in st.lists.items()], rows("done", st.done), cols=3),
            ui.Button("Full", key="full", on_click=lambda s, _: setattr(s.state, "full", True)),
            ui.Button("Slow", key="slow", on_click=lambda s, _: setattr(s.state, "slow", True)),
            ui.Button("Rename", key="rename", on_click=rename),
        )

    return app


async def wide(page: Page) -> None:
    await page.tab.call(
        "Emulation.setDeviceMetricsOverride",
        width=1000,
        height=700,
        deviceScaleFactor=1,
        mobile=False,
    )
    await page.rest()


async def test_a_row_is_dragged_to_another_place_and_into_another_list() -> None:
    async with Page(camp()) as page:
        await wide(page)
        # Within its list: the last row over the first.
        x, y = await page.middle('[data-sortable-row$="/tent"]')
        await page.drag(grip("stove"), (x, y - 30))
        assert (await page.read(ROWS))["todo"] == ["stove", "tent", "water", "map"]
        # Into the list beside it, let go under that list's one row, where
        # the list itself has ended.
        x, y = await page.middle('[data-sortable$="/doing"]')
        await page.drag(grip("map"), (x, y + 90))
        now = await page.read(ROWS)
        assert now["todo"] == ["stove", "tent", "water"] and now["doing"] == ["food", "map"]
        # Into a list with no rows, which says so until a row is over it.
        assert "Nothing here yet" in await page.read("document.body.textContent")
        x, y = await page.middle('[data-sortable$="/done"]')
        await page.drag(grip("water"), (x, y), let_go=False)
        assert await page.read(
            "!!document.querySelector('[data-sortable$=\"/done\"] [data-sortable-gap]')"
        )
        assert await page.read(COPIES) == 1
        await page.let_go((x, y))
        now = await page.read(ROWS)
        assert now["todo"] == ["stove", "tent"] and now["done"] == ["water"]
        assert await page.read(COPIES) == 0
        assert "Nothing here yet" not in await page.read("document.body.textContent")
        # The keyboard is on the grip of the row where it is now.
        assert await page.read(
            "document.activeElement?.closest('[data-sortable-row]')?.dataset.sortableRow"
        ) == await page.read(
            "document.querySelector('[data-sortable-row$=\"/done/water\"]').dataset.sortableRow"
        )


async def test_a_held_row_stays_held_and_a_dropped_row_waits_for_the_page() -> None:
    async with Page(camp()) as page:
        await wide(page)
        x, y = await page.middle('[data-sortable$="/doing"]')
        # The page changes something of the list that is not its rows, and
        # the row stays in the hand.
        await page.drag(grip("map"), (x, y + 90), let_go=False)
        await page.press("Rename")
        assert (
            await page.read("document.querySelector('[data-sortable$=\"/doing\"]').ariaLabel")
            == "doing 1"
        )
        assert await page.read(COPIES) == 1
        await page.let_go((x, y + 90))
        assert (await page.read(ROWS))["doing"] == ["food", "map"]

        # A handler that takes its time: the row stays where it was let go
        # until the page has it there, and does not go back meanwhile.
        await page.press("Slow")
        x, y = await page.middle('[data-sortable$="/done"]')
        await page.drag(grip("tent"), (x, y), let_go=False)
        await page.tab.call(
            "Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1
        )
        await asyncio.sleep(1.8)
        waiting = await page.read(ROWS)
        assert "tent" not in waiting["todo"] and await page.read(COPIES) == 1
        await asyncio.sleep(0.8)
        await page.rest()
        assert (await page.read(ROWS))["done"] == ["tent"] and await page.read(COPIES) == 0

        # A button that came up where the window did not see it lets the row go back.
        x, y = await page.middle('[data-sortable$="/doing"]')
        start = await page.read(ROWS)
        await page.drag(grip("water"), (x, y), let_go=False)
        assert await page.read(COPIES) == 1
        await page.tab.call(
            "Input.dispatchMouseEvent", type="mouseMoved", x=x + 5, y=y, button="none", buttons=0
        )
        await page.rest()
        assert await page.read(COPIES) == 0 and await page.read(ROWS) == start


async def test_a_row_the_page_does_not_move_goes_back() -> None:
    async with Page(camp()) as page:
        await wide(page)
        start = await page.read(ROWS)
        await page.press("Full")
        # The handler leaves the row where it was.
        x, y = await page.middle('[data-sortable$="/done"]')
        await page.drag(grip("map"), (x, y))
        assert await page.read(ROWS) == start and await page.read(COPIES) == 0
        # Let go beside every list.
        await page.drag(grip("tent"), (995, 400))
        assert await page.read(ROWS) == start and await page.read(COPIES) == 0
        # Escape while the row is held.
        x, y = await page.middle('[data-sortable$="/doing"]')
        await page.drag(grip("water"), (x, y), let_go=False)
        assert await page.read(COPIES) == 1
        # Holding a row changes nothing of the page as a whole, which would
        # have every element of a long page styled anew.
        assert await page.read("document.body.className") == ""
        await page.key("Escape", 27)
        assert await page.read(ROWS) == start and await page.read(COPIES) == 0
        await page.let_go((x, y))
        assert await page.read(ROWS) == start


async def test_the_keyboard_moves_a_row_a_place_at_a_time_and_goes_with_it() -> None:
    held = (
        "document.activeElement?.closest('[data-sortable-row]')"
        "?.dataset.sortableRow.split('/').slice(-2).join('/')"
    )
    async with Page(camp()) as page:
        await wide(page)
        await page.read(f"document.querySelector({json.dumps(grip('map'))}).focus()")
        await page.key("ArrowUp", 38, alt=True)
        assert (await page.read(ROWS))["todo"] == ["tent", "map", "water", "stove"]
        assert await page.read(held) == "todo/map"
        # A plain arrow is no move.
        await page.key("ArrowUp", 38)
        assert (await page.read(ROWS))["todo"] == ["tent", "map", "water", "stove"]
        # Past the end of its list a row goes into the next one, at the top.
        await page.read(f"document.querySelector({json.dumps(grip('stove'))}).focus()")
        await page.key("ArrowDown", 40, alt=True)
        now = await page.read(ROWS)
        assert now["todo"] == ["tent", "map", "water"] and now["doing"] == ["stove", "food"]
        assert await page.read(held) == "doing/stove"
        said = await page.read(
            "[...document.querySelectorAll('[data-sortable] + [aria-live]')]"
            ".map((e) => e.textContent)"
        )
        assert "Place 1 of 2 in doing 0" in said


async def test_lists_in_rows_a_row_dragged_by_all_of_it_and_a_long_list() -> None:
    class Trip(BaseModel):
        days: dict[str, list[str]] = {"mon": ["swim", "hike"], "tue": ["museum"], "wed": []}
        long: list[str] = [f"n{i}" for i in range(40)]
        pressed: list[str] = []

    app = mw.App("trip", state=Trip, public=None)

    def stop_moved(s: mw.Session[Trip], move: ui.Move) -> None:
        days = s.state.days
        days[move.source].remove(move.key)
        days[move.target].insert(move.to, move.key)

    def day_moved(s: mw.Session[Trip], move: ui.Move) -> None:
        day = move.key.removeprefix("day-")
        order = [d for d in s.state.days if d != day]
        order.insert(move.to, day)
        s.state.days = {d: s.state.days[d] for d in order}

    def long_moved(s: mw.Session[Trip], move: ui.Move) -> None:
        s.state.long.remove(move.key)
        s.state.long.insert(move.to, move.key)

    def press(s: mw.Session[Trip], _: Any) -> None:
        s.state.pressed.append("pressed")

    @app.page("/")
    def home(s: mw.Session[Trip]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.Grid(
                # Days, each a row with a list of its own in it.
                ui.Sortable(
                    *[
                        ui.Card(
                            ui.Sortable(
                                *[ui.Text(stop, key=stop) for stop in stops],
                                key=day,
                                group="stops",
                                empty="A free day",
                                on_move=stop_moved,
                            ),
                            key=f"day-{day}",
                            title=day,
                        )
                        for day, stops in st.days.items()
                    ],
                    key="days",
                    on_move=day_moved,
                ),
                # Rows dragged by all of them, with a button in each.
                ui.ScrollArea(
                    ui.Sortable(
                        *[
                            ui.Row(ui.Text(n), ui.Button("Press", on_click=press), key=n)
                            for n in st.long
                        ],
                        key="long",
                        handle=False,
                        on_move=long_moved,
                    ),
                    key="scroll",
                    height="20rem",
                ),
                cols=2,
            ),
            ui.Text(f"pressed {len(st.pressed)}", key="pressed"),
        )

    def day_grip(day: str) -> str:
        return f'[data-sortable-row$="/day-{day}"] > [data-sortable-grip]'

    async with Page(app) as page:
        await wide(page)
        # A stop goes into another day's list, and into a day with none.
        x, y = await page.middle('[data-sortable$="/tue"]')
        await page.drag(grip("hike"), (x, y + 4))
        x, y = await page.middle('[data-sortable$="/wed"]')
        await page.drag(grip("swim"), (x, y))
        now = await page.read(ROWS)
        assert (now["mon"], now["tue"], now["wed"]) == ([], ["museum", "hike"], ["swim"])
        # A day is a row of the list of days, and takes its stops along.
        x, y = await page.middle('[data-sortable-row$="/day-mon"]')
        await page.drag(day_grip("wed"), (x, y - 40))
        now = await page.read(ROWS)
        assert now["days"] == ["day-wed", "day-mon", "day-tue"] and now["wed"] == ["swim"]

        # A row with no grip: a press on its button is a press, and the
        # row is dragged by its words.
        await page.click('[data-sortable-row$="/n1"] button')
        assert "pressed 1" in await page.read("document.body.textContent")
        x, y = await page.middle('[data-sortable-row$="/n3"]')
        await page.drag('[data-sortable-row$="/n0"] p', (x, y + 4))
        assert (await page.read(ROWS))["long"][:4] == ["n1", "n2", "n3", "n0"]

        # Held near the foot of what scrolls, the list scrolls under the row.
        scrolled = "document.querySelector('[data-slot=scroll-area-viewport]').scrollTop"
        box = await page.read(
            "(() => { const r = document.querySelector('[data-slot=scroll-area-viewport]')"
            ".getBoundingClientRect(); return [r.x + r.width / 2, r.bottom - 10]; })()"
        )
        assert await page.read(scrolled) == 0
        await page.drag('[data-sortable-row$="/n1"] p', (box[0], box[1]), let_go=False)
        await page.rest(600)
        assert await page.read(scrolled) > 100
        await page.let_go((box[0], box[1]))
        order = (await page.read(ROWS))["long"]
        assert order.index("n1") > 8


async def test_a_list_that_keeps_its_order_or_takes_no_rows_and_a_finger_on_a_row() -> None:
    class Shelf(BaseModel):
        fixed: list[str] = ["f1", "f2", "f3"]
        open: list[str] = ["o1", "o2"]
        plain: list[str] = ["p1", "p2", "p3"]

    app = mw.App("shelf", state=Shelf, public=None)

    def moved(s: mw.Session[Shelf], move: ui.Move) -> None:
        getattr(s.state, move.source).remove(move.key)
        getattr(s.state, move.target).insert(move.to, move.key)

    def rows(name: str, keys: list[str], **how: Any) -> ui.Component:
        return ui.Sortable(
            *[ui.Card(title=key, key=key) for key in keys], key=name, on_move=moved, **how
        )

    @app.page("/")
    def home(s: mw.Session[Shelf]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.Grid(
                # Its rows keep their order and it takes none, but they may leave.
                rows("fixed", st.fixed, group="books", reorder=False, takes=False),
                rows("open", st.open, group="books"),
                rows("plain", st.plain, handle=False),
                # Nobody to tell of a move, so there is nothing to hold.
                ui.Sortable(
                    ui.Card(title="still", key="still"), ui.Card(title="too", key="too"), key="deaf"
                ),
                cols=4,
            )
        )

    async with Page(app) as page:
        await wide(page)
        start = await page.read(ROWS)
        assert (
            await page.read("document.querySelectorAll('[data-sortable$=\"/deaf\"] button').length")
            == 0
        )
        # Within the list that keeps its order a row goes nowhere.
        x, y = await page.middle('[data-sortable-row$="/f1"]')
        await page.drag(grip("f3"), (x, y - 20))
        assert await page.read(ROWS) == start
        # It takes no row of another list: one let go over it goes back.
        await page.drag(grip("o1"), (x, y))
        assert await page.read(ROWS) == start and await page.read(COPIES) == 0
        # Its own rows leave it.
        x, y = await page.middle('[data-sortable$="/open"]')
        await page.drag(grip("f2"), (x, y - 60))
        now = await page.read(ROWS)
        assert now["fixed"] == ["f1", "f3"] and now["open"] == ["f2", "o1", "o2"]

        # A finger on a row that is dragged by all of it: moved at once it
        # scrolls the page and holds nothing, and rested for a moment it
        # holds the row.
        await page.tab.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=1)
        x, y = await page.middle('[data-sortable-row$="/p1"]')
        last = await page.middle('[data-sortable-row$="/p3"]')
        target = (last[0], last[1] + 10)

        async def touch(kind: str, at: tuple[float, float] | None) -> None:
            points = [] if at is None else [{"x": at[0], "y": at[1]}]
            await page.tab.call("Input.dispatchTouchEvent", type=kind, touchPoints=points)

        await touch("touchStart", (x, y))
        await touch("touchMove", (x, y + 40))
        assert await page.read(COPIES) == 0
        await touch("touchEnd", None)
        await page.rest()
        assert (await page.read(ROWS))["plain"] == ["p1", "p2", "p3"]

        await touch("touchStart", (x, y))
        await page.rest(500)
        assert await page.read(COPIES) == 1
        await touch("touchMove", ((x + target[0]) / 2, (y + target[1]) / 2))
        await touch("touchMove", target)
        await touch("touchEnd", None)
        await page.rest()
        assert (await page.read(ROWS))["plain"] == ["p2", "p3", "p1"]


async def test_no_page_of_the_manual_makes_the_window_scroll() -> None:
    """A page scrolls in its own body, under the header. Something on it
    that is placed from outside that body, an element hidden for a screen
    reader for one, makes the window as long as the page and gives it a
    second scrollbar, with nothing to show for it."""
    from pathlib import Path

    import millwork.manual as manual

    pages = Path(manual.__file__).parent / "pages"
    paths = []
    for file in sorted(pages.rglob("*.md")):
        name = file.relative_to(pages).with_suffix("").as_posix()
        paths.append("/" if name == "index" else "/" + name.removesuffix("/index"))
    assert len(paths) > 20
    longer = (
        "(() => { const d = document.documentElement;"
        " return d.scrollHeight > innerHeight + 2 || d.scrollWidth > innerWidth + 2; })()"
    )
    drawn = "!!document.querySelector('.mw-shell-body h1')"
    scrolls: list[str] = []
    async with Page(manual.make_app()) as page:
        await wide(page)
        base = (await page.read("location.origin")) or ""
        for path in paths:
            await page.tab.call("Page.navigate", url=base + path)
            await page.tab.value(_SETTLE % {"timeout": 4000, "still": 100})
            assert await page.read(drawn), path
            if await page.read(longer):
                scrolls.append(path)
    assert scrolls == []


async def test_what_is_hidden_deep_in_a_long_page_does_not_make_the_window_scroll() -> None:
    app = mw.App("long", public=None)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            *[ui.Text(f"Line {n}") for n in range(150)],
            # Each has something in it that only a screen reader or the
            # browser's file dialog has a use for.
            ui.FileUpload(key="upload"),
            ui.FileUpload(key="button", dropzone=False),
            ui.Sortable(ui.Text("a", key="a"), key="rows", on_move=lambda s, m: None),
            ui.MultiSelect(options=["x", "y"], default=["x"], sortable=True),
            # In something that scrolls by itself as well.
            ui.ScrollArea(
                *[ui.Text(f"Inner {n}") for n in range(60)],
                ui.FileUpload(key="inner"),
                key="area",
                height="10rem",
            ),
        )

    async with Page(app) as page:
        await wide(page)
        sizes = await page.read(
            "(() => { const d = document.documentElement;"
            " const b = document.querySelector('.mw-shell-body');"
            " b.scrollTop = b.scrollHeight;"
            " return { window: innerHeight, page: d.scrollHeight, body: b.scrollHeight,"
            " end: Math.round(b.scrollTop + b.clientHeight) }; })()"
        )
        assert sizes["page"] <= sizes["window"] + 2
        # The body is as long as what is in it, and no longer.
        assert sizes["body"] > 3000 and sizes["end"] >= sizes["body"] - 2
        below = await page.read(
            "(() => { const b = document.querySelector('.mw-shell-body');"
            " const box = b.getBoundingClientRect();"
            " const area = document.querySelector('[data-slot=scroll-area]');"
            " return Math.round(box.bottom - area.getBoundingClientRect().bottom); })()"
        )
        # Scrolled to its end, the body ends a little under its last child.
        assert 0 <= below < 80
