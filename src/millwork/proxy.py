"""Trust in the reverse proxy: which peers may speak for the visitor.

A proxy in front of the app sets ``X-Forwarded-For`` and ``X-Forwarded-Proto``,
and an authenticating proxy adds identity headers on top. Both are believed
only when the connection comes from a proxy the app was told about, so a
visitor who reaches the process directly cannot pick an address or a name.
The middleware records that decision in the scope as ``millwork.proxied``
and, for a trusted peer, rewrites ``client`` and ``scheme`` the way uvicorn's
own proxy-headers middleware does. It stands in for that middleware, because
the identity check needs the real peer, which that rewrite throws away.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Any]]
Send = Callable[[Any], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK = ("127.0.0.1", "::1")


class TrustedProxies:
    """The peers whose forwarded and identity headers are believed: ``"*"`` for
    every peer, otherwise addresses, networks in CIDR form, and literal names."""

    def __init__(self, proxies: list[str] | str | None) -> None:
        # Not naming any proxy means the local one: the loopback addresses, and
        # a unix socket, whose peer has no address and whose file permissions
        # decide who may connect at all.
        self.local = proxies is None
        if proxies is None:
            proxies = list(LOOPBACK)
        elif isinstance(proxies, str):
            proxies = [p.strip() for p in proxies.split(",") if p.strip()]
        self.all = "*" in proxies
        self.addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        self.networks: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()
        self.literals: set[str] = set()
        for item in proxies:
            if item == "*":
                continue
            if "/" in item:
                try:
                    self.networks.add(ipaddress.ip_network(item, strict=False))
                except ValueError:
                    raise ValueError(f"proxies: {item!r} is not a network") from None
                continue
            try:
                self.addresses.add(ipaddress.ip_address(item))
            except ValueError:
                if _looks_numeric(item):
                    raise ValueError(f"proxies: {item!r} is not an address") from None
                self.literals.add(item)

    def __contains__(self, host: str | None) -> bool:
        if self.all:
            return True
        if host is None:
            return self.local
        if not host:
            return False
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return host in self.literals
        return ip in self.addresses or any(ip in net for net in self.networks)

    def visitor(self, forwarded_for: str) -> tuple[str, int] | None:
        """The visitor's address from ``X-Forwarded-For``: the last entry that is
        not itself a trusted proxy, since every proxy appends its own peer."""
        hops = [h.strip() for h in forwarded_for.split(",")]
        if not self.all:
            for hop in reversed(hops):
                host, port = _host_port(hop)
                if host not in self:
                    return (host, port) if host else None
        host, port = _host_port(hops[0])
        return (host, port) if host else None


def _looks_numeric(item: str) -> bool:
    """A would-be address with a typo, rather than a host name: only digits,
    dots, colons and hex letters, as in ``300.1.1.1`` or ``::g``."""
    return all(c in "0123456789abcdefABCDEF.:[]" for c in item) and any(c in ".:" for c in item)


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


class Proxied:
    """ASGI middleware: mark a connection from a trusted proxy and see through it.

    ``proxies`` is read on every connection, so a list set after the app was
    built still counts."""

    def __init__(self, app: ASGIApp, proxies: Callable[[], TrustedProxies]) -> None:
        self.app = app
        self.proxies = proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            proxies = self.proxies()
            client = scope.get("client")
            peer = client[0] if client else None
            trusted = peer in proxies
            scope["millwork.proxied"] = trusted
            if trusted:
                self._see_through(scope, proxies)
        await self.app(scope, receive, send)

    def _see_through(self, scope: Scope, proxies: TrustedProxies) -> None:
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
            visitor = proxies.visitor(b", ".join(forwarded).decode("latin-1"))
            if visitor is not None:
                scope["client"] = visitor
