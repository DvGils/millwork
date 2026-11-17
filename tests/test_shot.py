"""``millwork shot``: a picture of a page from a browser on the machine."""

from __future__ import annotations

import asyncio
import glob
import os
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

import pytest

import millwork as mw
from millwork import auth, ui
from millwork.cli import main
from millwork.shot import SIGNED_IN, ShotError, find_browser, shoot


def _browser() -> str | None:
    try:
        return find_browser()
    except ShotError:
        return None


needs_browser = pytest.mark.skipif(
    _browser() is None, reason="no Chromium-family browser on this machine"
)


def size(png: Path) -> tuple[int, int]:
    data = png.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def make_app(seen: list[str] | None = None) -> mw.App:
    async def verify(name: str, password: str) -> None:
        return None

    app = mw.App("pictures", secret="s" * 40, auth=auth.Auth([auth.Password(verify)]))

    @app.page("/", public=True)
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Header("Home"), ui.Text("Anyone sees this."))

    @app.page("/long", public=True)
    def long(s: mw.Session) -> ui.Component:
        return ui.Page(*[ui.Card(ui.Text(f"Row {i}"), title=f"Card {i}") for i in range(30)])

    @app.page("/spin", public=True)
    def spin(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Spinner(label="Forever"))

    @app.page("/mine")
    def mine(s: mw.Session) -> ui.Component:
        if seen is not None:
            seen.append(f"{s.user.id} {s.user.claims}")
        return ui.Page(ui.Text(f"Hello, {s.user.name}."))

    return app


def test_the_browser_is_the_one_named_or_the_first_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MILLWORK_BROWSER", raising=False)
    assert find_browser(sys.executable) == shutil.which(sys.executable)
    with pytest.raises(ShotError, match="no browser at 'nosuchbrowser'"):
        find_browser("nosuchbrowser")
    monkeypatch.setenv("MILLWORK_BROWSER", sys.executable)
    assert find_browser() == shutil.which(sys.executable)
    monkeypatch.delenv("MILLWORK_BROWSER")
    on_path = {"google-chrome": "/opt/chrome", "brave": "/opt/brave"}
    monkeypatch.setattr(shutil, "which", lambda name: on_path.get(name))
    assert find_browser() == "/opt/chrome"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(os.path, "isfile", lambda path: False)
    with pytest.raises(ShotError, match="no browser found"):
        find_browser()


async def test_what_cannot_be_a_picture_is_said_before_a_browser_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def no_browser(named: str | None = None) -> str:
        raise AssertionError("looked for a browser")

    monkeypatch.setattr("millwork.shot.find_browser", no_browser)
    app = make_app()
    with pytest.raises(ShotError, match="starts with one slash"):
        await shoot(app, "long", out=tmp_path / "a.png")
    with pytest.raises(ShotError, match="starts with one slash"):
        await shoot(app, "//elsewhere.example", out=tmp_path / "a.png")
    with pytest.raises(ShotError, match="200 to 4000 wide"):
        await shoot(app, "/", out=tmp_path / "a.png", width=20)
    with pytest.raises(ShotError, match="millwork App"):
        await shoot(object(), "/", out=tmp_path / "a.png")
    open_app = mw.App("open", public=None)
    with pytest.raises(ShotError, match="no sign-in"):
        await shoot(open_app, "/", out=tmp_path / "a.png", user=mw.User(id="ada", name="Ada"))
    assert not (tmp_path / "a.png").exists()


def test_the_command_says_what_is_wrong_with_what_it_was_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "plain.py"
    target.write_text("import millwork as mw\napp = mw.App('plain', public=None)\n")
    out = str(tmp_path / "a.png")
    assert main(["shot", str(target), "/", "--out", out, "--claims", "{}"]) == 2
    assert "--claims goes with --user" in capsys.readouterr().err
    assert main(["shot", str(target), "/", "--out", out, "--user", "a", "--claims", "x"]) == 2
    assert "--claims is not JSON" in capsys.readouterr().err
    assert main(["shot", str(target), "/", "--out", out, "--user", "a", "--claims", "[]"]) == 2
    assert "--claims is a JSON object" in capsys.readouterr().err
    assert main(["shot", str(target), "/", "--out", out, "--user", "ada"]) == 2
    assert "no sign-in" in capsys.readouterr().err
    assert main(["shot", str(target), "/", "--out", out, "--browser", "nosuchbrowser"]) == 2
    assert "no browser at 'nosuchbrowser'" in capsys.readouterr().err
    assert not Path(out).exists()


