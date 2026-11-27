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


# The keys held with a press, as the browser's own protocol numbers them.
ALT, SHIFT = 1, 8
# Whether the app has drawn its page, waited for as long as an app and a
# browser get to start. Before that the tab holds its shell and nothing of
# the page, and a shell can stand still for longer than a page is taken to
# need to come to rest: the first page a browser loads is its slowest.
DRAWN = """new Promise((done) => {
  const until = performance.now() + 30000;
  const look = () => {
    if (document.querySelector("[data-node]")) done(true);
    else if (performance.now() > until) done(false);
    else setTimeout(look, 25);
  };
  look();
})"""


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
        try:
            await self.tab.call("Page.enable")
            await self.tab.call("Page.navigate", url=base + "/")
            assert await self.tab.value(DRAWN), "the app did not draw its page"
            await self.rest()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
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

    async def click(
        self, selector: str, text: str | None = None, at_most: int = 5000, *, shift: bool = False
    ) -> None:
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
                "Input.dispatchMouseEvent",
                type=kind,
                x=at[0],
                y=at[1],
                button="left",
                clickCount=1,
                modifiers=SHIFT if shift else 0,
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

    async def key(self, name: str, code: int, *, alt: bool = False, shift: bool = False) -> None:
        """Press a key that types nothing, such as Escape, where the keyboard is."""
        for kind in ("keyDown", "keyUp"):
            await self.tab.call(
                "Input.dispatchKeyEvent",
                type=kind,
                key=name,
                code=name,
                windowsVirtualKeyCode=code,
                modifiers=(ALT if alt else 0) | (SHIFT if shift else 0),
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


class Shelf(BaseModel):
    seen: int = 0


async def test_the_query_of_an_address_is_the_pages_on_every_way_in() -> None:
    app = mw.App("query", state=Shelf, public=None)

    def more(s: mw.Session[Shelf], _: object) -> None:
        s.state.seen += 1

    @app.page("/")
    def home(s: mw.Session[Shelf]) -> ui.Page:
        return ui.Page(
            ui.Text(f"view={s.query.get('view', 'all')};seen={s.state.seen}", key="says"),
            ui.Link(label="Open", href="/?view=open"),
            ui.Link(label="Done", href="/?view=done&tag=a%20b"),
            ui.Link(label="All", href="/"),
            ui.Button("More", on_click=more),
        )

    async with Page(app) as page:
        origin = await page.read("location.origin")

        async def says(want: str) -> str:
            read = "document.querySelector(\"[data-node='root/says']\")?.textContent"
            for _ in range(100):
                if await page.read(read) == want:
                    break
                await asyncio.sleep(0.05)
            return f"{await page.read(read)} at {await page.read('location.search')!r}"

        async def follow(label: str) -> None:
            links = "[...document.querySelectorAll('a')]"
            await page.read(f"void {links}.find((a) => a.textContent === '{label}').click()")

        # The address a person was sent, or typed, opens the page it names.
        await page.tab.call("Page.navigate", url=origin + "/?view=open")
        assert await says("view=open;seen=0") == "view=open;seen=0 at '?view=open'"
        # A reload keeps the address, and with it the session and its state.
        await page.press("More")
        assert await says("view=open;seen=1") == "view=open;seen=1 at '?view=open'"
        await page.tab.call("Page.reload")
        assert await page.tab.value(DRAWN)
        assert await says("view=open;seen=1") == "view=open;seen=1 at '?view=open'"
        # A link to the same page with another query, and to it with none,
        # each change the address, and the history goes back through them.
        await follow("Done")
        assert await says("view=done;seen=1") == "view=done;seen=1 at '?view=done&tag=a%20b'"
        await follow("All")
        assert await says("view=all;seen=1") == "view=all;seen=1 at ''"
        await page.read("void history.back()")
        assert await says("view=done;seen=1") == "view=done;seen=1 at '?view=done&tag=a%20b'"
        await page.read("void history.back()")
        assert await says("view=open;seen=1") == "view=open;seen=1 at '?view=open'"
        await page.read("void history.forward()")
        assert await says("view=done;seen=1") == "view=done;seen=1 at '?view=done&tag=a%20b'"
        await page.read("void history.forward()")
        assert await says("view=all;seen=1") == "view=all;seen=1 at ''"


async def test_a_link_to_a_route_of_the_app_is_followed_by_the_browser() -> None:
    from starlette.responses import PlainTextResponse

    app = mw.App("routes", state=Shelf, public=None)
    asked: list[str] = []

    async def file(request: Any) -> PlainTextResponse:
        asked.append(str(request.url.path) + "?" + str(request.url.query))
        save = {"Content-Disposition": 'attachment; filename="notes.txt"'}
        return PlainTextResponse("notes", headers=save)

    async def plain(request: Any) -> PlainTextResponse:
        return PlainTextResponse("a page of the route's own")

    app.route("/raw/{name}", file)
    app.route("/plain", plain)

    def more(s: mw.Session[Shelf], _: object) -> None:
        s.state.seen += 1

    @app.page("/")
    def home(s: mw.Session[Shelf]) -> ui.Page:
        return ui.Page(
            ui.Text(f"seen={s.state.seen}", key="says"),
            ui.Link(label="Notes", href="/raw/notes.txt?v=2"),
            ui.Button("Later", on_click=lambda s, _: s.navigate("/raw/later.txt")),
            ui.Markdown("[Plain](/plain)"),
            ui.Button("More", on_click=more),
        )

    async with Page(app) as page:

        async def until(script: str, want: object) -> object:
            for _ in range(100):
                if await page.read(script) == want:
                    break
                await asyncio.sleep(0.05)
            return await page.read(script)

        async def follow(label: str) -> None:
            links = "[...document.querySelectorAll('a')]"
            await page.read(f"void {links}.find((a) => a.textContent === '{label}').click()")

        says = "document.querySelector(\"[data-node='root/says']\")?.textContent"
        # A file to save: the browser asks the route for it, and the page
        # stays as it is, with its session.
        await follow("Notes")
        for _ in range(100):
            if asked:
                break
            await asyncio.sleep(0.05)
        assert asked == ["/raw/notes.txt?v=2"]
        await page.press("Later")
        for _ in range(100):
            if len(asked) > 1:
                break
            await asyncio.sleep(0.05)
        assert asked[1:] == ["/raw/later.txt?"]
        await page.press("More")
        assert await until(says, "seen=1") == "seen=1"
        assert await page.read("location.pathname") == "/"
        # What a route answers with a page of its own is where the tab goes.
        await follow("Plain")
        assert await until("location.pathname", "/plain") == "/plain"
        said = "a page of the route's own"
        assert await until("document.body.innerText", said) == said


WIDTHS = """[...document.querySelectorAll("[data-node='root/%s'] th")].map(
  (th) => Math.round(th.getBoundingClientRect().width))"""


async def test_a_column_is_as_wide_as_it_says_in_pixels_or_as_a_length() -> None:
    app = mw.App("widths", public=None)
    rows = [{"id": 1, "a": "x", "b": "y", "c": "z"}]

    @app.page("/")
    def home(s: mw.Session) -> ui.Page:
        def table(width: int | str, key: str) -> ui.Table:
            columns = [ui.Column(key="a", width=width), ui.Column(key="b"), ui.Column(key="c")]
            return ui.Table(rows=rows, columns=columns, row_key="id", key=key)

        return ui.Page(table(320, "number"), table("20rem", "length"))

    async with Page(app) as page:
        await wide(page)
        number, length = await page.read(WIDTHS % "number"), await page.read(WIDTHS % "length")
        assert number[0] == 320 and length == number


EDGES = """(() => {
  const card = document.querySelector("[data-node='root/%s'] [data-slot=card]");
  const box = card.getBoundingClientRect();
  const row = card.querySelector("[data-slot=card-content] p").getBoundingClientRect();
  const round = (n) => Math.round(n);
  return [round(row.top - box.top), round(box.bottom - row.bottom), round(row.left - box.left)];
})()"""


async def test_a_card_without_padding_is_filled_to_its_edges() -> None:
    app = mw.App("flush", public=None)

    @app.page("/")
    def home(s: mw.Session) -> ui.Page:
        def row() -> ui.Text:
            return ui.Text("Row", cls="block border-b px-4 py-3")

        return ui.Page(
            ui.Card(row(), padding=False, key="bare"),
            ui.Card(row(), padding=False, title="Rows", key="titled"),
            ui.Card(row(), padding=False, footer=ui.Text("Foot"), key="footed"),
            ui.Card(row(), key="padded"),
        )

    async with Page(app) as page:
        # Nothing between what the card holds and its edge on any side.
        assert await page.read(EDGES % "bare") == [0, 0, 0]
        # A title keeps the room above it, and what is under it still
        # reaches the sides and the bottom.
        top, bottom, left = await page.read(EDGES % "titled")
        assert top > 40 and (bottom, left) == (0, 0)
        # With a footer under it, it still starts at the top edge.
        top, _, left = await page.read(EDGES % "footed")
        assert (top, left) == (0, 0)
        # A card with its padding has it all around.
        assert await page.read(EDGES % "padded") == [16, 16, 16]


LINES = """Object.fromEntries([...document.querySelectorAll("%s a")].map((a) => [
  a.textContent.trim(), getComputedStyle(a).textDecorationLine,
]))"""


async def test_the_header_draws_a_line_under_the_link_of_the_page_it_is_on() -> None:
    app = mw.App("places", public=None)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        def links() -> list[ui.Link]:
            return [
                ui.Link(label="Overview", href="/"),
                ui.Link(label="Bills", href="/bills", active=True),
            ]

        return ui.Page(
            ui.Header(title="Places", logo=False, links=links()), ui.Row(*links(), key="row")
        )

    async with Page(app) as page:
        await wide(page)
        assert await page.read(LINES % "header nav") == {"Overview": "none", "Bills": "underline"}
        # Anywhere else a link is underlined, the current one and the others.
        assert await page.read(LINES % "[data-node='root/row']") == {
            "Overview": "underline",
            "Bills": "underline",
        }


# Where a field of a form stands in the window, and how wide it is.
PLACED = """(() => {
  const at = (f) => document.querySelector(`[data-field="${f}"]`).getBoundingClientRect();
  const box = (f) => [at(f).left, at(f).top, at(f).width].map(Math.round);
  return Object.fromEntries(%s.map((f) => [f, box(f)]));
})()"""


async def test_a_row_that_becomes_another_variant_keeps_what_both_have() -> None:
    class Part(BaseModel):
        name: str = ""
        amount: float = 1

    class Oven(BaseModel):
        kind: Literal["oven"] = "oven"
        id: int | None = Field(default=None, json_schema_extra={"hidden": True})
        ref: str = ""
        title: str = ""
        minutes: int = 30
        degrees: int = 180

    class Rest(BaseModel):
        kind: Literal["rest"] = "rest"
        id: int | None = Field(default=None, json_schema_extra={"hidden": True})
        ref: str = ""
        title: str = ""
        minutes: int = 30

    class Side(BaseModel):
        parts: list[Part] = []

    class Recipe(BaseModel):
        name: str = ""
        serves: int = 4
        parts: list[Part] = []
        step: Annotated[Oven | Rest, Field(discriminator="kind")] = Oven()
        side: Side = Side()

    got: list[dict[str, Any]] = []
    app = mw.App("variants", public=None)
    start = Recipe(
        parts=[Part(name="Flour", amount=500)],
        step=Oven(id=7, ref="r-7", minutes=12, degrees=250),
        side=Side(parts=[Part(name="Oil", amount=2)]),
    )

    def made(s: mw.Session, recipe: Recipe) -> None:
        got.append(recipe.step.model_dump())

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        # One field a row holds unseen is left out by the model, the other
        # by the form.
        hide = {"/step/ref": {"widget": "hidden"}}
        return ui.Page(
            ui.Form(
                Recipe,
                initial=start,
                layout=2,
                labels={"/side": {"label": "On the side"}},
                overrides=hide,
                submit="Make",
                on_submit=made,
            )
        )

    async with Page(app) as page:
        await wide(page)
        await page.type("/step/title", "Typed by hand")
        await page.click('[data-field="/step"] [role=combobox]')
        await page.click("[role=option]", "Rest")
        assert "/step/degrees" not in await page.fields()
        await page.press("Make")
        # Back again, the oven has its own degrees and what the row kept.
        await page.click('[data-field="/step"] [role=combobox]')
        await page.click("[role=option]", "Oven")
        await page.press("Make")
        # In a form of two columns a list and a union lie across both, and
        # the fields of a row stand in the same two.
        fields = ["/name", "/serves", "/parts", "/parts/0/name", "/parts/0/amount", "/step"]
        fields += ["/side", "/side/parts/0/name", "/side/parts/0/amount"]
        at = await page.read(PLACED % json.dumps(fields))
        heading = await page.read(
            """document.querySelector('[data-field="/side"] > legend').textContent"""
        )
    assert got == [
        {"kind": "rest", "id": 7, "ref": "r-7", "title": "Typed by hand", "minutes": 12},
        {
            "kind": "oven",
            "id": 7,
            "ref": "r-7",
            "title": "Typed by hand",
            "minutes": 12,
            "degrees": 180,
        },
    ]
    whole = at["/serves"][0] + at["/serves"][2] - at["/name"][0]
    assert at["/parts"][2] == whole and at["/step"][2] == whole
    assert at["/parts/0/name"][1] == at["/parts/0/amount"][1]
    assert at["/parts/0/name"][0] < at["/parts/0/amount"][0]
    # A model in the model is one column wide, where the fields of a row
    # stand under each other, and it is headed by what the form calls it.
    assert at["/side"][2] < whole / 2
    assert at["/side/parts/0/name"][0] == at["/side/parts/0/amount"][0]
    assert at["/side/parts/0/name"][1] < at["/side/parts/0/amount"][1]
    assert heading == "On the side"


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


# The keys of a table's selected rows, in their order.
TOKENS = """(() => {
  const style = getComputedStyle(document.documentElement);
  return ["--background", "--radius"].map((name) => style.getPropertyValue(name).trim());
})()"""


async def test_a_color_of_the_light_scheme_leaves_the_dark_one_its_default() -> None:
    theme = Theme(mode="dark", tokens={"light": {"background": "#ffffff", "radius": "1rem"}})
    app = mw.App("schemes", public=None, theme=theme)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("A page."))

    async with Page(app) as page:
        assert await page.read("document.documentElement.classList.contains('dark')")
        background, radius = await page.read(TOKENS)
        # The length is for both schemes, the color for the light one alone.
        assert radius == "1rem"
        assert background not in ("", "#ffffff")
        await page.read("document.documentElement.classList.remove('dark')")
        assert await page.read(TOKENS) == ["#ffffff", "1rem"]


