"""``millwork run`` loads an app from a module path or a file path."""

import os
import sys
from pathlib import Path

import pytest

from millwork.cli import load_app


def test_a_file_path_loads_the_app_with_its_directory_importable(tmp_path: Path) -> None:
    (tmp_path / "helper.py").write_text("GREETING = 'hi'\n")
    (tmp_path / "demo.py").write_text(
        "import helper\nimport millwork as mw\n"
        "app = mw.App('demo')\napp.greeting = helper.GREETING\n"
    )
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path.parent)
        asgi = load_app(f"{tmp_path.name}/demo.py", debug=True)
        module = sys.modules["demo"]
    finally:
        os.chdir(cwd)
        sys.modules.pop("demo", None)
        sys.modules.pop("helper", None)
    assert asgi is module.app.asgi
    assert module.app.debug is True and module.app.greeting == "hi"


def test_a_missing_file_exits_with_a_message(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no such file"):
        load_app(str(tmp_path / "nope.py"))