async def test_an_app_that_does_not_start_is_said_and_no_browser_is_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("millwork.shot.find_browser", lambda named=None: "no-browser-is-run")
    broken = mw.App("broken", public=None)

    @broken.on_startup
    async def fail() -> None:
        raise RuntimeError("no database here")

    with pytest.raises(ShotError, match="the app did not start$"):
        await shoot(broken, "/", out=tmp_path / "a.png")
    slow = mw.App("slow", public=None)

    @slow.on_startup
    async def wait() -> None:
        await asyncio.sleep(1.0)

    monkeypatch.setattr("millwork.shot.START", 0.2)
    with pytest.raises(ShotError, match=r"the app did not start in 0.2 s"):
        await shoot(slow, "/", out=tmp_path / "a.png")
    assert not (tmp_path / "a.png").exists()


def test_a_user_signed_in_for_a_picture_is_so_for_minutes() -> None:
    app = make_app()
    ada = mw.User(id="ada", name="Ada")
    assert app.auth is not None
    usual = app.auth._read(app.auth.issue(ada))
    short = app.auth._read(app.auth.issue(ada, SIGNED_IN))
    assert usual is not None and short is not None and short[0] == ada
    assert 0 < short[2] - time.time() <= SIGNED_IN.total_seconds() < usual[2] - time.time()


@needs_browser
async def test_a_picture_is_the_window_or_the_whole_page_in_light_or_dark(tmp_path: Path) -> None:
    app = make_app()
    profiles = os.path.join(tempfile.gettempdir(), "millwork-shot-*")
    before = set(glob.glob(profiles))
    shot = await shoot(app, "/long", out=tmp_path / "new" / "window.png", width=900, height=600)
    assert size(shot.out) == (900, 600) == (shot.width, shot.height)
    assert (shot.path, shot.status, shot.still, shot.cut) == ("/long", 200, True, False)
    if sys.platform != "win32":
        # The browser's profile goes with it. On Windows a file of it can be
        # held a moment longer, and what is left is left to the system.
        assert set(glob.glob(profiles)) == before
    whole = await shoot(app, "/long", out=tmp_path / "whole.png", width=900, height=600, full=True)
    assert size(whole.out) == (900, whole.height) and whole.height > 1500
    dark = await shoot(app, "/long", out=tmp_path / "dark.png", width=900, height=600, dark=True)
    assert size(dark.out) == (900, 600)
    assert dark.out.read_bytes() != shot.out.read_bytes()


@needs_browser
async def test_a_page_behind_sign_in_is_seen_as_the_user_named(tmp_path: Path) -> None:
    seen: list[str] = []
    app = make_app(seen)
    nobody = await shoot(app, "/mine", out=tmp_path / "nobody.png")
    assert nobody.path.startswith("/_mw/login") and seen == []
    ada = mw.User(id="ada", name="Ada", claims={"role": "admin"})
    someone = await shoot(app, "/mine", out=tmp_path / "ada.png", user=ada)
    assert someone.path == "/mine" and seen == ["ada {'role': 'admin'}"]
    assert someone.out.read_bytes() != nobody.out.read_bytes()


@needs_browser
async def test_a_page_that_never_rests_is_taken_when_the_wait_runs_out(tmp_path: Path) -> None:
    shot = await shoot(make_app(), "/spin", out=tmp_path / "spin.png", timeout=0.8)
    assert shot.still is False and size(shot.out) == (1280, 800)


@needs_browser
def test_the_command_saves_the_picture_and_says_where(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "small.py"
    target.write_text(
        "import millwork as mw\n"
        "from millwork import ui\n"
        "app = mw.App('small', public=None)\n"
        "@app.page('/')\n"
        "def home(s):\n"
        "    return ui.Page(ui.Text('Hello.'))\n"
    )
    out = tmp_path / "small.png"
    assert main(["shot", str(target), "--out", str(out), "--width", "390", "--height", "700"]) == 0
    said = capsys.readouterr()
    assert said.out == f"{out}  390x700  /\n" and "the page" not in said.err
    assert size(out) == (390, 700)
    assert main(["shot", str(target), "/?q=a b#top", "--out", str(out)]) == 0
    said = capsys.readouterr()
    assert said.out == f"{out}  1280x800  /?q=a%20b\n" and "the page" not in said.err
    assert main(["shot", str(target), "/nowhere", "--out", str(out)]) == 0
    assert "the page answered 404" in capsys.readouterr().err
