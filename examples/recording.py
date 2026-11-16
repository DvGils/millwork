"""What the examples' pictures are made with: an example served on a port,
a headless Chromium-family browser driven over the DevTools protocol, one
window per person, and ffmpeg to put the frames together.

Each example has a ``record.py`` that says what happens in its picture, so
what its README shows is what its app does. The browser is ``MW_BROWSER``
or the first of brave, chromium and google-chrome on the path.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import websockets

CDP = 9344
FPS = 10
# How wide the still picture of an example is, in pixels.
STILL = 900
# A picture plays half again as fast as the app was used, so what is typed
# and pressed goes by briskly, and it rests between one thing and the next
# for the reader to look around.
SPEED = 1.5

# A pointer drawn on the page, since a screenshot has none: an arrow that
# glides to where it presses, and a ring at the press.
POINTER = """
(() => {
  const p = document.createElement('div');
  p.id = 'pointer';
  p.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;'
    + 'transition:transform .32s cubic-bezier(.2,.7,.2,1);transform:translate(640px,430px)';
  p.innerHTML = '<span style="position:absolute;left:-12px;top:-12px;width:30px;height:30px;'
    + 'border-radius:50%;background:rgba(67,71,198,.35);transform:scale(0)"></span>'
    + '<svg width="20" height="24" viewBox="0 0 20 24" style="position:absolute;left:0;top:0">'
    + '<path d="M2 2v17l4.6-4.3 3 6.9 2.9-1.3-3-6.8H16z" fill="#111" stroke="#fff"'
    + ' stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.body.appendChild(p);
})()
"""


class Window:
    """One person's browser: a context of its own, so a visitor of its own,
    with one tab in it."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        scheme: str = "light",
        zone: str | None = None,
        phone: bool = False,
    ) -> None:
        self.width, self.height = width, height
        self.scheme, self.zone, self.phone = scheme, zone, phone
        self.frames: list[bytes] = []
        # What it showed at the moment that was kept as the still picture.
        self.still: bytes | None = None
        self._n = 0

    async def open(self) -> None:
        self._browser = await websockets.connect(_browser_socket(), max_size=2**26)
        made = await self._ask(self._browser, "Target.createBrowserContext")
        self._context = made["browserContextId"]
        target = await self._ask(
            self._browser, "Target.createTarget", url="about:blank", browserContextId=self._context
        )
        page = f"ws://127.0.0.1:{CDP}/devtools/page/{target['targetId']}"
        self._tab = await websockets.connect(page, max_size=2**26)
        await self.call("Page.enable")
        await self.call("Runtime.enable")
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            width=self.width,
            height=self.height,
            deviceScaleFactor=2 if self.phone else 1,
            mobile=self.phone,
        )
        await self.call(
            "Emulation.setEmulatedMedia",
            features=[{"name": "prefers-color-scheme", "value": self.scheme}],
        )
        if self.zone:
            await self.call("Emulation.setTimezoneOverride", timezoneId=self.zone)

    async def close(self) -> None:
        await self._tab.close()
        await self._ask(
            self._browser, "Target.disposeBrowserContext", browserContextId=self._context
        )
        await self._browser.close()

    async def _ask(self, socket: Any, method: str, **params: object) -> dict[str, Any]:
        self._n += 1
        await socket.send(json.dumps({"id": self._n, "method": method, "params": params}))
        while True:
            msg = json.loads(await socket.recv())
            if msg.get("id") == self._n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                result: dict[str, Any] = msg.get("result", {})
                return result

    async def call(self, method: str, **params: object) -> dict[str, Any]:
        return await self._ask(self._tab, method, **params)

    async def go(self, url: str, settle: float = 2.0) -> None:
        await self.call("Page.navigate", url=url)
        await asyncio.sleep(settle)
        if not self.phone:
            await self.eval(POINTER)

    async def eval(self, js: str) -> Any:
        r = await self.call(
            "Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True
        )
        return r.get("result", {}).get("value")

    async def attach(self, field: str, file: Path) -> None:
        """Choose a file in the file field the JavaScript expression finds,
        as someone picks one from their device."""
        found = await self.call("Runtime.evaluate", expression=field)
        await self.call(
            "DOM.setFileInputFiles", files=[str(file)], objectId=found["result"]["objectId"]
        )

    async def shot(self) -> bytes:
        r = await self.call("Page.captureScreenshot", format="png")
        return base64.b64decode(r["data"])


