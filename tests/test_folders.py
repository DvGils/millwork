"""An app's folders are found next to its own file, wherever the server
is started from, and a folder the app names that is not there is said."""

import logging
import os
from pathlib import Path

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