# Of the strip of tabs at a place among the page's strips: whether it has
# more than is in sight, the tab it is on, and whether all of that tab is
# in sight.
STRIP = """(() => {
  const list = document.querySelectorAll("[role=tablist]")[%d];
  const strip = list.parentElement.getBoundingClientRect();
  const chosen = list.querySelector("[aria-selected=true]");
  const at = chosen.getBoundingClientRect();
  return [
    list.parentElement.scrollWidth > list.parentElement.clientWidth,
    chosen.textContent,
    at.left >= strip.left - 0.5 && at.right <= strip.right + 0.5,
  ];
})()"""

# Whether that strip lies within the window from side to side.
WITHIN = """(() => {
  const box = document.querySelectorAll("[role=tablist]")[%d].parentElement.getBoundingClientRect();
  return box.left >= 0 && box.right <= innerWidth;
})()"""


async def test_a_strip_of_tabs_wider_than_a_phone_scrolls_and_shows_the_tab_it_is_on() -> None:
    class Desk(BaseModel):
        at: str = "overview"

    app = mw.App("strips", state=Desk, public=None)
    names = ("Overview", "Activity", "Settings", "Members", "Billing", "Integrations")

    def last(s: mw.Session[Desk], _: Any) -> None:
        s.state.at = "integrations"

    def tabs(key: str, **how: Any) -> ui.Component:
        return ui.Tabs(*[ui.Tab(ui.Text(n), id=n.lower(), label=n) for n in names], key=key, **how)

    @app.page("/")
    def home(s: mw.Session[Desk]) -> ui.Component:
        return ui.Page(
            tabs("pill", default="overview", variant="pill"),
            tabs("late", default="integrations"),
            tabs("held", value=s.state.at),
            ui.Button("To the last", on_click=last),
            # Where the tabs would take the width of their strip.
            ui.Row(tabs("row", default="overview")),
            ui.Stack(tabs("middle", default="overview"), align="center"),
        )

    wide = "document.documentElement.scrollWidth > innerWidth"
    async with Page(app) as page:
        # On a desk the strips fit, and nothing about them scrolls.
        assert [await page.read(STRIP % n) for n in range(3)] == [
            [False, "Overview", True],
            [False, "Integrations", True],
            [False, "Overview", True],
        ]
        # The window is made as narrow as a phone while the page is open. It
        # stays a desk's window: a browser that is switched to a phone's ways
        # puts everything that scrolls back at its start, which no phone does.
        await page.tab.call(
            "Emulation.setDeviceMetricsOverride",
            width=390,
            height=800,
            deviceScaleFactor=1,
            mobile=False,
        )
        await page.rest()
        assert not await page.read(wide)
        assert [await page.read(STRIP % n) for n in range(3)] == [
            [True, "Overview", True],
            [True, "Integrations", True],
            [True, "Overview", True],
        ]
        # A choice of the page's brings its tab into sight.
        await page.press("To the last")
        assert await page.read(STRIP % 2) == [True, "Integrations", True]
        # So does a press on a tab that is partly out of sight.
        await page.read(
            "(() => { const strip = document.querySelector('[role=tablist]').parentElement;"
            " strip.scrollLeft = strip.scrollWidth - strip.clientWidth - 30; })()"
        )
        await page.click("[role=tablist] [role=tab]", "Integrations")
        assert await page.read(STRIP % 0) == [True, "Integrations", True]
        assert not await page.read(wide)
        # In a row and in the middle of a column the strip is no wider than
        # the page either, and has its first tab in sight.
        for n in (3, 4):
            assert await page.read(STRIP % n) == [True, "Overview", True]
            assert await page.read(WITHIN % n)