class Recording:
    """What a few windows show while an example is used, frame by frame.
    Every frame is one screenshot of each window, so they stay in step."""

    def __init__(self, *windows: Window) -> None:
        self.windows = windows

    async def capture(self, seconds: float) -> None:
        """Frames for this long of the app's own time, the app running
        meanwhile. They are taken at an even pace, each when it falls due."""
        start = time.monotonic()
        made, total = 0, max(1, round(seconds * FPS / SPEED))
        while made < total:
            for w in self.windows:
                w.frames.append(await w.shot())
            made += 1
            await asyncio.sleep(max(0.0, start + made * SPEED / FPS - time.monotonic()))

    async def still(self) -> None:
        """Keep what the windows show now, without the pointer, as the one
        picture of the example that does not move."""
        seen = "(p => p && (p.style.visibility = '{}'))(document.getElementById('pointer'))"
        for w in self.windows:
            await w.eval(seen.format("hidden"))
            w.still = await w.shot()
            await w.eval(seen.format(""))

    async def rest(self, seconds: float) -> None:
        """A moment of the picture's own time in which nothing is pressed."""
        await self.capture(seconds * SPEED)

    async def click(self, window: Window, element: str) -> None:
        """Press what the JavaScript expression ``element`` finds. The
        pointer goes there first, in view, and the press shows as a ring."""
        box = await window.eval(
            f"(() => {{ const e = {element}; if (!e) return null;"
            " const r = e.getBoundingClientRect();"
            " return {x: r.x + r.width * 0.5, y: r.y + r.height * 0.55}; })()"
        )
        if box is None:
            raise RuntimeError(f"no element for {element}")
        x, y = box["x"], box["y"]
        if not window.phone:
            # A page that was loaded since has no pointer yet.
            await window.eval(f"document.getElementById('pointer') || {POINTER.strip()}")
            await window.eval(
                "document.getElementById('pointer').style.transform ="
                f" 'translate({x - 2}px, {y - 2}px)'"
            )
            await self.capture(0.4)
            # The page's own pointer arrives, and what shows under it does.
            await window.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
            await self.capture(0.2)
            await window.eval(
                "document.querySelector('#pointer span').animate([{transform: 'scale(.2)',"
                " opacity: 1}, {transform: 'scale(1.2)', opacity: 0}], {duration: 380})"
            )
        for kind in ("mousePressed", "mouseReleased"):
            await window.call(
                "Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1
            )

    async def type(self, window: Window, text: str, per_char: float = 0.045) -> None:
        for ch in text:
            await window.call("Input.insertText", text=ch)
            await self.capture(per_char)

    async def enter(self, window: Window) -> None:
        for kind in ("keyDown", "keyUp"):
            await window.call(
                "Input.dispatchKeyEvent", type=kind, key="Enter", windowsVirtualKeyCode=13
            )


def _browser_socket() -> str:
    version = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json/version"))
    return str(version["webSocketDebuggerUrl"])


def _up(port: int) -> bool:
    """Whether the example and the browser both answer."""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/_mw/health").read()
        urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json/version").read()
    except Exception:
        return False
    return True


def _start(app: Path, port: int, profile: str) -> tuple[subprocess.Popen[bytes], ...]:
    millwork = str(Path(sys.executable).parent / "millwork")
    chromium = [
        browser(),
        "--headless",
        f"--remote-debugging-port={CDP}",
        f"--user-data-dir={profile}",
        "--hide-scrollbars",
        # A browser with a mouse, so that what shows at the pointer does.
        "--blink-settings=primaryHoverType=2,availableHoverTypes=2,"
        "primaryPointerType=4,availablePointerTypes=4",
        "about:blank",
    ]
    return tuple(
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for command in ([millwork, "run", str(app), "--port", str(port)], chromium)
    )


