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
    assert "- `on_feedback`: handler `(session, message, value, comment)`" in text
    assert "- `label: str` (required)" in text  # Stat
    assert "`ui.Button(label='', *children, **props)`" in text
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