SELECTED = """[...document.querySelectorAll("[data-node='root/%s'] tr[data-state=selected]")]
  .map((r) => Number(r.dataset.part)).sort((a, b) => a - b)"""


async def test_shift_selects_the_rows_from_the_last_one_used_to_this_one() -> None:
    class Picked(BaseModel):
        keys: list[int] = []

    app = mw.App("crew", state=Picked, public=None)
    names = ["Hal", "Ada", "Gus", "Ben", "Fay", "Cas", "Eli", "Dee"]

    def pick(s: mw.Session[Picked], keys: list[int]) -> None:
        s.state.keys = keys

    def table(key: str, **how: Any) -> ui.Component:
        return ui.Table(
            key=key,
            rows=[{"id": n, "name": name} for n, name in enumerate(names, 1)],
            columns=[ui.Column(key="name")],
            selection="rows",
            on_select=pick,
            **how,
        )

    @app.page("/")
    def home(s: mw.Session[Picked]) -> ui.Component:
        return ui.Page(
            table("all", selected=s.state.keys),
            table("paged", selected=s.state.keys, page_size=4),
            ui.Button("Clear", key="clear", on_click=lambda s, _: s.state.keys.clear()),
        )

    def box(n: int, of: str = "all") -> str:
        return f"[data-node='root/{of}'] tr[data-part='{n}'] [role=checkbox]"

    async with Page(app) as page:
        await wide(page)

        # A press on a name leaves where a selection of text would start.
        await page.click("[data-node='root/all'] tr[data-part='1'] td:nth-child(2)")
        await page.click(box(2))
        await page.click(box(5), shift=True)
        assert await page.read(SELECTED % "all") == [2, 3, 4, 5]
        assert await page.read("getSelection().toString()") == ""
        # The keyboard is where the mouse was last, as after any press.
        assert await page.read(
            f"document.activeElement === document.querySelector({json.dumps(box(5))})"
        )
        # A row that was selected is cleared, and the rows up to it with it.
        await page.click(box(3), shift=True)
        assert await page.read(SELECTED % "all") == [2]
        # The rows between are those shown between: sorted by name, Ben
        # and Dee have Cas between them and no other.
        await page.click("[data-node='root/all'] th button", "name")
        await page.click(box(4))
        await page.click(box(8), shift=True)
        assert await page.read(SELECTED % "all") == [2, 4, 6, 8]

        # With nothing selected there is nothing to extend, also where a
        # row was used before.
        await page.press("Clear")
        await page.click(box(1), shift=True)
        assert await page.read(SELECTED % "all") == [1]
        # The keyboard does what the mouse does.
        await page.read(f"document.querySelector({json.dumps(box(7))}).focus()")
        await page.key(" ", 32, shift=True)
        assert await page.read(SELECTED % "all") == [1, 3, 5, 7]

        # A range stays on the page in view: the row used on the first page
        # is not where one on the second starts.
        await page.press("Clear")
        await page.click(box(2, "paged"))
        await page.press("Next")
        await page.click(box(7, "paged"), shift=True)
        assert await page.read(SELECTED % "paged") == [7]
        await page.click(box(5, "paged"), shift=True)
        assert await page.read(SELECTED % "paged") == [5, 6, 7]
        assert await page.read(SELECTED % "all") == [2, 5, 6, 7]


