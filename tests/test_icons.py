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
