"""Record the README's GIFs from ``demo.py``: twenty seconds of the app being
used, at the pace it was used at, once in the light and once in the dark, for a reader in either. Run
from the repository root:

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
WIDTH, HEIGHT = 1200, 836
FPS = 10

# A pointer drawn on the page, since a screenshot has none: an arrow that
# glides to what is pressed next and a ring where it presses. It is no part
# of the app, and nothing on the page can be reached through it.
POINTER = """
(() => {
  const p = document.createElement('div');
  p.id = 'pointer';
  p.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;'
    + 'transition:transform .32s cubic-bezier(.2,.7,.2,1);transform:translate(640px,430px)';
  p.innerHTML = '<span style="position:absolute;left:-12px;top:-12px;width:30px;height:30px;'
    + 'border-radius:50%;background:rgba(37,99,235,.4);transform:scale(0)"></span>'
    + '<svg width="20" height="24" viewBox="0 0 20 24" style="position:absolute;left:0;top:0">'
    + '<path d="M2 2v17l4.6-4.3 3 6.9 2.9-1.3-3-6.8H16z" fill="#111" stroke="#fff"'
    + ' stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.body.appendChild(p);
})()
"""

# The assistant's window at a size a reader gave it, as the browser keeps it:
# small enough to leave the chart in view.
WINDOW = {"x": WIDTH - 24 - 500, "y": HEIGHT - 24 - 376, "width": 500, "height": 376}


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
            " return {x: r.x + r.width * 0.7, y: r.y + r.height * 0.6}; })()"
        )
        if box is None:
            raise RuntimeError(f"no element for {js_element}")
        x, y = box["x"], box["y"]  # type: ignore[index]
        # The pointer goes there first, in view, and the press shows as a ring.
        await self.eval(
            "document.getElementById('pointer').style.transform ="
            f" 'translate({x - 2}px, {y - 2}px)'"
        )
        await self.capture(0.4)
        await self.eval(
            "document.querySelector('#pointer span').animate([{transform: 'scale(.2)',"
            " opacity: 1}, {transform: 'scale(1.2)', opacity: 0}], {duration: 380})"
        )
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
        """Frames at FPS for this long, the app running meanwhile. A picture
        takes a while to make, so one may have to stand for the frames that
        fell due meanwhile: the GIF then plays as long as the recording took,
        and not faster."""
        start = time.monotonic()
        made = 0
        while True:
            r = await self.call("Page.captureScreenshot", format="png")
            frame = base64.b64decode(r["data"])
            now = time.monotonic() - start
            due = max(made + 1, min(int(now * FPS) + 1, round(seconds * FPS)))
            self.frames.extend([frame] * (due - made))
            made = due
            if now >= seconds or made >= round(seconds * FPS):
                break
            await asyncio.sleep(max(0.0, made / FPS - (time.monotonic() - start)))


def browser() -> str:
    for name in (os.environ.get("MW_BROWSER"), "brave", "chromium", "google-chrome", "chrome"):
        if name and shutil.which(name):
            return name
    raise SystemExit("no browser found; set MW_BROWSER to a Chromium-family binary")


async def record(tab: Tab) -> None:
    url = f"http://127.0.0.1:{PORT}/"
    await tab.call(
        "Page.addScriptToEvaluateOnNewDocument",
        source="localStorage.setItem('mw:floating:root/assistant:window', "
        f"{json.dumps(json.dumps(WINDOW))})",
    )
    await tab.nav(url, settle=2.5)
    await tab.eval(POINTER)

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
    await tab.capture(1.3)
    await tab.select_all(amount)
    await tab.type("980")
    await tab.capture(0.3)
    await tab.click(
        "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Add')"
    )
    await tab.capture(1.2)

    # 2. An import with progress, the table and the chart following it.
    await tab.click(
        "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Import')"
    )
    await tab.capture(3.9)

    # 3. A question in the assistant's window, answered by a reply that streams.
    await tab.click("document.querySelector('button[aria-label=\"Ask about the orders\"]')")
    await tab.capture(0.5)
    await tab.click("document.querySelector('textarea')")
    await tab.type("How much is still open?")
    await tab.key("Enter")
    # The answer, the highlight it sets around the figure it is about, and a
    # moment on the finished page before the loop starts over.
    await tab.capture(5.8)


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
        # The demo's theme follows the browser, so the browser is told which
        # of the two it prefers, and each recording is a session of its own.
        for scheme, name in (("light", "demo.gif"), ("dark", "demo-dark.gif")):
            async with Tab() as tab:
                await tab.call(
                    "Emulation.setEmulatedMedia",
                    features=[{"name": "prefers-color-scheme", "value": scheme}],
                )
                await record(tab)
                frames = tab.frames
            gif(frames, HERE / name)
            size = (HERE / name).stat().st_size
            print(f"{len(frames)} frames, {len(frames) / FPS:.1f} s, {name} {size / 1e6:.2f} MB")
    finally:
        chrome.terminate()
        app.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