# ------------------------------------------------------------- a color that is picked


async def test_a_color_is_picked_by_dragging_typing_and_pressing() -> None:
    class Paint(BaseModel):
        color: str | None = "#3b82f6"
        picks: int = 0
        refused: int = 0
        saved: str = ""

    class Label(BaseModel):
        color: str = Field(
            "#ef4444", json_schema_extra={"widget": "color", "swatches": ["#14b8a6"]}
        )

    app = mw.App("paint", state=Paint, public=None)

    def pick(s: mw.Session[Paint], color: str | None) -> None:
        s.state.picks += 1
        s.state.color = color

    def refuse(s: mw.Session[Paint], color: str | None) -> None:
        s.state.refused += 1

    def save(s: mw.Session[Paint], label: Label) -> None:
        s.state.saved = label.color

    @app.page("/")
    def home(s: mw.Session[Paint]) -> ui.Component:
        st = s.state
        return ui.Page(
            ui.ColorPicker(
                value=st.color,
                swatches=["#ef4444", "#22c55e"],
                clearable=True,
                on_change=pick,
                key="main",
            ),
            # The page holds these two at a color. One has a handler that
            # does not take a pick, and the other has nobody to tell.
            ui.ColorPicker(value="#ff0000", on_change=refuse, key="refused"),
            ui.ColorPicker(value="#00ff00", key="fixed"),
            ui.Text(f"{st.refused} refused", key="refusals"),
            ui.Text(f"{st.picks} picks, now {st.color}, saved {st.saved}", key="said"),
            ui.Form(Label, on_submit=save, key="form"),
        )

    said = "document.querySelector(\"[data-node='root/said']\").textContent"
    button = "[data-node='root/main'] button"
    shown = f"document.querySelector({json.dumps(button)}).textContent.trim()"
    hue = "document.querySelector('.mw-color-strip .mw-color-thumb').style.left"
    is_open = "!!document.querySelector('.mw-color-square')"

    async with Page(app) as page:
        await wide(page)

        async def square() -> tuple[float, float, float, float]:
            x, y, w, h = await page.read(
                "(() => { const r = document.querySelector('.mw-color-square')"
                ".getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()"
            )
            return x, y, w, h

        async def now() -> tuple[int, str]:
            picks, _, rest = (await page.read(said)).partition(" picks, now ")
            return int(picks), rest.partition(",")[0]

        await page.click(button)
        x, y, w, h = await square()

        # A color that is dragged shows here and is not the page's yet.
        await page.drag(".mw-color-square", (x + w * 0.25, y + h * 0.5), let_go=False)
        await page.rest()
        held = (await page.read(shown)).lower()
        assert held != "#3b82f6" and await now() == (0, "#3b82f6")
        # Let go, it is, in one pick. Let go outside, the picker stays.
        await page.let_go((x + w + 300, y + h + 200))
        assert await now() == (1, held) and await page.read(is_open)

        # A gray has no hue of its own, and the strip keeps the one it had.
        was = await page.read(hue)
        await page.drag(".mw-color-square", (x - 40, y + h * 0.5))
        picks, gray = await now()
        assert picks == 2 and gray[1:3] == gray[3:5] == gray[5:7]
        assert await page.read(hue) == was
        await page.drag(".mw-color-square", (x + w * 0.9, y + h * 0.2))
        picks, blue = await now()
        assert picks == 3 and await page.read(hue) == was
        assert int(blue[5:7], 16) > int(blue[1:3], 16)

        # A key held down moves the hue along, and the page hears of it
        # when the key is let go.
        await page.read("document.querySelector('.mw-color-strip').focus()")
        for kind in ("keyDown", "keyDown", "keyDown", "keyUp"):
            await page.tab.call(
                "Input.dispatchKeyEvent",
                type=kind,
                key="ArrowRight",
                code="ArrowRight",
                windowsVirtualKeyCode=39,
            )
        await page.rest()
        picks, turned = await now()
        assert picks == 4 and turned != blue and await page.read(hue) != was

        # A hex code is a color once its six digits are typed.
        await page.read(
            "(() => { const i = document.querySelector('input[aria-label=\"Hex code\"]');"
            " i.focus(); i.select(); })()"
        )
        await page.tab.call("Input.insertText", text="22c55")
        await page.rest()
        assert (await now())[0] == 4
        # A code half typed is not a wrong one.
        assert not await page.read("!!document.querySelector('input[aria-invalid=true]')")
        await page.tab.call("Input.insertText", text="e")
        await page.rest()
        assert await now() == (5, "#22c55e")
        assert await page.read(
            "document.querySelector('.mw-color-swatch[aria-pressed=true]').title"
        ) == ("#22C55E")

        # A color of the app's own is picked with a press, which is all
        # there was to do.
        await page.click(".mw-color-swatch[title='#EF4444']")
        assert await now() == (6, "#ef4444") and not await page.read(is_open)
        await page.click(button)
        await page.click("button[aria-label='No color']")
        assert await now() == (7, "None") and not await page.read(is_open)
        assert await page.read(shown) == "Choose"

        # Three digits are a color when the field is left with Enter.
        await page.click(button)
        await page.read(
            "(() => { const i = document.querySelector('input[aria-label=\"Hex code\"]');"
            " i.focus(); i.select(); })()"
        )
        await page.tab.call("Input.insertText", text="#0af")
        await page.rest()
        assert (await now())[0] == 7
        await page.key("Enter", 13)
        assert await now() == (8, "#00aaff")
        await page.key("Escape", 27)

        def says(key: str) -> str:
            return f"document.querySelector(\"[data-node='root/{key}'] button\").textContent.trim()"

        refusals = "document.querySelector(\"[data-node='root/refusals']\").textContent"

        # A picker the page holds shows the page's color. With nobody to
        # tell, a color that is let go of is gone at once.
        await page.click("[data-node='root/fixed'] button")
        x, y, w, h = await square()
        await page.drag(".mw-color-square", (x + w * 0.5, y + h * 0.9))
        assert await page.read(says("fixed")) == "#00FF00"
        await page.key("Escape", 27)
        # A handler is waited for, and the color stands meanwhile. This one
        # does not take it, so the page's color is back when the wait is over.
        await page.click("[data-node='root/refused'] button")
        x, y, w, h = await square()
        await page.drag(".mw-color-square", (x + w * 0.5, y + h * 0.9))
        assert await page.read(refusals) == "1 refused"
        assert await page.read(says("refused")) != "#FF0000"
        await asyncio.sleep(3.2)
        await page.rest()
        assert await page.read(says("refused")) == "#FF0000"
        # Escape in the middle of a drag takes the drag back.
        await page.drag(".mw-color-square", (x + w * 0.2, y + h * 0.2), let_go=False)
        await page.key("Escape", 27)
        await page.let_go((x + w * 0.2, y + h * 0.2))
        assert not await page.read(is_open)
        assert await page.read(refusals) == "1 refused"
        assert await page.read(says("refused")) == "#FF0000"

        # A field of a form is picked the same way, and saved with the form.
        await page.click("[data-node='root/form'] button[aria-haspopup]")
        await page.click(".mw-color-swatch[title='#14B8A6']")
        await page.press("Save")
        assert (await page.read(said)).endswith("saved #14b8a6")


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
    # A page is there once its heading is, however long the machine takes
    # over it: the page of charts is a while in coming on a slow one. Only
    # then is it given a moment to come to rest.
    drawn = """new Promise((done) => {
      const until = performance.now() + 30000;
      const look = () => {
        if (location.pathname === %s && document.querySelector('.mw-shell-body h1')) done(true);
        else if (performance.now() > until) done(false);
        else setTimeout(look, 25);
      };
      look();
    })"""
    scrolls: list[str] = []
    async with Page(manual.make_app()) as page:
        await wide(page)
        base = (await page.read("location.origin")) or ""
        for path in paths:
            await page.tab.call("Page.navigate", url=base + path)
            assert await page.read(drawn % json.dumps(path)), path
            await page.tab.value(_SETTLE % {"timeout": 4000, "still": 100})
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


