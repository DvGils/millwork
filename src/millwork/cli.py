"""``millwork run module:app`` and friends."""

from __future__ import annotations

import argparse
import contextlib
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
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, cast


def load_app(target: str, debug: bool = False, proxied: bool = False) -> object:
    """Import ``module:attribute`` or ``path/to/file.py:attribute``; the attribute
    defaults to ``app``.

    A module path is imported from the current directory. A file path is
    loaded from wherever it is, with its own directory importable so the app
    can import its neighbours.

    ``--debug`` switches a millwork App into debug mode (page errors in the
    tab, the theme file watched) as well as raising the log level, and
    ``--proxied`` tells the App a reverse proxy is in front of it.
    """
    app = load_object(target)
    if debug and hasattr(app, "debug"):
        app.debug = True
    if proxied and hasattr(app, "proxied"):
        app.proxied = True
    return getattr(app, "asgi", app)


def load_object(target: str) -> Any:
    """What a target names, as the module holds it."""
    module_name, attr = split_target(target)
    if module_name.endswith(".py") or os.sep in module_name:
        module = _import_file(module_name)
    else:
        sys.path.insert(0, os.getcwd())
        module = importlib.import_module(module_name)
    return getattr(module, attr or "app")


def split_target(target: str) -> tuple[str, str]:
    """``module:attribute`` or ``path:attribute``; a Windows drive letter is not a split."""
    module_name, sep, attr = target.rpartition(":")
    if sep and module_name and attr.isidentifier():
        return module_name, attr
    return target, ""


