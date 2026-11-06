"""The reference lists what the catalogue has."""

from millwork import ui
from millwork.cli import main
from millwork.reference import reference


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
    assert "- `page.answer(payload=None)`" in text and "`{id:int}`" in text
    assert "also takes plain strings" in text
    assert "- `page.stream`: Every chunk the chats on the page streamed" in text
    assert "\n## Signing in\n" in text and "- `auth.Auth(providers, on_login=None" in text
    assert "### ui.SignIn" in text and "`ui.SignIn(provider, *children, **props)`" in text
    assert "``(row, value) -> tone`` for a cell's" in text
    assert "- `cols: int | dict['sm' | 'md' | 'lg' | 'xl', int]` = `2`" in text
    assert "- `label: str` (required)" in text  # Stat
    assert "`ui.Button(label='', *children, **props)`" in text
    assert "### ui.Header\n" in text
    assert "`ui.AreaChart(rows=(), *children, **props)`" in text
    assert "- `rows: Sequence[Any]` = `()`" in text
    assert "one owner" not in text  # an inherited docstring is not the component's
    assert "`s.task(" in text and "`mw.App(name, state=None" in text
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