AT = "document.activeElement.dataset.part ?? document.activeElement.tagName"


async def test_a_row_that_can_be_pressed_is_pressed_from_the_keyboard() -> None:
    class Seen(BaseModel):
        picked: list[int] = []
        gone: list[int] = []

    app = mw.App("rows", state=Seen, public=None)
    clicked: list[int] = []
    few = [{"id": n, "name": f"row {n}"} for n in range(1, 4)]
    many = [{"id": n, "name": f"row {n}"} for n in range(1, 301)]

    def pick(s: mw.Session[Seen], keys: list[int]) -> None:
        s.state.picked = keys

    def click(s: mw.Session[Seen], key: int) -> None:
        clicked.append(key)

    def dismiss(s: mw.Session[Seen], key: int) -> None:
        s.state.gone.append(key)

    @app.page("/")
    def home(s: mw.Session[Seen]) -> ui.Component:
        return ui.Page(
            ui.Button("Before", key="before"),
            ui.Table(
                key="click",
                rows=few,
                on_row_click=click,
                row_actions=[ui.MenuItem(id="edit", label="Edit")],
                on_action=lambda s, _: None,
            ),
            ui.Table(
                key="pick", rows=few, selection="row", selected=s.state.picked, on_select=pick
            ),
            ui.Table(key="plain", rows=few),
            ui.Table(
                key="inbox",
                rows=[r for r in few if r["id"] not in s.state.gone],
                on_row_click=dismiss,
            ),
            ui.Table(key="long", rows=many, height=300, on_row_click=click),
        )

    def rows_of(of: str, read: str) -> str:
        rows = f"document.querySelectorAll(\"[data-node='root/{of}'] tbody tr\")"
        return f"[...{rows}].map((r) => {read})"

    def stops(of: str) -> str:
        return rows_of(of, "r.getAttribute('tabindex')")

    async with Page(app) as page:
        await wide(page)
        # One row of the table takes Tab, and rows nobody can press take none.
        assert await page.read(stops("click")) == ["0", "-1", "-1"]
        assert await page.read(stops("plain")) == [None, None, None]
        await page.read("document.querySelector(\"[data-node='root/before']\").focus()")
        await page.key("Tab", 9)
        while await page.read("document.activeElement.tagName") == "BUTTON":
            # The buttons that sort come before the rows.
            await page.key("Tab", 9)
        assert await page.read(AT) == "1"
        await page.key("Enter", 13)
        await page.key("ArrowDown", 40)
        assert await page.read(AT) == "2"
        # The row the keyboard is on shows it.
        ring = "(() => { const s = getComputedStyle(document.activeElement);"
        ring += " return [s.outlineStyle, s.outlineWidth, s.outlineOffset]; })()"
        assert await page.read(ring) == ["solid", "3px", "-3px"]
        await page.key(" ", 32)
        await page.key("End", 35)
        assert await page.read(AT) == "3"
        await page.key("ArrowDown", 40)
        assert await page.read(AT) == "3"
        await page.key("Home", 36)
        await page.key("ArrowUp", 38)
        assert await page.read(AT) == "1"
        await page.key("ArrowDown", 40)
        # Tab goes on to what the row holds, and comes back to the row it left.
        assert await page.read(stops("click")) == ["-1", "0", "-1"]
        await page.key("Tab", 9)
        assert await page.read("document.activeElement.tagName") == "BUTTON"
        await page.key("Tab", 9, shift=True)
        assert await page.read(AT) == "2"
        # A key in the menu of a row is the menu's own.
        await page.key("Tab", 9)
        await page.key("Enter", 13)
        await page.key("Escape", 27)
        assert clicked == [1, 2]

        # Space on a row of a table that lets one be picked picks it.
        await page.read("document.querySelector(\"[data-node='root/pick'] tbody tr\").focus()")
        await page.key("ArrowDown", 40)
        await page.key(" ", 32)
        assert await page.read(rows_of("pick", "r.dataset.state ?? ''")) == ["", "selected", ""]

        # A row that goes when it is pressed leaves the keyboard on the row
        # that took its place, and the last row leaves it on the one before.
        await page.read("document.querySelector(\"[data-node='root/inbox'] tbody tr\").focus()")
        await page.key("ArrowDown", 40)
        await page.key("Enter", 13)
        assert await page.read(rows_of("inbox", "r.dataset.part")) == ["1", "3"]
        assert await page.read(AT) == "3"
        await page.key("Enter", 13)
        assert await page.read(AT) == "1"

        # A long table draws some of its rows, and the keyboard reaches them all.
        # A row it goes up to is not left under the header.
        await page.read(
            "document.querySelector(\"[data-node='root/long'] tbody tr[data-part]\").focus()"
        )
        await page.key("End", 35)
        await page.rest()
        assert await page.read(AT) == "300"
        for _ in range(12):
            await page.key("ArrowUp", 38)
        assert await page.read(AT) == "288"
        clear = """(() => {
            const row = document.activeElement.getBoundingClientRect();
            const head = document.querySelector("[data-node='root/long'] thead");
            return row.top >= head.getBoundingClientRect().bottom - 1;
        })()"""
        assert await page.read(clear)
        await page.key("Home", 36)
        await page.rest()
        assert await page.read(AT) == "1"
        await page.key("Enter", 13)
        assert clicked == [1, 2, 1]


