"""Small things an app ran into: a custom component's class, a plain meter,
the tone of a toast in a test."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

import millwork as mw
from millwork import ui
from millwork.nodes import build
from millwork.testing import Notice, TestApp


def test_a_custom_prop_may_not_take_the_components_own_names() -> None:
    with pytest.raises(ValueError, match="named \\['cls'\\]"):
        ui.Custom("Pond", props={"cls": "x", "fish": 3})
    with pytest.raises(ValueError, match="on_event"):
        ui.Custom("Pond", props={"on_event": 1})
    ui.Custom("Pond", props={"name": "a prop of its own", "children": 2})
    pond = ui.Custom("Pond", props={"fish": 3}, cls="lg:col-span-2", hidden=False)
    node = mw.nodes.build(pond).nodes["root"]
    assert node.props["cls"] == "lg:col-span-2" and node.props["fish"] == 3


def test_a_progress_bar_can_be_a_plain_meter() -> None:
    meter = mw.nodes.build(ui.Progress(value=0.4, label="Energy", percent=False)).nodes["root"]
    assert meter.props["percent"] is False
    assert mw.nodes.build(ui.Progress(value=0.4)).nodes["root"].props["percent"] is True


async def test_the_harness_shows_each_toasts_tone(tmp_path: Path) -> None:
    app = mw.App("t", public=None, bundle_dir=tmp_path)

    async def warn(s: mw.Session, _: Any) -> None:
        s.toast("Careful.", tone="warning", title="Pond")
        s.toast("Fine.")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Button("go", key="go", on_click=warn))

    async with TestApp(app).open("/") as page:
        await page.click("go")
        assert page.toasts == ["Careful.", "Fine."]
        assert page.notices == [Notice("Careful.", "warning", "Pond"), Notice("Fine.", "default")]


def test_a_sidebar_group_has_one_owner_of_its_open_state() -> None:
    from millwork import ui

    group = ui.SidebarGroup(ui.Link(label="A", href="/a"), label="Part", default_open=False)
    assert group.default_open is False and group.label == "Part"
    with pytest.raises(ValueError):
        ui.SidebarGroup(label="Part", open=True, default_open=True)


def test_a_text_field_says_whether_the_browser_checks_its_spelling() -> None:
    assert ui.Input().spellcheck is None and ui.Textarea().spellcheck is None
    assert ui.Input(spellcheck=False).spellcheck is False
    assert ui.Textarea(spellcheck=True).spellcheck is True


def test_a_text_field_can_show_its_count() -> None:
    assert ui.Input().counter is False and ui.Textarea().counter is False
    counted = build(ui.Page(ui.Input(max_length=20, counter=True, key="title")), "root")
    props = counted.nodes["root/title"].props
    assert props["counter"] is True and props["max_length"] == 20
    assert (
        build(ui.Page(ui.Textarea(counter=True, key="notes")), "root")
        .nodes["root/notes"]
        .props["counter"]
    )


def test_a_form_field_shows_its_count_by_an_override() -> None:
    class Note(BaseModel):
        title: str = Field("", max_length=20)
        notes: str = Field("", max_length=300)

    form = ui.Form(Note, overrides={"/notes": {"counter": True}}, on_submit=lambda s, v: None)
    fields = {f["name"]: f for f in build(form).nodes["root"].props["schema"]["fields"]}
    assert fields["notes"]["counter"] is True and fields["notes"]["max_length"] == 300
    assert "counter" not in fields["title"]


def test_a_stat_takes_any_numbers_as_its_trend() -> None:
    whole: list[int] = [1, 2, 3]
    assert ui.Stat(label="Releases", value="3", trend=whole).trend == [1, 2, 3]
    assert ui.Stat(label="Releases", value="3", trend=(0.5, 1.5)).trend == [0.5, 1.5]
    # What is not a sequence is taken as well, and held as a list.
    assert ui.Stat(label="Releases", value="3", trend=(n for n in whole)).trend == [1, 2, 3]
    assert ui.Stat(label="Releases", value="3", trend={"a": 1, "b": 2}.values()).trend == [1, 2]


class _Shaky(BaseModel):
    broken: bool = True
    opened: int = 0


def _shaky_app(debug: bool = False) -> mw.App:
    app = mw.App("shaky", state=_Shaky, public=None, components=None, debug=debug)

    @app.page("/")
    def home(s: mw.Session[_Shaky]) -> ui.Component:
        return ui.Page(ui.Button("Open", key="open", on_click=lambda s, _: s.navigate("/shaky")))

    @app.page("/shaky")
    def shaky(s: mw.Session[_Shaky]) -> ui.Component:
        s.state.opened += 1
        if s.state.broken:
            raise RuntimeError("the database is away")
        return ui.Page(ui.Text("All is well", key="well"))

    return app


async def test_a_page_that_raises_before_anything_is_shown_gets_a_failure_page() -> None:
    async with TestApp(_shaky_app(), strict=False).open("/shaky") as page:
        assert [type(exc) for _, exc in page.failures] == [RuntimeError]
        assert "Something went wrong" in page.text() and "could not be shown" in page.text()
        # The exception is the author's to read, in debug mode only.
        assert "database" not in page.text()
        assert not any(getattr(m, "type", None) == "error" for m in page.messages)

        # Trying again while it still fails says so, and the page stays.
        await page.click("retry")
        assert getattr(page.messages[-1], "type", None) == "error"
        assert "Something went wrong" in page.text()

        # Once the page function works, its page takes the failure page's place.
        page.session.state.broken = False
        await page.click("retry")
        assert page.text() == "All is well"


async def test_a_navigation_to_a_page_that_raises_lands_on_the_failure_page() -> None:
    async with TestApp(_shaky_app(debug=True), strict=False).open("/") as page:
        await page.click("open")
        assert page.session.path == "/shaky"
        text = page.text()
        assert "Something went wrong" in text and "RuntimeError: the database is away" in text
        # From anywhere but the home page there is a way home.
        await page.click("home")
        assert page.session.path == "/" and page.find(ui.Button).props["label"] == "Open"


async def test_a_page_that_works_again_is_mounted_over_the_failure_page() -> None:
    app = mw.App("flat", state=_Shaky, public=None, components=None, debug=True)

    @app.page("/")
    def flat(s: mw.Session[_Shaky]) -> ui.Component:
        if s.state.broken:
            raise RuntimeError("away")
        return ui.Page(ui.Text("a"), ui.Text("b"), ui.Text("c"), ui.Text("d"))

    async with TestApp(app, strict=False).open("/") as page:
        page.session.state.broken = False
        seen = len(page.messages)
        await page.click("retry")
        kinds = [getattr(m, "type", None) for m in page.messages[seen:]]
        # A mount, so the tab starts the page as it starts any page, and
        # nothing is compared with the failure page's rows.
        assert "mount" in kinds and "patch" not in kinds
        assert not page.session._warned and not page.toasts


class _Mute(Exception):
    def __str__(self) -> str:
        raise RuntimeError("cannot say")


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (ValueError("cannot read caf\udce9.txt"), "ValueError: cannot read caf\\udce9.txt"),
        (_Mute(), "_Mute"),
        (RuntimeError("x" * 5000), "RuntimeError: " + "x" * 1986),
    ],
)
async def test_the_failure_page_shows_whatever_was_raised(error: Exception, shown: str) -> None:
    app = mw.App("odd", public=None, components=None, debug=True)

    @app.page("/")
    def odd(s: mw.Session[Any]) -> ui.Component:
        raise error

    async with TestApp(app, strict=False).open("/") as page:
        assert not page.session.over
        assert page.find(ui.Code).props["content"] == shown


async def test_a_failed_render_keeps_nothing_of_the_call_alive() -> None:
    import gc
    import logging
    import weakref

    class Rows:
        pass

    seen: list[weakref.ref[Rows]] = []
    app = _shaky_app()

    @app.page("/heavy")
    def heavy(s: mw.Session[_Shaky]) -> ui.Component:
        rows = Rows()
        seen.append(weakref.ref(rows))
        raise RuntimeError("away")

    async with TestApp(app, strict=False).open("/") as page:
        # The harness keeps what was raised, for the test to read, and the
        # test runner keeps the log record of it. A running app keeps neither.
        page.session.on_failure = None
        logging.disable(logging.CRITICAL)
        try:
            page.session.navigate("/heavy")
            await page.settle()
        finally:
            logging.disable(logging.NOTSET)
        assert "Something went wrong" in page.text()
        gc.collect()
        assert seen and seen[-1]() is None


def test_a_handler_made_with_partial_is_checked_once_per_shape(monkeypatch) -> None:
    from functools import partial

    from millwork import nodes

    def act(s: object, payload: object, who: int = 0) -> None: ...

    asked = []
    real = nodes._handler_problem
    monkeypatch.setattr(
        nodes, "_handler_problem", lambda fn, count: asked.append(fn) or real(fn, count)
    )
    nodes._HANDLER_SHAPES.clear()

    def made(handler: object) -> None:
        build(ui.Page(ui.Button("Go", on_click=handler)))

    for who in range(50):
        made(partial(act, who=who))
    assert len(asked) == 1
    # Another shape of the same function is another question, asked once.
    for _ in range(2):
        with pytest.raises(TypeError, match="on_click takes a handler of"):
            made(partial(act, None, None))
    assert len(asked) == 2
    # A partial of a partial, and one around something that has no code.
    made(partial(partial(act, who=1), who=2))

    class Callable_:
        def __call__(self, s: object, payload: object) -> None: ...

    made(partial(Callable_()))
    with pytest.raises(TypeError, match="on_click takes a handler of"):
        made(partial(lambda: None))


def test_a_form_passes_the_rows_of_a_textarea_on() -> None:
    class Notes(BaseModel):
        text: str = ""

    form = ui.Form(Notes, overrides={"/text": {"widget": "textarea", "rows": 10}})
    field = build(form).nodes["root"].props["schema"]["fields"][0]
    assert field["widget"] == "textarea" and field["rows"] == 10


async def test_events_are_handled_in_the_order_they_came_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two events sent one behind the other while the user is due to be
    checked again: the first asks, the answer comes at once, and the second
    finds it there without having waited. It must not get ahead for that."""
    import asyncio

    from millwork import work
    from millwork.protocol import Event

    asked = 0

    async def stay_current(s: mw.Session) -> bool:
        nonlocal asked
        asked += 1
        if asked == 1:
            # The one who asks waits for the answer, however soon it comes.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        return True

    app = mw.App("t", public=None, bundle_dir=tmp_path)
    order: list[str] = []

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Input(key="name", on_change=lambda s, v: order.append(f"typed {v}")),
            ui.Button("save", key="save", on_click=lambda s, _: order.append("save")),
            ui.Tabs(
                ui.Tab(ui.lazy(lambda: ui.Text("a"))(), id="a", label="A"),
                ui.Tab("b", id="b", label="B"),
                ui.Tab("c", id="c", label="C"),
                key="tabs",
            ),
        )

    async with TestApp(app).open("/") as page:
        s = page.session
        name, save, tabs = page.find("name").id, page.find("save").id, page.find("tabs").id
        monkeypatch.setattr(work, "stay_current", stay_current)
        s.event(Event(node=name, name="change", payload="new"))
        s.event(Event(node=save, name="click"))
        await page.settle()
        assert order == ["typed new", "save"]
        # The same for what a tab says about its tabs: the last word stands.
        asked = 0
        s.event(Event(node=tabs, name="show", payload="c"))
        s.event(Event(node=tabs, name="show", payload="b"))
        await page.settle()
        assert s._showing == {tabs: "b"}