def _import_file(path: str) -> types.ModuleType:
    file = os.path.abspath(path)
    if not os.path.isfile(file):
        raise SystemExit(f"millwork: no such file: {path}")
    name = os.path.splitext(os.path.basename(file))[0]
    sys.path.insert(0, os.path.dirname(file))
    spec = importlib.util.spec_from_file_location(name, file)
    if spec is None or spec.loader is None:
        raise SystemExit(f"millwork: cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def configure_logging(debug: bool) -> None:
    """millwork's own lines at debug when asked; uvicorn stays at info, since its
    debug log, a line per socket frame, would bury them."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if debug:
        logging.getLogger("millwork").setLevel(logging.DEBUG)


def asgi_factory() -> object:
    """uvicorn's reloader needs an import string; this wraps ``load_app``. The
    reloader's server is a fresh process, so logging is configured here too."""
    from millwork import deprecation

    debug = os.environ.get("MILLWORK_DEBUG") == "1"
    configure_logging(debug)
    deprecation.show()
    return load_app(os.environ["MILLWORK_TARGET"], debug, os.environ.get("MILLWORK_PROXIED") == "1")


def main(argv: list[str] | None = None) -> int:
    from millwork import __version__, deprecation

    # Whatever the command, what it loads says which of its spellings are
    # on their way out.
    deprecation.show()
    parser = argparse.ArgumentParser(prog="millwork")
    parser.add_argument("--version", action="version", version=f"millwork {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="serve an app")
    run.add_argument(
        "target", help="the App as module:attribute or file.py:attribute, for example app:app"
    )
    run.add_argument("--host", default=None, help="default 127.0.0.1")
    run.add_argument("--port", type=int, default=None, help="default 8000")
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
        "--proxied",
        action="store_true",
        help="a reverse proxy is in front: its forwarded address and scheme and its "
        "identity headers are believed; implied by --uds",
    )
    docs = sub.add_parser("docs", help="serve the manual, with its live examples")
    docs.add_argument("--host", default=None, help="default 127.0.0.1")
    docs.add_argument("--port", type=int, default=None, help="default 8008")
    docs.add_argument("--uds", default=None, metavar="PATH", help="listen on a unix socket")
    docs.add_argument("--proxied", action="store_true", help="as for run; implied by --uds")
    docs.add_argument("--theme", default=None, help="a theme file to show the manual in")
    docs.add_argument("--root-path", default="", help="the path prefix the manual is served under")
    routes = sub.add_parser(
        "routes", help="list an app's pages, routes and mounts with who may reach each"
    )
    routes.add_argument(
        "target", help="the App as module:attribute or file.py:attribute, for example app:app"
    )
    ref = sub.add_parser(
        "reference",
        help="print the catalogue as Markdown, or what it and the manual say of one thing",
    )
    ref.add_argument(
        "words", nargs="*", help="what to look up: a name such as ui.Table, or words to search for"
    )
    ref.add_argument("--index", action="store_true", help="list the names without what is said")
    ref.add_argument(
        "--chars",
        type=int,
        default=None,
        help="how much to print for one lookup: 4000 by default for a search, 500 at least",
    )
    shot = sub.add_parser(
        "shot", help="save a picture of one page, as a browser on this machine shows it"
    )
    shot.add_argument("target", help="as for run")
    shot.add_argument("path", nargs="?", default="/", help="the page's path; default /")
    shot.add_argument("--out", default="shot.png", metavar="FILE", help="default shot.png")
    shot.add_argument("--width", type=int, default=1280, help="of the window; default 1280")
    shot.add_argument("--height", type=int, default=800, help="of the window; default 800")
    shot.add_argument("--full", action="store_true", help="the whole page, as far as it scrolls")
    shot.add_argument("--dark", action="store_true", help="as a browser set to dark shows it")
    shot.add_argument("--user", metavar="ID", help="sign in as this user, in an app with sign-in")
    shot.add_argument("--claims", metavar="JSON", help="the user's claims, as a JSON object")
    shot.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="how long to wait for the page to stop changing; default 10",
    )
    shot.add_argument(
        "--browser", help="the browser to use; default the first Chromium-family one found"
    )
    shot.add_argument(
        "--no-sandbox",
        action="store_true",
        help="run the browser without its sandbox, for a container that allows it none",
    )
    shot.add_argument("--debug", action="store_true", help="as for run")
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

    if args.command == "shot":
        from millwork import shot as picture

        return picture.main(args)
    if args.command == "docs":
        from millwork.manual import make_app

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        manual = make_app(theme=args.theme)
        manual.proxied = args.proxied or bool(args.uds)
        return serve(
            manual.asgi,
            host=args.host,
            port=args.port,
            default_port=8008,
            uds=args.uds,
            root_path=args.root_path,
            debug=False,
        )
    if args.command == "routes":
        app = load_object(args.target)
        if not callable(getattr(app, "access", None)):
            print(f"{args.target} is not a millwork App", file=sys.stderr)
            return 2
        rows = app.access()
        wide = max((len(path) for _, path, _ in rows), default=0)
        for kind, path, who in rows:
            print(f"{kind:<5}  {path:<{wide}}  {who}")
        return 0
    if args.command == "reference":
        from millwork import lookup
        from millwork.reference import reference

        if args.index and args.words:
            parser.error("--index lists every name, and takes no words")
        if args.chars is not None and (not args.words or args.chars < lookup.LEAST):
            parser.error(f"--chars goes with words to look up, and is {lookup.LEAST} at least")
        if args.index:
            print(lookup.names(), end="")
            return 0
        query = " ".join(args.words).strip()
        if not query:
            print(reference())
            return 0
        found = lookup.find(query, args.chars)
        if found is None:
            print(
                f"nothing in the reference or the manual is about {query!r};"
                " `millwork reference --index` lists what there is",
                file=sys.stderr,
            )
            return 1
        print(found, end="")
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

    configure_logging(args.debug)
    # A unix socket is only ever reached through a proxy.
    proxied = args.proxied or bool(args.uds)
    if args.reload:
        os.environ["MILLWORK_TARGET"] = args.target
        os.environ["MILLWORK_DEBUG"] = "1" if args.debug else "0"
        os.environ["MILLWORK_PROXIED"] = "1" if proxied else "0"
        # The folder the command runs in, and the app's own when the app is
        # a file somewhere else.
        watched = [os.getcwd()]
        file = split_target(args.target)[0]
        if file.endswith(".py") or os.sep in file:
            watched.append(os.path.dirname(os.path.abspath(file)))
        return serve(
            "millwork.cli:asgi_factory",
            factory=True,
            reload=True,
            watched=watched,
            host=args.host,
            port=args.port,
            uds=args.uds,
            root_path=args.root_path,
            debug=args.debug,
        )
    return serve(
        load_app(args.target, args.debug, proxied),
        host=args.host,
        port=args.port,
        uds=args.uds,
        root_path=args.root_path,
        debug=args.debug,
    )


# The largest message a tab may send on the socket. Uploads travel in frames of
# a quarter of this, so the bound costs nothing and caps every event's payload.
WS_MAX_SIZE = 1024 * 1024