async def test_a_chart_that_can_be_pressed_is_pressed_from_the_keyboard() -> None:
    app = mw.App("charts", public=None)
    rows = [{"m": "Jan", "v": 3}, {"m": "Feb", "v": 5}]
    clicks: list[dict[str, Any]] = []

    def note(s: mw.Session, point: dict[str, Any]) -> None:
        clicks.append(point)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.BarChart(rows, x="m", y="v", on_click=note, height=150, key="bar"),
            ui.LineChart(rows, x="m", y="v", on_click=note, height=150, key="line"),
            ui.PieChart(rows, x="m", y="v", on_click=note, height=150, key="pie"),
            ui.BarChart(rows, x="m", y="v", height=150, key="still"),
        )

    async with Page(app) as page:
        await wide(page)
        for name in ("bar", "line", "pie", "still"):
            chart = f"[data-node='root/{name}'] svg[role=application]"
            await page.read(f'document.querySelector("{chart}").focus()')
            await page.rest()
            await page.key("Enter", 13)
            await page.key("ArrowRight", 39)
            await page.key(" ", 32)
        # The bar of a chart with one series is the one pressed, as a pointer
        # would press it. A line is pressed at its x.
        assert [c["x"] for c in clicks] == ["Jan", "Feb"] * 3
        assert clicks[0] == {"x": "Jan", "series": "v", "value": 3, "values": {"v": 3}}
        assert clicks[2] == {"x": "Jan", "series": None, "value": None, "values": {"v": 3}}
        assert clicks[5] == {"x": "Feb", "value": 5, "share": 0.625}
        # A chart the keyboard comes back to shows no tooltip. Enter shows it
        # again, as on a chart nobody can press, and the next one presses.
        await page.read(
            "document.querySelector(\"[data-node='root/bar'] svg[role=application]\").focus()"
        )
        await page.rest()
        del clicks[:]
        await page.key("Enter", 13)
        assert clicks == []
        await page.key("Enter", 13)
        assert [c["x"] for c in clicks] == ["Feb"]
        # The keyboard stops at a pie once.
        stops = "document.querySelectorAll(\"[data-node='root/pie'] [tabindex='0']\").length"
        assert await page.read(stops) == 1


