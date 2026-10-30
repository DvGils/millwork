"""``millwork run module:app`` and friends."""

from __future__ import annotations

import argparse
import getpass
import importlib
import importlib.util
import logging
import os
import secrets
import socket
import stat
import sys
import types
from typing import Any, cast


def load_app(target: str, debug: bool = False, proxies: str | None = None) -> object:
    """Import ``module:attribute`` or ``path/to/file.py:attribute``; the attribute
    defaults to ``app``.

    A module path is imported from the current directory. A file path is
    loaded from wherever it is, with its own directory importable so the app
    can import its neighbours.

    ``--debug`` switches a millwork App into debug mode (page errors in the
    tab, the theme file watched) as well as raising the log level, and
    ``--proxy`` names the proxies the App believes.
    """
    module_name, attr = split_target(target)
    if module_name.endswith(".py") or os.sep in module_name:
        module = _import_file(module_name)
    else:
        sys.path.insert(0, os.getcwd())
        module = importlib.import_module(module_name)
    app = getattr(module, attr or "app")
    if debug and hasattr(app, "debug"):
        app.debug = True
    if proxies is not None and hasattr(app, "proxies"):
        app.proxies = proxies
    return getattr(app, "asgi", app)


def split_target(target: str) -> tuple[str, str]:
    """``module:attribute`` or ``path:attribute``; a Windows drive letter is not a split."""
    module_name, sep, attr = target.rpartition(":")
    if sep and module_name and attr.isidentifier():
        return module_name, attr
    return target, ""


def _import_file(path: str) -> types.ModuleType:
    file = os.path.abspath(path)
    if not os.path.isfile(file):
        raise SystemExit(f"millwork run: no such file: {path}")
    name = os.path.splitext(os.path.basename(file))[0]
    sys.path.insert(0, os.path.dirname(file))
    spec = importlib.util.spec_from_file_location(name, file)
    if spec is None or spec.loader is None:
        raise SystemExit(f"millwork run: cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def asgi_factory() -> object:
    """uvicorn's reloader needs an import string; this wraps ``load_app``."""
    return load_app(
        os.environ["MILLWORK_TARGET"],
        os.environ.get("MILLWORK_DEBUG") == "1",
        os.environ.get("MILLWORK_PROXY") or None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="millwork")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="serve an app")
    run.add_argument(
        "target", help="the App as module:attribute or file.py:attribute, for example app:app"
    )
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)
    run.add_argument(
        "--uds",
        default=None,
        metavar="PATH",
        help="listen on a unix socket at this path instead of a host and port; the socket "
        "is created for its owner and group only",
    )
    run.add_argument("--debug", action="store_true")
    run.add_argument(
        "--root-path",
        default="",
        help="the path prefix the app is served under, such as /sales",
    )
    run.add_argument("--reload", action="store_true", help="restart the process on Python changes")
    run.add_argument(
        "--proxy",
        default=None,
        metavar="IPS",
        help="the reverse proxies to believe for X-Forwarded-* and identity headers: "
        "addresses or networks, comma separated, or *; the local host by default",
    )
    docs = sub.add_parser("docs", help="serve the manual, with its live examples")
    docs.add_argument("--host", default="127.0.0.1")
    docs.add_argument("--port", type=int, default=8008)
    docs.add_argument("--theme", default=None, help="a theme file to show the manual in")
    docs.add_argument("--root-path", default="", help="the path prefix the manual is served under")
    sub.add_parser("secret", help="print a signing secret for App(secret=...)")
    hp = sub.add_parser("hash-password", help="hash a password for a Password provider")
    hp.add_argument("--user", default="", help="prefix the line with the user name")
    args = parser.parse_args(argv)
    if getattr(args, "root_path", ""):
        from millwork.shell import check_prefix

        try:
            args.root_path = check_prefix(args.root_path)
        except ValueError as exc:
            print(f"--root-path: {exc}", file=sys.stderr)
            return 2

    if getattr(args, "proxy", None):
        from millwork.proxy import TrustedProxies

        try:
            TrustedProxies(args.proxy)
        except ValueError as exc:
            print(f"--proxy: {exc}", file=sys.stderr)
            return 2

    if args.command == "docs":
        import uvicorn

        from millwork.manual import make_app

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        uvicorn.run(
            cast(Any, make_app(theme=args.theme).asgi),
            host=args.host,
            port=args.port,
            proxy_headers=False,
            root_path=args.root_path,
        )
        return 0
    if args.command == "secret":
        print(secrets.token_urlsafe(48))
        return 0
    if args.command == "hash-password":
        from millwork.auth import hash_password

        pw = getpass.getpass("Password: ")
        again = getpass.getpass("Again: ")
        if pw != again:
            print("the passwords differ", file=sys.stderr)
            return 1
        line = hash_password(pw)
        print(f"{args.user}:{line}" if args.user else line)
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.reload:
        os.environ["MILLWORK_TARGET"] = args.target
        os.environ["MILLWORK_DEBUG"] = "1" if args.debug else "0"
        os.environ["MILLWORK_PROXY"] = args.proxy or ""
        return serve(
            "millwork.cli:asgi_factory",
            factory=True,
            reload=True,
            host=args.host,
            port=args.port,
            uds=args.uds,
            root_path=args.root_path,
            debug=args.debug,
        )
    return serve(
        load_app(args.target, args.debug, args.proxy),
        host=args.host,
        port=args.port,
        uds=args.uds,
        root_path=args.root_path,
        debug=args.debug,
    )


