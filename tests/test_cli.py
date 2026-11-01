"""``millwork run`` loads an app from a module path or a file path."""

import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from millwork.cli import load_app


def test_a_file_path_loads_the_app_with_its_directory_importable(tmp_path: Path) -> None:
    (tmp_path / "helper.py").write_text("GREETING = 'hi'\n")
    (tmp_path / "demo.py").write_text(
        "import helper\nimport millwork as mw\n"
        "app = mw.App('demo')\napp.greeting = helper.GREETING\n"
    )
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path.parent)
        asgi = load_app(f"{tmp_path.name}/demo.py", debug=True)
        module = sys.modules["demo"]
    finally:
        os.chdir(cwd)
        sys.modules.pop("demo", None)
        sys.modules.pop("helper", None)
    assert asgi is module.app.asgi
    assert module.app.debug is True and module.app.greeting == "hi"


def test_a_missing_file_exits_with_a_message(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no such file"):
        load_app(str(tmp_path / "nope.py"))


def test_the_target_splits_at_the_attribute_not_a_drive_letter() -> None:
    from millwork.cli import split_target

    assert split_target("app.py") == ("app.py", "")
    assert split_target("app.py:app") == ("app.py", "app")
    assert split_target("pkg.mod:make_app") == ("pkg.mod", "make_app")
    assert split_target("C:\\apps\\app.py") == ("C:\\apps\\app.py", "")
    assert split_target("C:\\apps\\app.py:app") == ("C:\\apps\\app.py", "app")


def write_demo(tmp_path: Path) -> str:
    (tmp_path / "demo.py").write_text("import millwork as mw\napp = mw.App('demo', public=None)\n")
    return str(tmp_path / "demo.py")


@pytest.fixture
def sock_dir() -> Iterator[Path]:
    """A short directory: a unix socket path is limited to about a hundred bytes."""
    d = Path(tempfile.mkdtemp(prefix="mw"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


unix_only = pytest.mark.skipif(sys.platform == "win32", reason="no unix sockets")


@unix_only
def test_a_unix_socket_is_bound_for_owner_and_group_only(
    tmp_path: Path, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    import stat

    import uvicorn

    from millwork.cli import main

    seen: list[tuple[uvicorn.Config, list[socket.socket] | None]] = []

    def run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        seen.append((self.config, sockets))
        assert sockets is not None and os.path.exists(path)
        assert stat.S_ISSOCK(os.stat(path).st_mode)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o660
        assert not sockets[0].get_inheritable()
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.connect(path)
        probe.close()
        for sock in sockets:
            sock.close()

    monkeypatch.setattr(uvicorn.Server, "run", run)
    path = str(sock_dir / "app.sock")
    mask = os.umask(0o077)  # the mode holds whatever the process umask is
    try:
        assert main(["run", write_demo(tmp_path), "--uds", path, "--root-path", "/x"]) == 0
    finally:
        os.umask(mask)
    assert os.umask(mask) == mask  # and the umask is back to what it was
    config, sockets = seen[0]
    assert config.uds == path and config.proxy_headers is False and config.root_path == "/x"
    assert sockets is not None and sockets[0].family == socket.AF_UNIX
    # The socket file stays at exit, and the next start binds the path again:
    # its fake run above connects to what it finds there.
    assert os.path.exists(path)
    assert main(["run", str(tmp_path / "demo.py"), "--uds", path]) == 0 and len(seen) == 2
    # A socket another process answers on is refused and left alone, like a port.
    busy = str(sock_dir / "busy.sock")
    live = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    live.bind(busy)
    live.listen(1)
    try:
        held = os.stat(busy).st_ino
        assert main(["run", str(tmp_path / "demo.py"), "--uds", busy]) == 2
        assert os.stat(busy).st_ino == held
    finally:
        live.close()
    # Anything at the path that is not a socket stops the start and is left alone.
    (sock_dir / "precious.txt").write_text("data")
    assert main(["run", str(tmp_path / "demo.py"), "--uds", str(sock_dir / "precious.txt")]) == 2
    assert (sock_dir / "precious.txt").read_text() == "data"
    assert main(["run", str(tmp_path / "demo.py"), "--uds", str(sock_dir / "no/dir.sock")]) == 2
    assert main(["run", str(tmp_path / "demo.py"), "--uds", path, "--port", "1"]) == 2
    assert len(seen) == 2


@unix_only
def test_reload_mode_passes_the_bound_socket_to_the_reloader(
    tmp_path: Path, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    import uvicorn.supervisors

    from millwork.cli import main

    for key in ("MILLWORK_TARGET", "MILLWORK_DEBUG", "MILLWORK_PROXIED"):
        monkeypatch.setenv(key, "")  # so the values main sets are undone afterwards
    seen: list[tuple[int, bool]] = []

    class Reloader:
        def __init__(self, config: object, target: object, sockets: list[socket.socket]) -> None:
            seen.append((sockets[0].family, sockets[0].get_inheritable()))
            for sock in sockets:
                sock.close()

        def run(self) -> None:
            pass

    monkeypatch.setattr(uvicorn.supervisors, "ChangeReload", Reloader)
    path = str(sock_dir / "app.sock")
    assert main(["run", write_demo(tmp_path), "--reload", "--uds", path]) == 0
    assert seen[0] == (socket.AF_UNIX, True)
    assert main(["run", str(tmp_path / "demo.py"), "--reload", "--port", "0"]) == 0
    assert seen[1][0] in (socket.AF_INET, socket.AF_INET6)


def test_serve_bounds_what_a_tab_may_send_on_the_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from millwork.cli import WS_MAX_SIZE, serve

    seen: dict[str, object] = {}

    class Config:
        def __init__(self, app: object, **kw: object) -> None:
            seen.update(kw)
            self.backlog = 2048

    class Server:
        def __init__(self, config: object) -> None:
            pass

        def run(self, sockets: object = None) -> None:
            pass

    monkeypatch.setattr(uvicorn, "Config", Config)
    monkeypatch.setattr(uvicorn, "Server", Server)
    assert serve(object(), host=None, port=None, uds=None, root_path="", debug=False) == 0
    assert seen["ws_max_size"] == WS_MAX_SIZE == 1024 * 1024 and seen["proxy_headers"] is False