async def test_escape_over_a_multiselects_open_list_leaves_its_dialog_open() -> None:
    app = mw.App("escape", public=None)
    closed: list[bool] = []

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Dialog(
                ui.MultiSelect(options=["North", "South", "East"], key="plain"),
                ui.MultiSelect(options=["North", "South", "East"], sortable=True, key="sorted"),
                open=not closed,
                title="Regions",
                on_close=lambda s, _: closed.append(True),
            ),
        )

    dialog = "!!document.querySelector('[data-slot=dialog-content]')"
    listed = "!!document.querySelector('[role=listbox]')"
    chosen = "document.querySelectorAll('[data-slot=combobox-chip]').length"
    async with Page(app) as page:
        for name in ("plain", "sorted"):
            await page.click(f"[data-node$='/{name}'] input")
            await page.key("ArrowDown", 40)
            await page.key("Enter", 13)
            assert await page.read(listed)
            await page.key("Escape", 27)
            # The key closed the list and went no further.
            assert not await page.read(listed)
            assert await page.read(dialog) and not closed
        assert await page.read(chosen) == 2
        # With no list open, Escape is the dialog's.
        await page.key("Escape", 27)
        assert closed == [True]


async def test_a_chip_longer_than_its_box_is_cut_and_keeps_its_cross() -> None:
    app = mw.App("chips", public=None)
    long = "How satisfied were you with the answer you got, " * 3
    options = ["Short", ui.Option(value="long", label=long, icon="star")]

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Stack(
                ui.MultiSelect(options=options, default=["long", "Short"], key="plain"),
                ui.MultiSelect(options=options, default=["long"], sortable=True, key="sorted"),
                cls="w-72",
            ),
        )

    # How far a chip and its cross stay inside the right edge of their box.
    chips = "[data-node$='/%s'] [data-slot=combobox-chip]"
    room = """[...document.querySelectorAll("CHIPS")].map((c) => {
      const box = c.closest("[data-slot=combobox-chips]").getBoundingClientRect();
      const cross = c.querySelector("[data-slot=combobox-chip-remove]").getBoundingClientRect();
      return [box.right - c.getBoundingClientRect().right >= 0, box.right - cross.right >= 0];
    })""".replace("CHIPS", chips)
    titles = "[...document.querySelectorAll('[data-slot=combobox-chip]')].map((c) => c.title)"
    async with Page(app) as page:
        assert await page.read(room % "plain") == [[True, True], [True, True]]
        assert await page.read(room % "sorted") == [[True, True]]
        # The whole label is there for the pointer.
        assert await page.read(titles) == [long, "Short", long]
        # The cross of the long chip can be pressed.
        await page.click("[data-node$='/plain'] [data-slot=combobox-chip-remove]")
        assert await page.read(titles) == ["Short", long]


@pytest.mark.parametrize("count", [80, 300])
async def test_a_table_that_fills_scrolls_in_the_room_left_and_cuts_a_long_column(
    count: int,
) -> None:
    app = mw.App("fills", public=None)
    long = "Which of these have you used in the past year, counting the ones you tried once?"
    rows = [
        {"id": i, "kind": "single", "text": long if i % 2 else "Age", "note": f"note {i}"}
        for i in range(1, count + 1)
    ]

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        columns = [
            ui.Column(key="id", width=90),
            ui.Column(key="kind", format="badge"),
            ui.Column(key="text", lines=1),
            ui.Column(key="note"),
        ]
        table = ui.Table(rows=rows, columns=columns, search=True, fill=True, key="t")
        return ui.Page(
            ui.Split(
                ui.Stack(ui.Text("Above the table"), table, fill=True, cls="p-4"),
                ui.Text("Beside it"),
                sizes=[50, 50],
            ),
        )

    measured = """(() => {
      const box = document.querySelector("[data-node$='/t'] .mw-scroll");
      const at = box.getBoundingClientRect();
      const heads = [...box.querySelectorAll("thead th")];
      const cut = [...box.querySelectorAll("tbody td div[title]")].find((d) => d.title.length > 9);
      return {
        bottom: at.bottom,
        page: document.documentElement.scrollHeight,
        scrolls: box.scrollHeight > box.clientHeight,
        sideways: box.scrollWidth > box.clientWidth,
        widths: heads.map((h) => Math.round(h.getBoundingClientRect().width)),
        cut: cut.scrollWidth > cut.clientWidth,
        title: cut.title,
      };
    })()"""
    async with Page(app) as page:
        await wide(page)
        seen = await page.read(measured)
        # The table ends in the window and scrolls its own rows, not the page.
        assert seen["bottom"] <= 700 and seen["page"] == 700 and seen["scrolls"]
        # The long column takes what the others leave and is cut, with its
        # whole text for the pointer. A column that said its width has it,
        # also in a table long enough to draw only the rows in view.
        assert not seen["sideways"] and seen["cut"] and seen["title"] == long
        assert seen["widths"][0] == 90 and seen["widths"][2] > 150
        # The search reads what the cut hides.
        await page.read("document.querySelector(\"[data-node$='/t'] input\").focus()")
        await page.tab.call("Input.insertText", text="tried once")
        await page.rest()
        summary = "document.querySelector(\"[data-node$='/t']\").lastElementChild.textContent"
        assert f"{count // 2} of {count} rows" in await page.read(summary)


