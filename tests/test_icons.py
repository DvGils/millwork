"""The icon names the bundle draws are the ones Python accepts."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

import millwork as mw
from millwork import ui
from millwork._icons import PASCAL
from millwork.icons import ICONS, check_icon

ICONS_TS = Path(__file__).resolve().parents[1] / "bundle" / "src" / "icons.ts"


def test_the_python_table_is_the_bundles() -> None:
    source = ICONS_TS.read_text()
    table = re.search(r"const byPascal[^{]*\{([^}]*)\}", source)
    assert table is not None
    names = [n.strip() for n in table.group(1).split(",") if n.strip()]
    assert list(PASCAL) == names, "run the bundle build; it regenerates src/millwork/_icons.py"


def test_names_resolve_the_way_the_tab_resolves_them() -> None:
    assert "file-text" in ICONS and "trash-2" in ICONS and "bar-chart-3" in ICONS
    for name in ("file-text", "trash-2", "trash2", "Trash2", "BarChart3", None):
        assert check_icon(name) == name
    with pytest.raises(ValueError, match="no icon named 'wallet'.*millwork.ICONS"):
        check_icon("wallet")
    with pytest.raises(ValueError, match="closest are .*file-text"):
        check_icon("file_text")


def test_a_component_refuses_an_unknown_icon() -> None:
    assert ui.Button("Save", icon="save").icon == "save"
    with pytest.raises(ValidationError, match="no icon named 'house'"):
        ui.Button("Home", icon="house")
    with pytest.raises(ValidationError, match="no icon named"):
        ui.MenuItem(id="x", label="X", icon="banknote")
    with pytest.raises(ValidationError, match="no icon named"):
        ui.Input(prefix_icon="magnifier")
    assert mw.ICONS is ICONS


def test_an_apps_own_component_keeps_its_icon_meaning() -> None:
    from typing import ClassVar

    from millwork.nodes import Component

    class Avatar(Component):
        type: ClassVar[str] = "x-avatar"
        icon: str | None = None

    assert Avatar(icon="https://example.com/a.png").icon == "https://example.com/a.png"
    assert ui.Button("x", icon="").icon == ""


def test_an_icon_is_a_name_or_a_file_under_public() -> None:
    for path in (
        "/public/rocket.svg",
        "/public/icons/rocket.svg",
        "/public/icons/brand/Logo-2_x.1.PNG",
        "/public/a.webp",
        "/public/a.jpg",
        "/public/a.jpeg",
    ):
        assert check_icon(path) == path
    assert ui.Button("Launch", icon="/public/icons/rocket.svg").icon == "/public/icons/rocket.svg"
    assert ui.Input(prefix_icon="/public/icons/rocket.svg").prefix_icon
    assert ui.MenuItem(id="x", label="X", icon="/public/icons/rocket.svg").icon


@pytest.mark.parametrize(
    "path",
    [
        "/public/../secret.svg",
        "/public/a/../b.svg",
        "/public/./a.svg",
        "/public/.hidden.svg",
        "/public/a/.b/c.svg",
        "/elsewhere/x.svg",
        "/x.svg",
        "/public",
        "/public/",
        "/public/.svg",
        "//evil.example/x.svg",
        "/public//x.svg",
        "/public/x.svg?v=1",
        "/public/x.svg#a",
        "/public/x%2e%2e/y.svg",
        "/public\\x.svg",
        "/public/x .svg",
        '/public/x").svg',
        "/public/x.svg\n",
        "/public/x\x00.svg",
        "/public/notes.txt",
        "/public/x.svg.html",
        "/public/x",
        "/public/" + "a" * 200 + ".svg",
    ],
)
def test_a_path_that_could_lead_anywhere_else_is_no_icon(path: str) -> None:
    with pytest.raises(ValueError, match="an icon file is a path under /public/"):
        check_icon(path)
    with pytest.raises(ValidationError, match="an icon file is a path under /public/"):
        ui.Button("x", icon=path)
    with pytest.raises(ValidationError, match="an icon file is a path under /public/"):
        ui.Icon(path)


@pytest.mark.parametrize(
    "path",
    [
        "/PUBLIC/x.svg",
        "/Public/icons/x.svg",
        "/publ\u0131c/x.svg",
        "/public/x.\u017fvg",
        "/public/\u212a.svg",
        "/public/x.gif",
        "/public/x.ico",
        "/public/" + "a" * 189 + ".svg",
    ],
)
def test_the_folder_is_spelled_one_way_and_the_name_is_plain(path: str) -> None:
    with pytest.raises(ValueError, match="an icon file is a path under /public/"):
        check_icon(path)


def test_a_path_is_as_long_as_two_hundred_characters_and_no_longer() -> None:
    longest = "/public/" + "a" * 188 + ".svg"
    assert len(longest) == 200 and check_icon(longest) == longest
    assert check_icon("/public/x.SVG") == "/public/x.SVG"


def test_every_place_that_takes_an_icon_checks_it() -> None:
    bad = "//evil.example/x.svg"
    makers = [
        lambda: ui.Option(value="a", icon=bad),
        lambda: ui.MenuItem(id="a", label="A", icon=bad),
        lambda: ui.Tab(id="a", label="A", icon=bad),
        lambda: ui.Alert("a", icon=bad),
        lambda: ui.Badge("a", icon=bad),
        lambda: ui.Stat(label="a", value="1", icon=bad),
        lambda: ui.Link(label="a", href="/", icon=bad),
        lambda: ui.Empty(title="a", icon=bad),
        lambda: ui.Select(options=[{"value": "a", "icon": bad}]),
        lambda: ui.Command(id="a", label="A", icon=bad),
    ]
    for make in makers:
        with pytest.raises(ValidationError):
            make()


def test_a_catalogue_component_under_another_name_still_checks_its_icon() -> None:
    class Launch(ui.Button):
        pass

    assert Launch("Go", icon="/public/icons/rocket.svg").icon
    with pytest.raises(ValidationError, match="an icon file is a path under /public/"):
        Launch("Go", icon="//evil.example/x.svg")
    with pytest.raises(ValidationError, match="no icon named"):
        Launch("Go", icon="constructor")


def test_a_very_long_name_is_refused_without_being_weighed_or_repeated() -> None:
    import time

    started = time.perf_counter()
    with pytest.raises(ValueError) as refused:
        check_icon("x" * 2_000_000)
    assert time.perf_counter() - started < 0.2
    assert len(str(refused.value)) < 300


def test_an_address_elsewhere_is_no_icon() -> None:
    for address in ("https://example.com/x.svg", "javascript:alert(1)", "data:image/svg+xml,x"):
        with pytest.raises(ValueError, match="no icon named"):
            check_icon(address)


def test_an_icon_stands_on_its_own() -> None:
    from millwork.nodes import build

    icon = ui.Icon("check", size="lg", tone="success", label="Done", key="done")
    props = build(ui.Page(icon), "root").nodes["root/done"].props
    assert props == {"name": "check", "size": "lg", "tone": "success", "label": "Done"}
    assert ui.Icon("/public/icons/rocket.svg").name == "/public/icons/rocket.svg"
    with pytest.raises(ValidationError, match="no icon named 'rocket-ship'"):
        ui.Icon("rocket-ship")
    with pytest.raises(ValidationError, match="an icon needs a name"):
        ui.Icon("")
    with pytest.raises(TypeError):
        ui.Icon()  # type: ignore[call-arg]
