"""Small things an app ran into: a custom component's class, a plain meter,
the tone of a toast in a test."""

from pathlib import Path
from typing import Any

import pytest

import millwork as mw
from millwork import ui
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