async def test_a_forms_button_turns_when_its_submit_takes_a_moment() -> None:
    app = mw.App("saving", public=None)

    class Name(BaseModel):
        name: str = "Ada"

    async def slow(s: mw.Session, doc: Name) -> None:
        await s.task(asyncio.sleep, 0.9)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Form(Name, on_submit=slow, key="slow"),
            ui.Form(Name, on_submit=lambda s, doc: None, key="fast"),
        )

    def button(form: str) -> str:
        return (
            f"(() => {{ const b = document.querySelector(\"[data-node$='/{form}'] "
            'button[type=submit]"); return [b.disabled, !!b.querySelector("svg")]; })()'
        )

    def submit(form: str) -> str:
        return f"document.querySelector(\"[data-node$='/{form}'] button[type=submit]\").click()"

    async with Page(app) as page:
        # A submit that is answered at once never turns its button.
        turned = """new Promise((done) => {
          const b = document.querySelector("[data-node$='/fast'] button[type=submit]");
          let seen = false;
          const watch = new MutationObserver(() => { seen ||= !!b.querySelector("svg"); });
          watch.observe(b, { childList: true, subtree: true });
          b.click();
          setTimeout(() => done([b.disabled, seen]), 600);
        })"""
        assert await page.read(turned) == [False, False]
        # One that takes a moment greys the button at once and turns it after.
        await page.read(submit("slow"))
        await asyncio.sleep(0.1)
        assert await page.read(button("slow")) == [True, False]
        await asyncio.sleep(0.45)
        assert await page.read(button("slow")) == [True, True]
        await asyncio.sleep(0.8)
        await page.rest()
        assert await page.read(button("slow")) == [False, False]


@pytest.mark.parametrize("kind", ["dialog", "sheet"])
async def test_the_cross_of_a_dialog_or_a_sheet_lies_over_nothing(kind: str) -> None:
    app = mw.App("cross", public=None)
    made = ui.Dialog if kind == "dialog" else ui.Sheet
    long = "A title that is long enough to reach the far edge of what it is the title of"

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        titled = s.query.get("titled") == "1"
        field = ui.Input(value="delivery", clearable=True, key="field")
        return ui.Page(made(field, open=True, title=long if titled else None, key="over"))

    # Whether the cross lies clear of the title and of the first thing under it.
    clear = f"""(() => {{
      const cross = document.querySelector("[data-slot={kind}-close]").getBoundingClientRect();
      const apart = (e) => {{
        const r = e.getBoundingClientRect();
        return r.right <= cross.left || r.top >= cross.bottom;
      }};
      const title = document.querySelector("[data-slot={kind}-title]");
      const field = document.querySelector("[data-slot={kind}-body] input");
      return [title ? apart(title) : null, apart(field)];
    }})()"""
    async with Page(app) as page:
        await wide(page)
        assert await page.read(clear) == [None, True]
        await page.tab.call("Page.navigate", url=await page.read("location.origin") + "/?titled=1")
        assert await page.tab.value(DRAWN)
        await page.rest()
        assert await page.read(clear) == [True, True]


@pytest.mark.parametrize("mark", ["help", "info", "underline"])
async def test_a_tooltip_is_behind_the_mark_the_theme_chooses(mark: str) -> None:
    app = mw.App("tips", public=None, theme=Theme(tooltip_mark=mark))  # type: ignore[arg-type]
    pressed: list[bool] = []

    class Line(BaseModel):
        text: str = ""

    class Export(BaseModel):
        decimals: int = Field(1, json_schema_extra={"tooltip": "Rounded, not cut."})
        totals: bool = Field(True, json_schema_extra={"tooltip": "A last row of sums."})
        lines: list[Line] = Field([], json_schema_extra={"tooltip": "Above the table."})
        name: str = ""

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Card(
                ui.Form(Export, on_submit=lambda s, doc: None, key="form"),
                ui.Field(ui.Input(key="zone"), label="Zone", tooltip="Of the dates."),
                title="Export",
                tooltip="Of the table as it is.",
                on_click=lambda s, _: pressed.append(True),
                key="card",
            ),
        )

    marks = """[...document.querySelectorAll("[data-slot=info-tip]")].map((m) => [
      m.tagName, !!m.querySelector("svg"), m.getAttribute("aria-label"),
      getComputedStyle(m).textDecorationStyle, m.textContent,
      m.getAttribute("aria-description")])"""
    shown = (
        "[...document.querySelectorAll('[data-slot=tooltip-content]')].map((e) => e.textContent)"
    )
    title = "[data-slot=card-title] [data-slot=info-tip]"
    async with Page(app) as page:
        found = await page.read(marks)
        # The card, three fields of the form, one of them a list, and the
        # field built by hand. The field without a tooltip has no mark.
        assert len(found) == 5
        if mark == "underline":
            assert [m[0] for m in found] == ["SPAN"] * 5 and not any(m[1] for m in found)
            assert {m[3] for m in found} == {"dotted"}
            assert [m[4] for m in found] == ["Export", "Decimals", "Totals", "Lines", "Zone"]
            # The explanation is the text's description, for a screen reader.
            assert found[1][5] == "Rounded, not cut."
        else:
            assert [m[0] for m in found] == ["BUTTON"] * 5 and all(m[1] for m in found)
            # The explanation is the mark's name, for a screen reader.
            assert found[0][2] == "Of the table as it is." and found[1][2] == "Rounded, not cut."
        # A label without a tooltip is as wide as its field, as it was.
        wide_as_field = """(() => {
          const field = document.querySelector('[data-field="/name"]');
          const label = field.querySelector("label").getBoundingClientRect();
          return Math.round(label.width) === Math.round(field.getBoundingClientRect().width);
        })()"""
        assert await page.read(wide_as_field)
        # The keyboard reaches a mark, and the explanation shows there.
        await page.read("document.querySelectorAll('[data-slot=info-tip]')[1].focus()")
        await page.key("Shift", 16)
        await asyncio.sleep(0.8)
        assert await page.read(shown) == ["Rounded, not cut."]
        await page.key("Escape", 27)
        await page.read("document.activeElement.blur()")
        await asyncio.sleep(0.4)
        assert await page.read(shown) == []
        if mark == "underline":
            # The title of a card that can be pressed still presses it.
            await page.click(title)
            assert pressed == [True]
            return
        # A press on an icon is the icon's, and does not press the card it
        # is in. It shows the explanation, which is how a finger asks.
        at = await page.middle(title)
        for kind in ("touchStart", "touchEnd"):
            points = [{"x": at[0], "y": at[1]}] if kind == "touchStart" else []
            await page.tab.call("Input.dispatchTouchEvent", type=kind, touchPoints=points)
        await asyncio.sleep(0.6)
        assert await page.read(shown) == ["Of the table as it is."]
        assert pressed == []
