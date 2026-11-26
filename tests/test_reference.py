"""The reference lists what the catalogue has."""

from millwork import ui
from millwork.cli import main
from millwork.reference import reference


def test_every_component_of_the_catalogue_is_exported() -> None:
    # Lazy is what a call of a ``ui.lazy`` function gives, and no component to write.
    made = {
        name
        for name, obj in vars(ui).items()
        if isinstance(obj, type) and issubclass(obj, ui.Component) and not name.startswith("_")
    }
    assert made - set(ui.__all__) == {"Lazy"}
    assert "### ui.Combobox\n" in reference()


# What the session, the app and a test's page can be asked that the
# reference leaves out: what the framework calls on itself. A new method is
# listed in the reference or here, so that one an app is meant to call is
# not left out of what an agent reads by being forgotten.
INSIDE_THE_SESSION = {
    *("aim", "answer", "attached", "bring_up", "cancel", "close_ask", "closed", "command"),
    *("detached", "dismiss", "enter", "event", "fall_back", "flush", "has_tab", "hello"),
    "in_zone",
    *("idle", "inflight", "kept_part", "leave", "leaving_for", "marked", "mounted"),
    *("open_ask", "owns_resume", "place", "post", "ready", "render", "request"),
    *("settle_page", "shown", "sort", "stay_current", "stream", "take_owed", "take_wanted"),
    *("upload_spec", "visitor", "wait_for_task", "want", "warn", "watch_sign_in", "watch_user"),
}
INSIDE_THE_APP = {
    *("access", "admit", "asgi", "check_components", "end_sign_in", "fallback"),
    *("file_response", "locate", "make_state", "may", "resolve", "serves", "user_for"),
}
# Named in the words above the list of what a page does.
SAID_OF_THE_PAGE = {
    *("commands", "errors", "last_patch", "notices", "patches", "state", "toasts", "tree"),
}


def test_every_public_method_is_in_the_reference_or_left_out_on_purpose() -> None:
    from millwork import reference as listed
    from millwork.app import App
    from millwork.session import Session
    from millwork.testing import Page

    def public(cls: type) -> set[str]:
        return {
            name
            for name, value in vars(cls).items()
            if not name.startswith("_") and (callable(value) or isinstance(value, property))
        }

    for cls, api, inside in (
        (Session, listed.SESSION_API, INSIDE_THE_SESSION),
        (App, listed.APP_API, INSIDE_THE_APP),
        (Page, listed.PAGE_API, SAID_OF_THE_PAGE),
    ):
        assert not set(api) & inside, cls.__name__
        assert public(cls) == set(api) | inside, cls.__name__
    text = reference()
    for call in (
        # What is given by name only says so.
        "`s.highlight(name, color='blue', *, style='solid',",
        "`s.outline(*, within=None, as_text=False, rows=5, chars=200)`",
        "`s.focus(name)`",
        "`s.follow(signal)`",
        "`s.named(name)`",
        "`mw.Signal()`",
        "`signal.fire()`",
        "`app.spawn(coro",
        "`page.touch(name)`",
        "`page.marks`",
        # A method that is a function of another module is said without
        # the session it is handed.
        "`s.ask(component, timeout=None)`",
        "`s.confirm(title,",
    ):
        assert call in text, call
    assert "(s, " not in text


def test_the_reference_covers_every_component_and_the_tables(capsys) -> None:
    text = reference()
    for name in ui.__all__:
        obj = getattr(ui, name)
        if isinstance(obj, type) and issubclass(obj, ui.Component) and obj is not ui.Component:
            assert f"### ui.{name}\n" in text, name
    variants = "'primary' | 'secondary' | 'outline' | 'ghost' | 'link' | 'destructive'"
    assert f"- `variant: {variants}` = `'primary'`" in text
    assert (
        "- `on_feedback`: handler `(session, message, value, comment)`, arguments the message,"
        " 'up', 'down' or None when withdrawn, and the comment" in text
    )
    assert "- `on_action`: handler `(session, payload)`, payload [action_id, row_key]" in text
    assert "`ui.Form(model=None, *children, **props)`" in text
    assert "`ui.BarChart(rows=(), *children, **props)`" in text
    for section in ("## Tasks", "## Forms", "## Testing"):
        assert f"\n{section}\n" in text
    assert "- `p.step(label)`: ``with p.step(" in text and "- `task.ok`: Finished" in text
    assert "- `p.log(line)`: A line of output." in text
    assert "`ui.Tone` is the type of every `tone`: `default`, `muted`" in text
    assert "- `page.answer(payload=None)`" in text and "`{id:int}`" in text
    assert "also takes plain strings" in text
    assert "- `page.stream`: Every chunk the chats on the page streamed" in text
    assert "\n## Signing in\n" in text and "- `auth.Auth(providers, *, on_login=None" in text
    assert "### ui.SignIn" in text and "`ui.SignIn(provider, *children, **props)`" in text
    assert "``(row, value) -> tone`` for a cell's" in text
    assert "- `cols: int | dict['sm' | 'md' | 'lg' | 'xl', int]` = `2`" in text
    assert "- `label: str` (required)" in text  # Stat
    assert "`ui.Button(label='', *children, **props)`" in text
    assert "### ui.Header\n" in text
    assert "`ui.AreaChart(rows=(), *children, **props)`" in text
    assert "- `rows: Sequence[Any]` = `()`" in text
    assert "one owner" not in text  # an inherited docstring is not the component's
    assert "`s.task(" in text and "`mw.App(name, *, state=None" in text
    assert "`multiselect`" in text and "`currency`" in text and "file-text" in text
    assert main(["reference"]) == 0
    assert capsys.readouterr().out.startswith("# millwork ")


async def test_the_manual_serves_the_reference(tmp_path) -> None:
    from starlette.testclient import TestClient

    from millwork.manual import make_app

    app = make_app()
    app.bundle_dir = tmp_path
    with TestClient(app.asgi) as client:
        r = client.get("/llms.txt")
        assert r.status_code == 200 and r.text.startswith("# millwork ")
