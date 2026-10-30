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
    assert not os.path.exists(path)  # removed on exit
    # A socket file left behind is replaced; one that answers is refused and
    # left alone; a file that is not a socket is refused and left alone.
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(path)
    stale.close()
    assert main(["run", str(tmp_path / "demo.py"), "--uds", path]) == 0 and len(seen) == 2
    live = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    live.bind(path)
    live.listen(1)
    try:
        assert main(["run", str(tmp_path / "demo.py"), "--uds", path]) == 2
        assert stat.S_ISSOCK(os.stat(path).st_mode)
    finally:
        live.close()
        os.remove(path)
    (sock_dir / "precious.txt").write_text("data")
    assert main(["run", str(tmp_path / "demo.py"), "--uds", str(sock_dir / "precious.txt")]) == 2
    assert (sock_dir / "precious.txt").read_text() == "data"
    assert main(["run", str(tmp_path / "demo.py"), "--uds", str(sock_dir / "no/dir.sock")]) == 2
    assert len(seen) == 2


@unix_only
def test_exit_only_removes_the_socket_the_process_made(
    tmp_path: Path, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    import uvicorn

    from millwork.cli import main

    path = str(sock_dir / "app.sock")
    other = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        # The socket is removed while running and another process binds the path.
        os.remove(path)
        other.bind(path)
        other.listen(1)

    monkeypatch.setattr(uvicorn.Server, "run", run)
    try:
        assert main(["run", write_demo(tmp_path), "--uds", path]) == 0
        assert os.path.exists(path)
    finally:
        other.close()


@unix_only
def test_reload_mode_passes_the_bound_socket_to_the_reloader(
    tmp_path: Path, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    import uvicorn.supervisors

    from millwork.cli import main

    for key in ("MILLWORK_TARGET", "MILLWORK_DEBUG", "MILLWORK_PROXY"):
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
    assert not os.path.exists(path)
    assert main(["run", str(tmp_path / "demo.py"), "--reload", "--port", "0"]) == 0
    assert seen[1][0] in (socket.AF_INET, socket.AF_INET6)