def browser() -> str:
    for name in (
        os.environ.get("MW_BROWSER"),
        "brave",
        "chromium",
        "chromium-browser",
        "google-chrome",
    ):
        if name and shutil.which(name):
            return name
    raise SystemExit("no browser found; set MW_BROWSER to a Chromium-family binary")


@contextlib.asynccontextmanager
async def served(app: Path, port: int) -> AsyncIterator[str]:
    """The example at ``app`` on a port and a browser to look at it with.
    Gives the address the example is served at."""
    profile = tempfile.mkdtemp(prefix="mw-record-")
    server, chrome = _start(app, port, profile)
    try:
        for _ in range(60):
            if _up(port):
                break
            await asyncio.sleep(0.25)
        else:
            raise SystemExit(f"{app} on port {port} or the browser did not come up")
        yield f"http://127.0.0.1:{port}"
    finally:
        chrome.terminate()
        server.terminate()
        shutil.rmtree(profile, ignore_errors=True)


def picture(
    out: Path,
    placed: list[tuple[Window, int, int, int]],
    size: tuple[int, int] = (1200, 800),
    backdrop: str = "0xe9e4da",
) -> None:
    """Write a GIF of a few windows side by side on a backdrop. Each is
    given with where its corner goes and how wide it is drawn, and gets a
    thin frame around it: ``(window, x, y, width)``.

    When ``Recording.still`` kept a moment, that moment is written beside
    it as a PNG of the same name, for a page that shows the example small.

    A name that ends in ``.webp`` gets an animated WebP. A picture of soft
    light and blur needs more than the 256 colors a GIF has, and is a
    third of the size this way."""
    with tempfile.TemporaryDirectory() as tmp:
        inputs: list[str] = []
        stills: list[str] = []
        parts = [f"color=c={backdrop}:s={size[0]}x{size[1]}:r={FPS}[p0]"]
        for n, (window, x, y, width) in enumerate(placed):
            for i, png in enumerate(window.frames):
                (Path(tmp) / f"w{n}-{i:05d}.png").write_bytes(png)
            inputs += ["-framerate", str(FPS), "-i", str(Path(tmp) / f"w{n}-%05d.png")]
            if window.still is not None:
                (Path(tmp) / f"w{n}-still.png").write_bytes(window.still)
                stills += ["-i", str(Path(tmp) / f"w{n}-still.png")]
            # A phone gets the dark frame of a phone, a screen a hairline that
            # shows against its own scheme.
            if window.phone:
                frame = "pad=iw+12:ih+12:6:6:color=0x0e0d12"
            else:
                line = "0x2a3140" if window.scheme == "dark" else "0xd5cec1"
                frame = f"pad=iw+2:ih+2:1:1:color={line}"
            parts.append(f"[{n}:v]scale={width}:-1:flags=lanczos,{frame}[w{n}]")
            parts.append(f"[p{n}][w{n}]overlay={x}:{y}:shortest=1[p{n + 1}]")
        picture = ";".join(parts)
        last = f"[p{len(placed)}]"
        palette = str(Path(tmp) / "palette.png")
        quiet = ["ffmpeg", "-y", "-loglevel", "error"]
        if len(stills) == 2 * len(placed):
            # The still picture, laid out as the moving one and beside it.
            small = f"{picture};{last}scale={STILL}:-1:flags=lanczos[still]"
            one = ["-map", "[still]", "-frames:v", "1", str(out.with_suffix(".png"))]
            subprocess.run([*quiet, *stills, "-filter_complex", small, *one], check=True)
        if out.suffix == ".webp":
            how = ["-c:v", "libwebp_anim", "-quality", "60", "-loop", "0", "-an"]
            subprocess.run(
                [*quiet, *inputs, "-filter_complex", picture, "-map", last, *how, str(out)],
                check=True,
            )
            return
        subprocess.run(
            [
                *quiet,
                *inputs,
                "-filter_complex",
                f"{picture};{last}palettegen=max_colors=192:stats_mode=diff",
                palette,
            ],
            check=True,
        )
        subprocess.run(
            [
                *quiet,
                *inputs,
                "-i",
                palette,
                "-filter_complex",
                f"{picture};{last}[{len(placed)}:v]paletteuse=dither=none",
                str(out),
            ],
            check=True,
        )
