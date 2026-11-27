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
from millwork.shot import (
    SIGNED_IN,
    ShotError,
    _port,
    _why,
    find_browser,
    find_browsers,
    shoot,
)


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
    # Chrome goes before a Chromium, and one browser under two names is one.
    on_path = {
        "chromium": "/opt/chromium",
        "chromium-browser": "/opt/chromium",
        "google-chrome": "/opt/chrome",
        "brave": "/opt/brave",
    }
    monkeypatch.setattr(shutil, "which", lambda name: on_path.get(name))
    monkeypatch.setattr(os.path, "isfile", lambda path: False)
    assert find_browsers() == ["/opt/chrome", "/opt/chromium", "/opt/brave"]
    assert find_browser() == "/opt/chrome"
    assert find_browsers("brave") == ["/opt/brave"]
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ShotError, match="no browser found"):
        find_browser()


async def test_what_cannot_be_a_picture_is_said_before_a_browser_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def no_browser(named: str | None = None) -> list[str]:
        raise AssertionError("looked for a browser")

    monkeypatch.setattr("millwork.shot.find_browsers", no_browser)
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
    monkeypatch.setattr("millwork.shot.find_browsers", lambda named=None: ["no-browser-is-run"])
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


# What a browser that is kept from its sandbox writes as it ends: the line
# that says so, then a trace.
CRASH = """\
[1:1:1117/101010.1:ERROR:dbus/bus.cc:408] Failed to connect to the bus
[1:1:1117/101010.2:FATAL:content/browser/zygote_host/zygote_host_impl_linux.cc:128] \
No usable sandbox! If you are running on Ubuntu 23.10+, see the notes on AppArmor.
#0 0x5d6a base::debug::CollectStackTrace()
  r8: 0000000000000000  r9: 0000000000000000 r10: 0000000000000008
  ip: 0000769aa90ae14c efl: 0000000000000246 cgf: 002b000000000033
[end of stack trace]
"""


def crashing_browser(folder: Path) -> str:
    """A browser that ends at once as one without a sandbox does, having
    written down what it was started with."""
    fake = folder / "chromium"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"pathlib.Path({str(folder / 'args')!r}).write_text(' '.join(sys.argv[1:]))\n"
        f"sys.stderr.write({CRASH!r})\n"
        "sys.exit(133)\n"
    )
    fake.chmod(0o755)
    return str(fake)


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in browser is a script")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root runs a browser without its sandbox"
)
async def test_a_browser_that_will_not_start_says_why_in_its_own_words(tmp_path: Path) -> None:
    fake = crashing_browser(tmp_path)
    with pytest.raises(ShotError) as refused:
        await shoot(make_app(), "/", out=tmp_path / "a.png", browser=fake)
    said = str(refused.value)
    assert said.startswith(f"{fake} would not start: ") and "No usable sandbox!" in said
    assert "stack trace" not in said and "dbus" not in said
    assert "--no-sandbox runs it without one" in said
    assert "--no-sandbox" not in (tmp_path / "args").read_text()
    with pytest.raises(ShotError) as refused:
        await shoot(make_app(), "/", out=tmp_path / "a.png", browser=fake, sandbox=False)
    assert "--no-sandbox runs it without one" not in str(refused.value)
    assert "--no-sandbox" in (tmp_path / "args").read_text()


@needs_browser
@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in browser is a script")
async def test_a_browser_that_will_not_start_is_passed_over_for_the_next(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = find_browser()
    fake = crashing_browser(tmp_path)
    monkeypatch.setattr("millwork.shot.find_browsers", lambda named=None: [fake, real])
    shot = await shoot(make_app(), "/", out=tmp_path / "a.png")
    assert size(shot.out) == (1280, 800) and shot.status == 200
    monkeypatch.setattr("millwork.shot.find_browsers", lambda named=None: [fake, fake])
    with pytest.raises(ShotError) as refused:
        await shoot(make_app(), "/", out=tmp_path / "b.png")
    assert str(refused.value).count("would not start") == 2


def test_the_port_is_read_once_the_browser_has_written_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    file = tmp_path / "DevToolsActivePort"
    assert _port(file) is None
    file.write_text("41234\n")
    assert _port(file) is None
    file.write_text("41234\n/devtools/browser/abc\n")
    assert _port(file) == ("41234", "/devtools/browser/abc")

    # On Windows a file the browser is still writing cannot be opened.
    def held(self: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", held)
    assert _port(file) is None


def test_why_a_browser_ended_is_its_fatal_line_or_its_last_error() -> None:
    assert "No usable sandbox!" in _why(CRASH, 133) and "dbus" not in _why(CRASH, 133)
    noise = "[1:1:ERROR:dbus/bus.cc:408] no bus\n[1:1:ERROR:gpu.cc:9] no display\nReceived signal 5"
    assert _why(noise, 133) == "[1:1:ERROR:gpu.cc:9] no display"
    assert _why("one\n\ntwo\nthree\nfour", 1) == "one two three"
    assert _why("", 1) == "it ended with code 1"


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


async def test_a_browser_that_stops_answering_is_not_waited_for_without_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from millwork.shot import _Tab

    class Silent:
        """A line to a browser that takes what it is sent and says nothing."""

        async def send(self, message: str) -> None:
            pass

        async def recv(self) -> str:
            await asyncio.Event().wait()
            raise AssertionError("never said")

    monkeypatch.setattr("millwork.shot.ANSWER", 0.05)
    tab = _Tab(["a-browser"])
    tab._ws = Silent()  # type: ignore[assignment]
    with pytest.raises(ShotError, match=r"the browser did not answer Page.reload in 0.05 s"):
        await tab.call("Page.reload")
    # A script that waits is given its own time on top.
    with pytest.raises(ShotError, match=r"did not answer Runtime.evaluate in 0.15 s"):
        await tab.value("new Promise(() => {})", at_most=0.1)
