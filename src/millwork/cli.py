"""``millwork run module:app`` and friends."""

from __future__ import annotations

import argparse
import getpass
import importlib
import importlib.util
import logging
import os
import secrets
import sys
import types
from typing import Any, cast


def load_app(target: str, debug: bool = False) -> object:
    """Import ``module:attribute`` or ``path/to/file.py:attribute``; the attribute
    defaults to ``app``.

    A module path is imported from the current directory. A file path is
    loaded from wherever it is, with its own directory importable so the app
    can import its neighbours.

    ``--debug`` switches a millwork App into debug mode (page errors in the
    tab, the theme file watched) as well as raising the log level.
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
    return load_app(os.environ["MILLWORK_TARGET"], os.environ.get("MILLWORK_DEBUG") == "1")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="millwork")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="serve an app")
    run.add_argument(
        "target", help="the App as module:attribute or file.py:attribute, for example app:app"
    )
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)
    run.add_argument("--debug", action="store_true")
    run.add_argument("--reload", action="store_true", help="restart the process on Python changes")
    run.add_argument(
        "--proxy",
        default=None,
        metavar="IPS",
        help="trust X-Forwarded-* from these proxy addresses (comma separated, or *)",
    )
    docs = sub.add_parser("docs", help="serve the manual, with its live examples")
    docs.add_argument("--host", default="127.0.0.1")
    docs.add_argument("--port", type=int, default=8008)
    docs.add_argument("--theme", default=None, help="a theme file to show the manual in")
    sub.add_parser("secret", help="print a signing secret for App(secret=...)")
    hp = sub.add_parser("hash-password", help="hash a password for a Password provider")
    hp.add_argument("--user", default="", help="prefix the line with the user name")
    args = parser.parse_args(argv)

    if args.command == "docs":
        import uvicorn

        from millwork.manual import make_app

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        uvicorn.run(cast(Any, make_app(theme=args.theme).asgi), host=args.host, port=args.port)
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
    import uvicorn

    if args.reload:
        os.environ["MILLWORK_TARGET"] = args.target
        os.environ["MILLWORK_DEBUG"] = "1" if args.debug else "0"
        uvicorn.run(
            "millwork.cli:asgi_factory",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[os.getcwd()],
            forwarded_allow_ips=args.proxy,
        )
        return 0
    uvicorn.run(
        cast(Any, load_app(args.target, args.debug)),
        host=args.host,
        port=args.port,
        log_level="debug" if args.debug else "info",
        forwarded_allow_ips=args.proxy,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
