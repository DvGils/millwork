"""Record the README's GIF from ``demo.py``: ten seconds of the app being
used. Run from the repository root:

    uv run python .github/readme/record.py

It starts the demo on a port, drives a headless Chromium-family browser over
the DevTools protocol, and assembles the GIF with ffmpeg. The browser is
``MW_BROWSER`` or the first of brave, chromium and google-chrome on the path.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent
PORT = 8031
CDP = 9344
WIDTH, HEIGHT = 1200, 880
FPS = 10


class Tab:
    """One browser tab over the DevTools protocol."""

    def __init__(self) -> None:
        self.n = 0
        self.frames: list[bytes] = []

    async def __aenter__(self) -> Tab:
        req = urllib.request.Request(f"http://127.0.0.1:{CDP}/json/new?about:blank", method="PUT")
        info = json.load(urllib.request.urlopen(req))
        self.id = info["id"]
        self.ws = await websockets.connect(info["webSocketDebuggerUrl"], max_size=50_000_000)
        await self.call("Page.enable")
        await self.call("Runtime.enable")
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            width=WIDTH,
            height=HEIGHT,
            deviceScaleFactor=1,
            mobile=False,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.ws.close()
        urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json/close/{self.id}")

    async def call(self, method: str, **params: object) -> dict:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def nav(self, url: str, settle: float = 2.0) -> None:
        await self.call("Page.navigate", url=url)
        await asyncio.sleep(settle)

    async def eval(self, js: str) -> object:
        r = await self.call(
            "Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True
        )
        return r.get("result", {}).get("value")

    # ---- the pointer and the keyboard, with frames captured as they act

    async def click(self, js_element: str) -> None:
        box = await self.eval(
            f"(() => {{ const e = {js_element}; if (!e) return null;"
            " const r = e.getBoundingClientRect();"
            " return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()"
        )
        if box is None:
            raise RuntimeError(f"no element for {js_element}")
        x, y = box["x"], box["y"]  # type: ignore[index]
        await self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await self.call(
            "Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1
        )
        await self.call(
            "Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1
        )

    async def type(self, text: str, per_char: float = 0.04) -> None:
        for ch in text:
            await self.call("Input.insertText", text=ch)
            await self.capture(per_char)

    async def key(self, key: str) -> None:
        codes = {"Enter": 13, "Tab": 9, "Backspace": 8}
        code = codes[key]
        await self.call(
            "Input.dispatchKeyEvent", type="keyDown", key=key, windowsVirtualKeyCode=code
        )
        await self.call("Input.dispatchKeyEvent", type="keyUp", key=key, windowsVirtualKeyCode=code)

    async def select_all(self, js_element: str) -> None:
        await self.eval(f"(() => {{ const e = {js_element}; e.focus(); e.select(); }})()")

    async def capture(self, seconds: float) -> None:
        """Frames at FPS for this long, the app running meanwhile."""
        end = time.monotonic() + seconds
        while True:
            r = await self.call("Page.captureScreenshot", format="png")
            self.frames.append(base64.b64decode(r["data"]))
            left = end - time.monotonic()
            if left <= 0:
                break
            await asyncio.sleep(min(1 / FPS, left))


def browser() -> str:
    for name in (os.environ.get("MW_BROWSER"), "brave", "chromium", "google-chrome", "chrome"):
        if name and shutil.which(name):
            return name
    raise SystemExit("no browser found; set MW_BROWSER to a Chromium-family binary")


async def record(tab: Tab) -> None:
    url = f"http://127.0.0.1:{PORT}/"
    await tab.nav(url, settle=2.5)

    # 1. A new order: refused once, then saved.
    await tab.capture(0.8)
    customer = "document.getElementById('f_customer')"
    amount = "document.getElementById('f_amount')"
    await tab.click(customer)
    await tab.type("Kestrel Books")
    await tab.click(amount)
    await tab.type("-20")
    await tab.capture(0.3)
    await tab.click(
        "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Add')"
    )
    await tab.capture(1.4)
    await tab.select_all(amount)
    await tab.type("980")
    await tab.capture(0.3)
    await tab.click(
        "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Add')"
    )
    await tab.capture(1.6)

    # 2. An import with progress, the table filling as it runs.
    await tab.click(
        "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Import')"
    )
    await tab.capture(4.2)

    # 3. A question, answered by a reply that streams.
    await tab.click("document.querySelector('textarea')")
    await tab.type("Which customer spent most?")
    await tab.key("Enter")
    await tab.capture(3.8)


def gif(frames: list[bytes], out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for i, png in enumerate(frames):
            (Path(tmp) / f"f{i:05d}.png").write_bytes(png)
        pattern = str(Path(tmp) / "f%05d.png")
        palette = str(Path(tmp) / "palette.png")
        filters = f"fps={FPS},scale={WIDTH}:-1:flags=lanczos"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-framerate",
                str(FPS),
                "-i",
                pattern,
                "-vf",
                f"{filters},palettegen=max_colors=192:stats_mode=diff",
                palette,
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-framerate",
                str(FPS),
                "-i",
                pattern,
                "-i",
                palette,
                "-lavfi",
                f"{filters}[x];[x][1:v]paletteuse=dither=none",
                str(out),
            ],
            check=True,
        )


async def main() -> None:
    app = subprocess.Popen(
        [str(Path(sys.executable).parent / "millwork"), "run", "demo.py", "--port", str(PORT)],
        cwd=HERE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    profile = tempfile.mkdtemp(prefix="mw-record-")
    chrome = subprocess.Popen(
        [
            browser(),
            "--headless",
            f"--remote-debugging-port={CDP}",
            f"--user-data-dir={profile}",
            f"--window-size={WIDTH},{HEIGHT}",
            "--hide-scrollbars",
            "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_mw/health").read()
                urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json/version").read()
                break
            except Exception:
                await asyncio.sleep(0.2)
        async with Tab() as tab:
            await record(tab)
            frames = tab.frames
        gif(frames, HERE / "demo.gif")
        size = (HERE / "demo.gif").stat().st_size
        print(f"{len(frames)} frames, {len(frames) / FPS:.1f} s, demo.gif {size / 1e6:.2f} MB")
    finally:
        chrome.terminate()
        app.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