async def test_a_fixed_row_with_an_optional_child_is_no_list_without_keys(tmp_path: Path) -> None:
    class S(BaseModel):
        more: bool = False
        rows: list[str] = ["a", "b", "c", "d"]

    app = mw.App("w", state=S, public=None, bundle_dir=tmp_path, debug=True)

    def flip(s: mw.Session[S], _: Any) -> None:
        s.state.more = not s.state.more

    def grow(s: mw.Session[S], _: Any) -> None:
        s.state.rows.append("e")

    @app.page("/")
    def home(s: mw.Session[S]) -> ui.Component:
        st = s.state
        return ui.Page(
            # Four children written out, one of them there or not: the places
            # stay where they are, and nothing is redrawn that a key would save.
            ui.Row(
                ui.Badge("a"),
                ui.Badge("b"),
                ui.Badge("c"),
                ui.Badge("d") if st.more else None,
                key="fixed",
            ),
            # Rows made from data: one more of them moves every place after it.
            ui.Row(*(ui.Badge(r) for r in st.rows), key="made"),
            ui.Button("flip", key="flip", on_click=flip),
            ui.Button("grow", key="grow", on_click=grow),
        )

    async with TestApp(app).open("/") as page:
        warned = lambda: [  # noqa: E731
            c.args["message"]
            for c in page.commands
            if c.name == "toast" and c.args.get("title") == "millwork"
        ]
        await page.click("flip")
        await page.click("flip")
        assert not any("without keys" in w for w in warned())
        await page.click("grow")
        assert [w.split(" is ")[0] for w in warned() if "without keys" in w] == ["root/made"]