def serve(
    app: object,
    *,
    host: str,
    port: int,
    uds: str | None,
    root_path: str,
    debug: bool,
    reload: bool = False,
    factory: bool = False,
) -> int:
    """Run uvicorn around the app. millwork handles proxy headers itself, so
    uvicorn's own handling is off. A unix socket is bound here rather than by
    uvicorn, so that it is never open to every local user: uvicorn would make
    it world-writable."""
    import uvicorn

    config = uvicorn.Config(
        cast(Any, app),
        host=host,
        port=port,
        uds=uds,
        proxy_headers=False,
        root_path=root_path,
        log_level="debug" if debug else "info",
        reload=reload,
        reload_dirs=[os.getcwd()] if reload else None,
        factory=factory,
    )
    # The reloader pickles the server for the process it spawns, which a class
    # defined in a function cannot be; there the supervisor removes the socket.
    server = (uvicorn.Server if reload else _server_class())(config)
    usock: UnixSocket | None = None
    try:
        if uds:
            usock = UnixSocket(uds, config.backlog, inheritable=reload)
            server.owned = usock
    except OSError as exc:
        print(f"--uds: {exc}", file=sys.stderr)
        return 2
    try:
        if reload:
            from uvicorn.supervisors import ChangeReload

            sockets = [usock.sock if usock else config.bind_socket()]
            ChangeReload(config, target=server.run, sockets=sockets).run()
        elif usock is not None:
            server.run(sockets=[usock.sock])
        else:
            server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if usock is not None:
            usock.close()
            usock.remove()
    return 0


def _server_class() -> type:
    import uvicorn

    class Server(uvicorn.Server):
        """Removes the unix socket file as part of shutting down. After the
        server loop uvicorn re-raises the signal that stopped it, which ends the
        process before any cleanup around ``run`` could happen. Under the
        reloader the supervisor owns the socket and removes it when it exits."""

        owned: UnixSocket | None = None

        async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
            await super().shutdown(sockets)
            if self.owned is not None:
                self.owned.remove()

    return Server


class UnixSocket:
    """A listening unix socket the process owns: made for its owner and group
    only (mode 0660, whatever the umask, created under that mask so it is never
    briefly open to everyone), and removed at the end only while the path still
    holds the very socket that was created, never something put there since.

    Whatever is at the path first must be a socket. One nobody answers on was
    left by a crashed process and is replaced; one that answers, or cannot be
    told apart from a live one within a second, is refused.
    """

    def __init__(self, path: str, backlog: int, *, inheritable: bool) -> None:
        self.path = path
        self._clear(path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        mask = os.umask(0o117)
        try:
            sock.bind(path)
        except FileNotFoundError:
            sock.close()
            raise OSError(f"{path}: the directory does not exist") from None
        except OSError:
            sock.close()
            raise
        finally:
            os.umask(mask)
        st = os.lstat(path)
        self.ident = (st.st_dev, st.st_ino)
        sock.set_inheritable(inheritable)
        sock.listen(backlog)
        self.sock = sock

    @staticmethod
    def _clear(path: str) -> None:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(st.st_mode):
            raise OSError(f"{path} exists and is not a socket")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        try:
            probe.connect(path)
        except ConnectionRefusedError:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise OSError(f"{path} may be in use ({exc.strerror or exc})") from None
        else:
            raise OSError(f"{path} is in use by another process")
        finally:
            probe.close()

    def close(self) -> None:
        self.sock.close()

    def remove(self) -> None:
        try:
            st = os.lstat(self.path)
            if stat.S_ISSOCK(st.st_mode) and (st.st_dev, st.st_ino) == self.ident:
                os.remove(self.path)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
