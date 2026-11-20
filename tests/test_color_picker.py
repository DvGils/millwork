"""The ColorPicker: what counts as a color, and what a pick comes to."""

from pathlib import Path

import pytest
from pydantic import BaseModel, Field

import millwork as mw
from millwork import ui
from millwork.forms import field_spec
from millwork.nodes import build
from millwork.testing import TestApp

PALETTE = ["#EF4444", "#0f0"]


class Paint(BaseModel):
    color: str | None = "#3b82f6"
    picked: list[str | None] = []


class Label(BaseModel):
    name: str = "Urgent"
    color: str = Field("#ef4444", json_schema_extra={"widget": "color", "swatches": PALETTE})
    edge: str | None = Field(None, json_schema_extra={"widget": "color"})


def make_app(tmp_path: Path) -> mw.App:
    app = mw.App("paint", state=Paint, public=None, bundle_dir=tmp_path)

    def pick(s: mw.Session[Paint], color: str | None) -> None:
        s.state.picked.append(color)
        s.state.color = color

    @app.page("/")
    def home(s: mw.Session[Paint]) -> ui.Component:
        return ui.Page(
            ui.ColorPicker(value=s.state.color, clearable=True, on_change=pick, key="main"),
            ui.ColorPicker(value=s.state.color, on_change=pick, key="kept"),
            ui.ColorPicker(value="#000000", disabled=True, on_change=pick, key="off"),
        )

    return app


def test_a_color_is_held_as_six_digits_in_lower_case() -> None:
    picker = ui.ColorPicker(value="#ABC", swatches=PALETTE)
    assert picker.value == "#aabbcc"
    assert picker.swatches == ["#ef4444", "#00ff00"]
    assert ui.ColorPicker(default=" #3B82F6 ").default == "#3b82f6"
    assert ui.ColorPicker(value=None).value is None
    props = (
        build(ui.ColorPicker(value="#F00", swatches=("#00f",), compact=True)).nodes["root"].props
    )
    assert props["value"] == "#ff0000" and props["swatches"] == ["#0000ff"]
    assert props["compact"] is True
    # Whatever holds the colors, each is checked and is there once.
    assert ui.ColorPicker(swatches=(c for c in ["#F00", "#ff0000", "#00f"])).swatches == [
        "#ff0000",
        "#0000ff",
    ]
    assert ui.ColorPicker(swatches={"#FFF"}).swatches == ["#ffffff"]


@pytest.mark.parametrize("bad", ["red", "#12", "#12345", "3b82f6", "#gggggg", "rgb(0, 0, 0)", ""])
def test_what_is_no_hex_code_is_no_color(bad: str) -> None:
    for how in ({"value": bad}, {"default": bad}, {"swatches": ["#000000", bad]}):
        with pytest.raises(ValueError, match="is not a color"):
            ui.ColorPicker(**how)
    with pytest.raises(ValueError, match="is not a color"):
        ui.ColorPicker(swatches={bad})
    with pytest.raises(ValueError):
        ui.ColorPicker(swatches="#000000")


def test_a_picker_has_the_pages_color_or_its_own() -> None:
    with pytest.raises(ValueError, match="not both"):
        ui.ColorPicker(value="#000000", default="#ffffff")


async def test_a_pick_reaches_the_handler_as_the_tab_sent_it(tmp_path: Path) -> None:
    async with TestApp(make_app(tmp_path)).open("/") as page:
        await page.change("main", "#22c55e")
        assert page.state.color == "#22c55e"
        assert page.find("kept").component.value == "#22c55e"
        await page.change("main", None)
        assert page.state.picked == ["#22c55e", None]


async def test_what_is_no_color_is_not_heard(tmp_path: Path) -> None:
    async with TestApp(make_app(tmp_path)).open("/") as page:
        for sent in ("red", "#22C55E", "#2c5", "#22c55e;", ["#22c55e"]):
            with pytest.raises(LookupError, match="not a color|not text"):
                await page.change("main", sent)
        # Only the one with a way back to no color takes none.
        with pytest.raises(LookupError, match="not one to clear"):
            await page.change("kept", None)
        with pytest.raises(LookupError):
            await page.change("off", "#22c55e")
        assert page.state.picked == [] and page.state.color == "#3b82f6"


def test_a_form_field_is_a_color_by_its_widget() -> None:
    spec = {f["name"]: f for f in field_spec(Label)["fields"]}
    assert spec["color"]["widget"] == "color"
    assert spec["color"]["swatches"] == ["#ef4444", "#00ff00"]
    assert spec["color"]["default"] == "#ef4444"
    # A field that may be empty has a way back to no color.
    assert spec["edge"]["widget"] == "color" and spec["edge"]["clearable"] is True
    assert "swatches" not in spec["edge"]
    over = build(ui.Form(Label, overrides={"/name": {"widget": "color", "swatches": ["#000"]}}))
    fields = over.nodes["root"].props["schema"]["fields"]
    name = next(f for f in fields if f["name"] == "name")
    assert name["widget"] == "color" and name["swatches"] == ["#000000"]


def test_the_swatches_of_a_form_field_are_colors() -> None:
    class Off(BaseModel):
        color: str = Field("#ef4444", json_schema_extra={"widget": "color", "swatches": ["red"]})

    with pytest.raises(ValueError, match="'red' is not a color"):
        field_spec(Off)
    with pytest.raises(ValueError, match="'blue' is not a color"):
        build(ui.Form(Label, overrides={"/color": {"swatches": ["blue"]}}))