async def test_an_icon_file_that_is_not_there_is_said_once(tmp_path: Path) -> None:
    (tmp_path / "public" / "icons").mkdir(parents=True)
    (tmp_path / "public" / "icons" / "rocket.svg").write_text("<svg/>")
    app = mw.App("i", public=tmp_path / "public", bundle_dir=tmp_path, debug=True)
    # Made once, outside any page, as an app's links often are.
    links = [ui.Link(label="Early", href="/", icon="/public/icons/early.svg")]

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Button("there", icon="/public/icons/rocket.svg", key="there"),
            ui.Button("gone", icon="/public/icons/missing.svg", key="gone"),
            ui.Button("again", icon="/public/icons/missing.svg", key="again", on_click=again),
            ui.Input(prefix_icon="/public/icons/lens.svg", key="field"),
            header=ui.Header(title="Icons", links=links),
        )

    def again(s: mw.Session, _: Any) -> None:
        s.refresh()

    async with TestApp(app).open("/") as page:
        await page.click("again")
        said = [c.args["message"] for c in page.commands if c.args.get("title") == "millwork"]
        assert sorted(m.split()[2] for m in said if "icon" in m) == [
            "/public/icons/early.svg",
            "/public/icons/lens.svg",
            "/public/icons/missing.svg",
        ]


