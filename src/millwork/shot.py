"""A picture of one page of an app, as a browser shows it.

``millwork shot app.py /orders`` serves the app on a free local port, opens
the page in a headless browser that is already on the machine, waits until
the page has stopped changing, and saves a PNG. The browser is driven over
its DevTools protocol on a websocket, so nothing is installed for it: any
Chromium-family browser will do.

The picture is of a page as it opens. Nothing is pressed or typed first.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from websockets.exceptions import ConnectionClosed, WebSocketException

# Looked for on the path, in this order.
NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "chromium",
    "chromium-browser",
    "brave",
    "brave-browser",
    "microsoft-edge",
    "msedge",
)
# Where a browser is installed without being on the path.
_MAC = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
_WINDOWS = (
    r"Google\Chrome\Application\chrome.exe",
    r"Chromium\Application\chrome.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
    r"Microsoft\Edge\Application\msedge.exe",
)

# The tallest picture a browser draws in one piece.
TALLEST = 16000
# How long a page has to stand still to count as done, in milliseconds.
STILL = 300
# How long the app and the browser each get to start, in seconds.
START = 30.0
# How long a browser gets to answer one thing asked of it, in seconds, on
# top of what the thing itself is given. One that says nothing for that long
# is not going to.
ANSWER = 60.0
# How long the cookie of a user signed in for a picture is good for.
SIGNED_IN = dt.timedelta(minutes=5)


class ShotError(Exception):
    """Why no picture was made, in words for the person who asked for one."""


@dataclass
class Shot:
    """What was saved, and how the page got there."""

    out: Path
    width: int
    height: int
    # Where the browser ended up, which is not where it was sent after a redirect.
    path: str
    # What the server answered for the page, when the browser said.
    status: int | None
    # False when the page was still changing as the wait ran out.
    still: bool
    # True when the page is taller than a picture can be, and its end is missing.
    cut: bool = False


def find_browsers(named: str | None = None) -> list[str]:
    """The browsers to try, in order: the one named or ``MILLWORK_BROWSER``
    and no other, or every Chromium-family browser found on the path and
    where its installer puts it."""
    wanted = named or os.environ.get("MILLWORK_BROWSER")
    if wanted:
        found = shutil.which(wanted)
        if found is None:
            raise ShotError(f"no browser at {wanted!r}")
        return [found]
    places: list[str] = []
    if sys.platform == "darwin":
        places = list(_MAC)
    elif sys.platform == "win32":
        roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        places = [os.path.join(root, tail) for root in roots if root for tail in _WINDOWS]
    on_path = [shutil.which(name) for name in NAMES]
    browsers: list[str] = []
    seen: set[str] = set()
    for one in [b for b in on_path if b] + [place for place in places if os.path.isfile(place)]:
        # One browser under two names is tried once.
        real = os.path.normcase(os.path.realpath(one))
        if real not in seen:
            seen.add(real)
            browsers.append(one)
    if not browsers:
        raise ShotError(
            "no browser found. A picture needs Chrome, Chromium, Edge or Brave on this "
            "machine; --browser or MILLWORK_BROWSER names one that is somewhere else"
        )
    return browsers


def find_browser(named: str | None = None) -> str:
    """The first of the browsers to try."""
    return find_browsers(named)[0]


def _port(file: Path) -> tuple[str, str] | None:
    """The port a browser took and its own address, once it has written both."""
    try:
        parts = file.read_text().split()
    except OSError:
        # Not there yet, or still held by the browser as it writes, which
        # Windows does not let another process read through.
        return None
    return (parts[0], parts[1]) if len(parts) >= 2 else None


def _why(said: str, code: int | None) -> str:
    """Why a browser ended as it started, from what it wrote: the line that
    says so, which a crash follows with a long trace."""
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    fatal = [line for line in lines if "FATAL" in line]
    # A browser writes errors it lives with as it starts. The last is the
    # nearest to what ended it.
    errors = [line for line in lines if "ERROR" in line]
    if fatal or errors:
        return (fatal[0] if fatal else errors[-1])[:400]
    return " ".join(lines[:3])[:400] or f"it ended with code {code}"


class _Tab:
    """One tab of a headless browser, over the DevTools protocol."""

    def __init__(self, browsers: list[str], sandbox: bool = True) -> None:
        self.browsers = browsers
        self.browser = browsers[0]
        # A browser refuses to start as root with its sandbox on, which is
        # how a container runs one.
        self.sandbox = sandbox and not (hasattr(os, "geteuid") and os.geteuid() == 0)
        self._n = 0
        self._session: str | None = None
        self._asked = False
        self.events: list[dict[str, Any]] = []

    async def __aenter__(self) -> _Tab:
        # A browser that will not start here is passed over for the next one
        # found. One build can be kept from its sandbox where another is not.
        failed: list[str] = []
        for browser in self.browsers:
            self.browser = browser
            self._stack = contextlib.AsyncExitStack()
            try:
                await self._start(browser)
                return self
            except ShotError as exc:
                await self._stack.aclose()
                failed.append(str(exc))
            except BaseException:
                await self._stack.aclose()
                raise
        why = "; ".join(failed)
        if "sandbox" in why.lower() and self.sandbox:
            why = why.rstrip(".") + (
                ". The browser's sandbox does not work here, as in many containers, "
                "and --no-sandbox runs it without one"
            )
        raise ShotError(why)

    async def _start(self, browser: str) -> None:
        from websockets.asyncio.client import connect

        self._n = 0
        self._session = None
        self.events = []
        # On Windows the browser can still hold a file as the profile goes.
        profile = self._stack.enter_context(
            tempfile.TemporaryDirectory(prefix="millwork-shot-", ignore_cleanup_errors=True)
        )
        said = Path(profile) / "browser.log"
        args = [
            browser,
            "--headless=new",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--hide-scrollbars",
            # A cookie is kept in the profile, and the keyring of the
            # person at the machine is not asked to guard it.
            "--use-mock-keychain",
            "--password-store=basic",
        ]
        if not self.sandbox:
            args.append("--no-sandbox")
        # A group of its own, so that Ctrl-C in the terminal stops this
        # command and the command closes the browser.
        apart: dict[str, Any] = {"start_new_session": True}
        if sys.platform == "win32":
            apart = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        with said.open("wb") as log:
            proc = await asyncio.create_subprocess_exec(
                *args,
                "about:blank",
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                **apart,
            )
        self._stack.push_async_callback(self._stop, proc)
        # The browser writes the port it took and its own address there.
        port_file = Path(profile) / "DevToolsActivePort"
        waited = 0.0
        while (reached := _port(port_file)) is None:
            if proc.returncode is not None:
                # What it wrote may be held by a helper of it that is still ending.
                wrote = ""
                with contextlib.suppress(OSError):
                    wrote = said.read_text(errors="replace")
                why = _why(wrote, proc.returncode)
                raise ShotError(f"{browser} would not start: {why}")
            if waited >= START:
                raise ShotError(f"{browser} did not start in {START:g} s")
            await asyncio.sleep(0.05)
            waited += 0.05
        port, address = reached
        try:
            # A proxy named in the environment is not for a browser on this machine.
            self._ws = await self._stack.enter_async_context(
                connect(f"ws://127.0.0.1:{port}{address}", max_size=None, proxy=None)
            )
            # A browser that started gets as long to say so as it got to start.
            target = await self._ask("Target.createTarget", {"url": "about:blank"}, START)
            attach = {"targetId": target["targetId"], "flatten": True}
            attached = await self._ask("Target.attachToTarget", attach, START)
        except (OSError, WebSocketException) as exc:
            raise ShotError(f"{browser} started and could not be reached: {exc}") from exc
        self._session = attached["sessionId"]

    async def __aexit__(self, *exc: object) -> None:
        # Asked to close, a browser ends its helpers and stops writing to its
        # profile before the profile is removed. Stopped, it may not.
        with contextlib.suppress(Exception):
            self._session = None
            await asyncio.wait_for(self.call("Browser.close"), 2)
            self._asked = True
        await self._stack.aclose()

    async def _stop(self, proc: asyncio.subprocess.Process) -> None:
        if self._asked:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), 3)
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        return await self._ask(method, params, ANSWER)

    async def _ask(self, method: str, params: dict[str, Any], within: float) -> dict[str, Any]:
        self._n += 1
        message: dict[str, Any] = {"id": self._n, "method": method, "params": params}
        if self._session is not None:
            message["sessionId"] = self._session
        try:
            async with asyncio.timeout(within):
                await self._ws.send(json.dumps(message))
                while True:
                    answer = json.loads(await self._ws.recv())
                    if answer.get("id") == self._n:
                        break
                    self.events.append(answer)
        except TimeoutError:
            raise ShotError(f"the browser did not answer {method} in {within:g} s") from None
        if "error" in answer:
            raise ShotError(f"the browser refused {method}: {answer['error'].get('message')}")
        result: dict[str, Any] = answer.get("result", {})
        return result

    async def value(self, script: str, at_most: float = 0.0) -> Any:
        """What a script comes to in the page, a promise awaited. A script
        that waits for something says for how long ``at_most``, in seconds,
        and is given that long to answer and a while more."""
        asked = {"expression": script, "returnByValue": True, "awaitPromise": True}
        answer = await self._ask("Runtime.evaluate", asked, ANSWER + at_most)
        if "exceptionDetails" in answer:
            raise ShotError("the page could not be read: " + answer["exceptionDetails"]["text"])
        return answer["result"].get("value")


# A page is done when, for a moment, nothing in it changes, no animation runs,
# and its fonts and pictures are in. A spinner counts as running, so a page
# that loads its data is waited for, and one that never rests runs out the
# time it was given. An animation that goes by how far something has
# scrolled, and not by the clock, runs for as long as its element is there
# and is no sign of a page at work.
_SETTLE = """
new Promise((done) => {
  const deadline = performance.now() + %(timeout)d;
  let last = performance.now();
  const watch = new MutationObserver(() => { last = performance.now(); });
  const all = { subtree: true, childList: true, attributes: true, characterData: true };
  watch.observe(document, all);
  const busy = () =>
    !document.getElementById("root")?.childElementCount
    || document.fonts.status !== "loaded"
    || Array.from(document.images).some((i) => !i.complete)
    || document.getAnimations().some(
      (a) => a.playState === "running" && a.timeline instanceof DocumentTimeline,
    );
  const look = () => {
    const now = performance.now();
    if (busy()) last = now;
    if (now - last >= %(still)d || now >= deadline) {
      watch.disconnect();
      done(now - last >= %(still)d);
    } else setTimeout(look, 50);
  };
  look();
})
"""

# How much of the page is below the window: of the shell's body, which is
# what scrolls in a page with a shell, or of the document.
_BELOW = """
(() => {
  const body = document.querySelector(".mw-shell-body");
  const below = body
    ? body.scrollHeight - body.clientHeight
    : document.documentElement.scrollHeight - window.innerHeight;
  return Math.max(0, Math.ceil(below));
})()
"""


@contextlib.asynccontextmanager
async def _served(app: Any) -> AsyncIterator[str]:
    """The app on a free local port, for as long as the block runs."""
    import uvicorn

    from millwork.cli import WS_MAX_SIZE

    config = uvicorn.Config(
        app.asgi,
        host="127.0.0.1",
        port=0,
        proxy_headers=False,
        ws_max_size=WS_MAX_SIZE,
        log_level="warning",
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)

    # In a thread of its own the server leaves this process's signals alone,
    # and an app that fails to start ends that thread and nothing else. One
    # that hangs as it starts is left behind there when the command ends.
    def run() -> None:
        # A server whose app fails to start says so and leaves by SystemExit.
        with contextlib.suppress(SystemExit):
            server.run()

    thread = threading.Thread(target=run, name="millwork shot: the app", daemon=True)
    thread.start()
    try:
        waited = 0.0
        while not server.started:
            if not thread.is_alive():
                raise ShotError("the app did not start")
            if waited >= START:
                raise ShotError(f"the app did not start in {START:g} s")
            await asyncio.sleep(0.02)
            waited += 0.02
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)


async def shoot(
    app: Any,
    path: str = "/",
    *,
    out: Path | str = "shot.png",
    width: int = 1280,
    height: int = 800,
    full: bool = False,
    dark: bool = False,
    user: Any = None,
    timeout: float = 10.0,
    browser: str | None = None,
    sandbox: bool = True,
) -> Shot:
    """Save a picture of the page at ``path`` and say how it went.

    ``full`` makes the picture as tall as the page. ``dark`` is the page as a
    browser set to dark shows it. ``user`` is a ``mw.User`` to be signed in
    as, for an app with sign-in. The cookie is made with the app's own secret
    and is good for a few minutes. ``on_login`` is not asked about the user,
    and the app's ``recheck`` is. ``sandbox=False`` runs the browser without
    its sandbox, for a container that does not let it have one.
    """
    if not path.startswith("/") or path.startswith("//"):
        raise ShotError(f"a path starts with one slash, and {path!r} does not")
    if not callable(getattr(app, "access", None)):
        raise ShotError("a picture is of a millwork App")
    if user is not None and app.auth is None:
        raise ShotError("the app has no sign-in, so there is nobody to be")
    if not (200 <= width <= 4000 and 200 <= height <= TALLEST):
        raise ShotError(f"a picture is 200 to 4000 wide and 200 to {TALLEST} high")
    found = find_browsers(browser)
    out = Path(out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ShotError(f"no folder for {out}: {exc}") from exc
    wait = int(timeout * 1000)
    tab = _Tab(found, sandbox)
    try:
        return await _shoot(app, path, out, width, height, full, dark, user, wait, tab)
    except ConnectionClosed as exc:
        raise ShotError(f"{tab.browser} went away before the picture was made") from exc


async def _shoot(
    app: Any,
    path: str,
    out: Path,
    width: int,
    height: int,
    full: bool,
    dark: bool,
    user: Any,
    wait: int,
    tab: _Tab,
) -> Shot:
    async with _served(app) as base, tab:
        await tab.call("Page.enable")
        await tab.call("Network.enable")
        metrics = {"width": width, "deviceScaleFactor": 1, "mobile": False}
        await tab.call("Emulation.setDeviceMetricsOverride", height=height, **metrics)
        scheme = {"name": "prefers-color-scheme", "value": "dark" if dark else "light"}
        await tab.call("Emulation.setEmulatedMedia", features=[scheme])
        if user is not None:
            from millwork.auth import AUTH_COOKIE

            await tab.call(
                "Network.setCookie",
                name=AUTH_COOKIE,
                value=app.auth.issue(user, SIGNED_IN),
                url=base,
                httpOnly=True,
            )
        went = await tab.call("Page.navigate", url=base + path)
        if went.get("errorText"):
            raise ShotError(f"the browser could not open the page: {went['errorText']}")
        still = bool(await tab.value(_SETTLE % {"timeout": wait, "still": STILL}, wait / 1000))
        cut = False
        if full:
            below = int(await tab.value(_BELOW))
            if below:
                cut = height + below > TALLEST
                height = min(height + below, TALLEST)
                await tab.call("Emulation.setDeviceMetricsOverride", height=height, **metrics)
                # What comes into view may have waited for that to load.
                again = await tab.value(_SETTLE % {"timeout": min(wait, 3000), "still": STILL}, 3)
                still = still and bool(again)
        picture = await tab.call("Page.captureScreenshot", format="png")
        ended = urlsplit(str(await tab.value("location.href")))
        # The answer to the page itself, the last one after any redirect.
        answers = [
            e["params"]["response"]["status"]
            for e in tab.events
            if e.get("method") == "Network.responseReceived"
            and e["params"].get("type") == "Document"
            and e["params"].get("frameId") == went.get("frameId")
        ]
    await asyncio.to_thread(out.write_bytes, base64.b64decode(picture["data"]))
    where = ended.path + (f"?{ended.query}" if ended.query else "")
    return Shot(out, width, height, where, answers[-1] if answers else None, still, cut)


def _interrupted(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def main(args: Any) -> int:
    """``millwork shot``: the picture, one line about it, and what to know."""
    from millwork.cli import load_object

    app = load_object(args.target)
    if args.debug and hasattr(app, "debug"):
        app.debug = True
    user = None
    try:
        if args.claims and not args.user:
            raise ShotError("--claims goes with --user")
        if args.user:
            from millwork.auth import User

            claims = json.loads(args.claims) if args.claims else {}
            if not isinstance(claims, dict):
                raise ShotError("--claims is a JSON object")
            user = User(id=args.user, name=args.user, claims=claims)
        # Stopped by a signal, the command still closes the browser it started.
        main_thread = threading.current_thread() is threading.main_thread()
        before = signal.signal(signal.SIGTERM, _interrupted) if main_thread else None
        try:
            shot = asyncio.run(
                shoot(
                    app,
                    args.path,
                    out=args.out,
                    width=args.width,
                    height=args.height,
                    full=args.full,
                    dark=args.dark,
                    user=user,
                    timeout=args.timeout,
                    browser=args.browser,
                    sandbox=not args.no_sandbox,
                )
            )
        finally:
            if main_thread:
                signal.signal(signal.SIGTERM, before or signal.SIG_DFL)
    except json.JSONDecodeError as exc:
        print(f"--claims is not JSON: {exc}", file=sys.stderr)
        return 2
    except ShotError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    print(f"{shot.out}  {shot.width}x{shot.height}  {shot.path}")
    if unquote(urlsplit(shot.path).path) != unquote(urlsplit(args.path).path):
        print(f"the page sent the browser on to {shot.path}", file=sys.stderr)
    if shot.cut:
        print(
            f"the page is taller than {TALLEST} pixels, and the picture ends there",
            file=sys.stderr,
        )
    if shot.status is not None and shot.status != 200:
        print(f"the page answered {shot.status}", file=sys.stderr)
    if not shot.still:
        print(
            f"the page was still changing after {args.timeout:g} s, so this is how it "
            "looked then; --timeout waits longer or shorter",
            file=sys.stderr,
        )
    return 0
