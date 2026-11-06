"""A reverse proxy in front of the app.

With ``App(proxied=True)``, or ``millwork run --proxied``, the process is
behind a reverse proxy and believes what that proxy says: the visitor's
address and scheme from ``X-Forwarded-For`` and ``X-Forwarded-Proto``, and
the visitor's identity from the headers an ``auth.Headers`` provider names.
Whoever can reach the process can then send those headers, so a proxied
app listens where only its proxy connects: a unix socket, a loopback port,
a container network.

Without the switch the headers are ignored, which suits a process that
browsers reach directly, as in development. The middleware records the
switch in the scope as ``millwork.proxied`` for the auth layer.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

log = logging.getLogger("millwork.proxy")

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Any]]
Send = Callable[[Any], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class Proxied:
    """ASGI middleware: see through the proxy when the app says there is one.

    ``proxied`` is read on every connection, so the switch can be set after
    the app was built, as the CLI does."""

    def __init__(self, app: ASGIApp, proxied: Callable[[], bool]) -> None:
        self.app = app
        self.proxied = proxied
        self._bad_root: str | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            # The app's own root, noted before any routing: something the app
            # mounts sees a root with the mount's path added, and the cookie's
            # name and the app's URLs go by this one.
            scope["millwork.root"] = scope.get("root_path") or ""
            if not self._root_ok(scope):
                await _refuse(scope, send)
                return
            trusted = bool(self.proxied())
            scope["millwork.proxied"] = trusted
            if trusted:
                _see_through(scope)
        await self.app(scope, receive, send)

    def _root_ok(self, scope: Scope) -> bool:
        """The prefix the server was given must be plain path segments; one that
        is not would fail inside every handler, the error page included."""
        from millwork.shell import check_prefix

        root = scope.get("root_path", "")
        if root == self._bad_root:
            return False
        try:
            check_prefix(root)
        except ValueError as exc:
            self._bad_root = root
            log.error("every request refused: %s", exc)
            return False
        return True


def _see_through(scope: Scope) -> None:
    """The scheme and the visitor's address as the proxy forwarded them. A proxy
    appends the address it saw to ``X-Forwarded-For``, so the last one is the
    proxy's word and anything before it is whatever the browser sent."""
    proto: bytes | None = None
    forwarded: list[bytes] = []
    for name, value in scope["headers"]:
        if name == b"x-forwarded-proto":
            proto = value
        elif name == b"x-forwarded-for":
            forwarded.append(value)
    if proto is not None:
        scheme = proto.decode("latin-1").strip().lower()
        if scheme in ("http", "https", "ws", "wss"):
            if scope["type"] == "websocket":
                scheme = scheme.replace("http", "ws")
            scope["scheme"] = scheme
    if forwarded:
        last = b", ".join(forwarded).decode("latin-1").split(",")[-1].strip()
        host, port = _host_port(last)
        if host:
            scope["client"] = (host, port)


def _host_port(value: str) -> tuple[str, int]:
    """``host``, ``host:port`` or ``[v6]:port``; anything else is kept as given."""
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return value, 0
        rest = value[end + 1 :]
        if rest[:1] == ":" and rest[1:].isdigit():
            return value[1:end], int(rest[1:])
        return value[1:end], 0
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if port.isdigit():
            return host, int(port)
    return value, 0


async def _refuse(scope: Scope, send: Send) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1011})
        return
    body = b"millwork: the server's root path is not a valid prefix; see the log"
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": body})
