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

    async def rest(self) -> None:
        await self.tab.value(_SETTLE % {"timeout": 5000, "still": STILL})

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