def serve(
    app: object,
    *,
    host: str | None,
    port: int | None,
    uds: str | None,
    root_path: str,
    debug: bool,
    reload: bool = False,
    watched: list[str] | None = None,
    factory: bool = False,
    default_port: int = 8000,
) -> int:
    """Run uvicorn around the app. millwork handles proxy headers itself, so
    uvicorn's own handling is off. A unix socket is bound here rather than by
    uvicorn, so that it is never open to every local user: uvicorn would make
    it world-writable."""
    import uvicorn

    if uds and (host is not None or port is not None):
        print("--uds replaces --host and --port; give one or the other", file=sys.stderr)
        return 2
    config = uvicorn.Config(
        cast(Any, app),
        host=host or "127.0.0.1",
        port=port or default_port,
        uds=uds,
        proxy_headers=False,
        ws_max_size=WS_MAX_SIZE,
        root_path=root_path,
        log_level="info",
        reload=reload,
        reload_dirs=(watched or [os.getcwd()]) if reload else None,
        factory=factory,
    )
    server = uvicorn.Server(config)
    sock: socket.socket | None = None
    try:
        if uds:
            sock = bind_unix_socket(uds, config.backlog, inheritable=reload)
            # uvicorn says where it listens only for sockets it bound itself.
            logging.getLogger("millwork").info("listening on unix socket %s", uds)
    except OSError as exc:
        print(f"--uds: {exc}", file=sys.stderr)
        return 2
    try:
        if reload:
            sockets = [sock if sock is not None else config.bind_socket()]
            _reloader(config, server.run, sockets).run()
        elif sock is not None:
            server.run(sockets=[sock])
        else:
            server.run()
    except KeyboardInterrupt:
        pass
    return 0


# Folders that hold no code of the app's own.
_NOT_THE_APPS = frozenset({"node_modules", "__pycache__", "site-packages"})


def own_files(folders: Iterable[str | Path]) -> Iterator[Path]:
    """The Python files of an app under ``folders``. A virtual environment,
    by whatever name, a hidden folder and installed packages are left out."""
    for top in folders:
        for folder, inner, files in os.walk(top):
            inner[:] = [
                name
                for name in inner
                if not name.startswith(".")
                and name not in _NOT_THE_APPS
                and not os.path.exists(os.path.join(folder, name, "pyvenv.cfg"))
            ]
            for name in files:
                if name.endswith(".py"):
                    yield Path(folder, name)


def _reloader(config: Any, target: Any, sockets: list[socket.socket]) -> Any:
    """What restarts the server when a Python file changes.

    With watchfiles installed that is uvicorn's reloader, which the system
    tells of a change. Without it uvicorn's looks at every Python file
    under the folder, time and again, and a project's virtual environment
    alone holds thousands. Its first pass after each start only notes
    when a file was last changed, so an edit made during that pass is
    never seen, and a later one is seen a pass late. The one here looks
    at the app's own files, which takes no time to speak of."""
    from uvicorn.supervisors import ChangeReload
    from uvicorn.supervisors.statreload import StatReload

    if ChangeReload is not StatReload:
        return ChangeReload(config, target=target, sockets=sockets)

    class OwnFiles(StatReload):
        def iter_py_files(self) -> Iterator[Path]:
            return own_files(self.config.reload_dirs)

    return OwnFiles(config, target=target, sockets=sockets)


def _unix_family() -> int:
    """The address family for a unix socket, which Windows lacks."""
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise OSError("unix sockets are not available on this platform")
    return int(family)


def _answers(path: str) -> bool:
    """Whether a process listens on the socket. A connect on a unix socket
    answers at once: refused means nobody, and anything else means someone,
    including a listener too busy to accept."""
    probe = socket.socket(_unix_family(), socket.SOCK_STREAM)
    probe.setblocking(False)
    try:
        probe.connect(path)
    except (ConnectionRefusedError, FileNotFoundError):
        return False
    except OSError:
        return True
    else:
        return True
    finally:
        probe.close()


def bind_unix_socket(path: str, backlog: int, *, inheritable: bool) -> socket.socket:
    """A listening unix socket for the process's owner and group only: mode 0660
    whatever the umask, created under that mask so it is at no point open to
    everyone. Like a port, the path is refused while another process answers
    on it; a socket file nobody answers on was left by an earlier process and
    is replaced; anything else at the path stops the start. The file stays at
    exit, where the next start replaces it."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISSOCK(st.st_mode):
            raise OSError(f"{path} exists and is not a socket file")
        if _answers(path):
            raise OSError(f"{path} is in use by another process")
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
    sock = socket.socket(_unix_family(), socket.SOCK_STREAM)
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
    sock.set_inheritable(inheritable)
    sock.listen(backlog)
    return sock


if __name__ == "__main__":
    raise SystemExit(main())
