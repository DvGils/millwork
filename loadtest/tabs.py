"""Tabs without a browser: each opens the session socket, says hello, keeps
the page it is sent, and presses what a person would. It reconnects the
way the bundle does, with the session it had, and says afterwards whether
it got that session back.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import urllib.request
from typing import Any

import websockets

from millwork.protocol import PROTOCOL_VERSION


class Tab:
    def __init__(self, url: str, number: int, cookies: bool = False) -> None:
        self.url = url.rstrip("/") + "/_mw/ws"
        self.page_url = "http" + url.rstrip("/").removeprefix("ws") + "/"
        self.number = number
        # A browser's cookies: what the page load set, and what the socket's
        # handshake set since. None for a tab that keeps none.
        self.cookies: dict[str, str] | None = {} if cookies else None
        self.ws: Any = None
        self.session: str | None = None
        self.resume: str | None = None
        self.seen = 0
        self.sent = 0
        self.props: dict[str, dict[str, Any]] = {}
        self.mounted = asyncio.Event()
        self.changed = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_code: int | None = None
        self.error: str | None = None
        self.sessions_had: list[str] = []
        self.mounts = 0
        self._reader: asyncio.Task[None] | None = None

    # ---- what the page says

    def text(self, key: str) -> str:
        return str(self.props.get(f"root/{key}", {}).get("content", ""))

    @property
    def replica(self) -> str:
        return self.text("replica").removeprefix("replica=")

    @property
    def n(self) -> int:
        return int(self.text("mark").removeprefix("n=") or -1)

    # ---- the socket

    async def open(self, timeout: float = 30.0) -> bool:
        """Connect and wait for the page. True when the session is the one
        this tab had before."""
        before = self.session
        self.mounted.clear()
        self.closed.clear()
        self.close_code = None
        headers = {}
        if self.cookies is not None:
            if not self.cookies:
                await asyncio.to_thread(self._load_page)
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        self.ws = await websockets.connect(
            self.url, max_size=None, open_timeout=timeout, additional_headers=headers
        )
        if self.cookies is not None:
            self._keep(self.ws.response.headers.get_all("Set-Cookie"))
        await self._say(
            {
                "type": "hello",
                "path": "/",
                "session": self.session,
                "resume": self.resume,
                "seq": self.seen,
                "protocol": PROTOCOL_VERSION,
            }
        )
        self._reader = asyncio.get_running_loop().create_task(self._read())
        async with asyncio.timeout(timeout):
            waits = [asyncio.ensure_future(e.wait()) for e in (self.mounted, self.closed)]
            try:
                await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for w in waits:
                    w.cancel()
        if not self.mounted.is_set():
            raise ConnectionError(f"closed with {self.close_code} before a page: {self.error}")
        return before is not None and self.session == before

    def _load_page(self) -> None:
        """The page, as a browser asks for it before it opens the socket."""
        with urllib.request.urlopen(self.page_url, timeout=30) as response:
            response.read()
            self._keep(response.headers.get_all("Set-Cookie") or [])

    def _keep(self, set_cookies: list[str]) -> None:
        assert self.cookies is not None
        for line in set_cookies:
            name, _, value = line.split(";", 1)[0].partition("=")
            self.cookies[name.strip()] = value.strip()

    async def _say(self, message: dict[str, Any]) -> None:
        await self.ws.send(json.dumps({"seq": self.sent, "msg": message}))
        self.sent += 1

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                packet = json.loads(raw)
                seq, msg = packet.get("seq", 0), packet["msg"]
                if seq:
                    self.seen = max(self.seen, seq)
                kind = msg["type"]
                if kind == "session":
                    if msg["id"] != self.session:
                        # Another session: nothing of the old page holds.
                        self.props, self.seen = {}, seq
                        self.sessions_had.append(msg["id"])
                    self.session, self.resume = msg["id"], msg["resume"]
                    if self.props:
                        # The session this tab had: its page stands.
                        self.mounted.set()
                elif kind == "mount":
                    self.props = {i: dict(n["props"]) for i, n in msg["nodes"].items()}
                    self.mounts += 1
                    self.mounted.set()
                elif kind == "patch":
                    for op in msg["ops"]:
                        if op["op"] == "set":
                            self.props.setdefault(op["id"], {}).update(op["props"])
                        elif op["op"] == "add":
                            self.props[op["node"]["id"]] = dict(op["node"]["props"])
                        elif op["op"] == "remove":
                            self.props.pop(op["id"], None)
                elif kind == "error":
                    self.error = msg["message"]
                self.changed.set()
        except websockets.ConnectionClosed:
            pass
        finally:
            self.close_code = self.ws.close_code
            self.closed.set()
            self.changed.set()

    async def drop(self) -> None:
        """The connection goes, as on a network that fails: no goodbye."""
        if self._reader is not None:
            self._reader.cancel()
        with contextlib.suppress(Exception):
            self.ws.transport.abort()
        self.closed.set()

    async def reconnect(self, tries: int = 12) -> tuple[bool, float]:
        """Come back as the bundle does: after 0.5 s, then 1 s and so on up
        to 10 s. Whether the session is the old one, and how long the tab
        was without a page."""
        began = time.monotonic()
        for retry in range(tries):
            await asyncio.sleep(min(10.0, 0.5 * 2**retry))
            try:
                resumed = await self.open()
                return resumed, time.monotonic() - began
            except (OSError, ConnectionError, TimeoutError, websockets.WebSocketException):
                continue
        raise ConnectionError("no page after every retry")

    # ---- what a person does

    async def until(self, ready: Any, timeout: float = 30.0) -> None:
        async with asyncio.timeout(timeout):
            while not ready():
                if self.closed.is_set():
                    raise ConnectionError(f"closed with {self.close_code}")
                self.changed.clear()
                await self.changed.wait()

    async def click(self, key: str = "bump") -> float:
        """Press the button and wait for the count to move. Seconds."""
        want = self.n + 1
        began = time.monotonic()
        await self._say({"type": "event", "node": f"root/{key}", "name": "click"})
        await self.until(lambda: self.n >= want)
        return time.monotonic() - began

    async def press(self, key: str) -> None:
        await self._say({"type": "event", "node": f"root/{key}", "name": "click"})

    async def type(self, key: str, value: str) -> None:
        await self._say({"type": "event", "node": f"root/{key}", "name": "change", "payload": value})


async def open_many(
    url: str, count: int, a_second: float = 300.0, cookies: bool = False
) -> list[Tab]:
    tabs = [Tab(url, i, cookies) for i in range(count)]
    pending = []
    for tab in tabs:
        pending.append(asyncio.ensure_future(tab.open()))
        await asyncio.sleep(1 / a_second)
    await asyncio.gather(*pending)
    return tabs


def spread(tabs: list[Tab]) -> dict[str, int]:
    found: dict[str, int] = {}
    for tab in tabs:
        found[tab.replica] = found.get(tab.replica, 0) + 1
    return dict(sorted(found.items()))


def percentiles(values: list[float]) -> str:
    if not values:
        return "nothing measured"
    ordered = sorted(values)

    def at(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(p * len(ordered)))] * 1e3

    return f"least {ordered[0] * 1e3:.1f} ms, p50 {at(0.5):.1f} ms, p95 {at(0.95):.1f} ms, p99 {at(0.99):.1f} ms, worst {ordered[-1] * 1e3:.0f} ms"
