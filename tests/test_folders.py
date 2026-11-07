"""An app's folders are found next to its own file, wherever the server
is started from, and a folder the app names that is not there is said."""

import logging
import os
from pathlib import Path
from typing import Any

import pytest

import millwork as mw
from millwork.cli import load_object


def test_the_default_folders_are_next_to_the_apps_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "pond"
    (home / "public").mkdir(parents=True)
    (home / "components").mkdir()
    (home / "public" / "theme.json").write_text('{"mode": "dark"}')
    (home / "app.py").write_text(
        "import millwork as mw\napp = mw.App('pond', public=None if False else 'public')\n"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    app = load_object(os.fspath(home / "app.py"))
    assert app.public_dir == home / "public"
    assert app.components_dir == home / "components"
    assert app.theme.mode == "dark"


def test_a_folder_the_app_names_and_does_not_have_is_said(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="millwork.app"):
        app = mw.App("bare", public=tmp_path / "nowhere", components="missing")
    assert "public folder" in caplog.text and str(tmp_path / "nowhere") in caplog.text
    assert "components folder" in caplog.text
    assert app.components_dir == Path(__file__).parent / "missing"
    # The defaults being absent is nothing to say.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="millwork.app"):
        mw.App("plain")
    assert caplog.text == ""


def test_code_with_no_file_works_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "public").mkdir()
    monkeypatch.chdir(tmp_path)
    scope: dict[str, Any] = {}
    exec("import millwork as mw\napp = mw.App('cell')", scope)
    assert scope["app"].public_dir == tmp_path / "public"


def test_the_folders_are_next_to_whoever_calls_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A helper in another module makes the app: the folders are next to
    # the helper, which is why one passes absolute paths.
    helper = tmp_path / "helper"
    helper.mkdir()
    (helper / "public").mkdir()
    (helper / "make.py").write_text(
        "import millwork as mw\ndef make():\n    return mw.App('made')\n"
    )
    (tmp_path / "app.py").write_text("from make import make\napp = make()\n")
    monkeypatch.syspath_prepend(str(helper))
    app = load_object(os.fspath(tmp_path / "app.py"))
    assert app.public_dir == helper / "public"


def test_a_package_reached_through_a_symlink_is_still_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import millwork

    link = tmp_path / "link"
    link.mkdir()
    (link / "millwork").symlink_to(Path(millwork.__file__).parent)
    home = tmp_path / "pond"
    (home / "public").mkdir(parents=True)
    (home / "app.py").write_text("import millwork as mw\napp = mw.App('pond')\n")
    code = (
        "import sys, importlib\n"
        f"sys.path.insert(0, {os.fspath(link)!r})\n"
        "for name in [n for n in sys.modules if n == 'millwork' or n.startswith('millwork.')]:\n"
        "    del sys.modules[name]\n"
        "import millwork\n"
        f"assert millwork.__file__.startswith({os.fspath(link)!r}), millwork.__file__\n"
        "from millwork.cli import load_object\n"
        f"app = load_object({os.fspath(home / 'app.py')!r})\n"
        "from pathlib import Path\n"
        f"assert app.public_dir == Path({os.fspath(home / 'public')!r}), app.public_dir\n"
    )
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