def test_a_page_function_that_asks_for_more_than_the_session_fails_where_it_is_added() -> None:
    app = mw.App("p", public=None)

    with pytest.raises(TypeError, match=r"/jobs/\{job_id\}.*job\(s, job_id\).*s\.params"):

        @app.page("/jobs/{job_id}")
        def job(s: Any, job_id: Any) -> ui.Component:
            return ui.Page()

    with pytest.raises(TypeError, match="session alone"):
        app.not_found(lambda: ui.Page())

    assert app.pages == []
    # What can be called with the session alone is a page function, whatever
    # else it could take.
    app.page("/a")(lambda s, extra=None: ui.Page())
    app.page("/b")(lambda *args: ui.Page())


async def test_a_field_cleared_right_after_typing_is_told_so() -> None:
    from millwork.protocol import Event

    class Draft(BaseModel):
        text: str = ""
        posted: list[str] = []

    app = mw.App("composer", state=Draft, public=None)

    def post(s: mw.Session[Draft], _: Any) -> None:
        s.state.posted.append(s.state.text)
        s.state.text = ""

    @app.page("/")
    def home(s: mw.Session[Draft]) -> ui.Component:
        return ui.Page(
            ui.Textarea(
                value=s.state.text, on_change=lambda s, v: setattr(s.state, "text", v), key="box"
            ),
            ui.Input(
                value=s.state.text,
                on_change=lambda s, v: setattr(s.state, "text", v),
                on_submit=post,
                key="line",
            ),
            ui.Button("Post", on_click=post, key="post"),
        )

    def nothing() -> None:
        return None

    async def waits(s: mw.Session[Draft], v: str) -> None:
        s.state.text = v
        await s.task(nothing, label="Checking", quiet=True)

    def raises(s: mw.Session[Draft], v: str) -> None:
        s.state.text = v
        raise RuntimeError("after the value was kept")

    @app.page("/more")
    def more(s: mw.Session[Draft]) -> ui.Component:
        return ui.Page(
            ui.Textarea(value=s.state.text, on_change=waits, key="waits"),
            ui.Textarea(value=s.state.text, on_change=raises, key="raises"),
            ui.Button("Post", on_click=post, key="post"),
        )

    def told(page: Any, node: str) -> list[Any]:
        return [
            op.props["value"]
            for patch in page.patches
            for op in patch.ops
            if op.op == "set" and op.id == node and "value" in op.props
        ]

    async with TestApp(app).open("/") as page:
        box, line, button = page.find("box").id, page.find("line").id, page.find("post").id
        # A button pressed right after typing: the tab sends the field's
        # value and the click one after the other.
        page.session.event(Event(node=box, name="change", payload="fast body"))
        page.session.event(Event(node=button, name="click"))
        await page.settle()
        assert page.state.posted == ["fast body"] and page.state.text == ""
        # The tab hears the typed value and then the cleared one. One drawing
        # for both would find the value as it was before the typing.
        assert told(page, box) == ["fast body", ""]
        # Enter in a field does the same from the field's own node.
        page.session.event(Event(node=line, name="change", payload="a line"))
        page.session.event(Event(node=line, name="submit", payload="a line"))
        await page.settle()
        assert page.state.posted == ["fast body", "a line"]
        assert told(page, line)[-2:] == ["a line", ""]
        # Many values of one field are still one drawing.
        drawn = len(page.patches)
        for text in ("a", "ab", "abc"):
            page.session.event(Event(node=box, name="change", payload=text))
        await page.settle()
        assert len(page.patches) == drawn + 1 and told(page, box)[-1] == "abc"

    async with TestApp(app, strict=False).open("/more") as page:
        button = page.find("post").id
        # A handler that waits for a task lets the click in before it is
        # done, and one that raises has still put the value in state.
        for key, text in (("waits", "while it waits"), ("raises", "though it raised")):
            field = page.find(key).id
            page.session.event(Event(node=field, name="change", payload=text))
            page.session.event(Event(node=button, name="click"))
            await page.settle()
            assert page.state.posted[-1] == text and page.state.text == ""
            assert told(page, field)[-2:] == [text, ""]
