"""Files: uploads streamed into a per-session directory, fetched over the socket.

A ``FileRef`` is what an upload becomes and what a page
shows; on the wire it carries the id, name, size and type, never the path. The
bytes travel over the session's own socket, so a file has no URL.
"""

from __future__ import annotations

import codecs
import contextlib
import logging
import mimetypes
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from millwork.session import Session

log = logging.getLogger("millwork.files")


# Served inline (the browser may render it); everything else is an attachment.


class FileRef(BaseModel):
    """A file the session holds. ``path`` stays on the server."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    size: int
    mime: str
    path: Path = Field(exclude=True)
    session: str = Field(exclude=True)
    node: str | None = Field(default=None, exclude=True)

    def __millwork_wire__(self) -> dict[str, Any]:
        # The tab fetches the bytes over its socket by id; a file has no URL.
        return self.model_dump(mode="json")

    @property
    def kind(self) -> str:
        major = self.mime.split("/")[0]
        if major in ("image", "audio", "video"):
            return major
        if self.mime == "application/pdf":
            return "pdf"
        if major == "text" or self.mime in ("application/json",):
            return "text"
        return "file"


class Reject(Exception):
    """An upload refused, with the reason. ``key`` names the theme string that
    says it to the person, filled with ``vars``; without one, as for a
    refusal of the app's own, the reason itself is what they read."""

    def __init__(
        self,
        reason: str,
        status: int = 400,
        *,
        key: str | None = None,
        vars: Mapping[str, Any] | None = None,
    ) -> None:
        self.reason = reason
        self.status = status
        self.key = key
        self.vars = dict(vars or {})
        super().__init__(reason)


def fits(size: int, max_bytes: int) -> None:
    """Refuse a file that says it is larger than an upload may be."""
    if size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise Reject(f"the file is larger than {mb} MB", key="file_too_large", vars={"mb": mb})


# Magic bytes for the formats worth checking; anything else is accepted by extension.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
    "zip": (b"PK\x03\x04",),
    "docx": (b"PK\x03\x04",),
    "xlsx": (b"PK\x03\x04",),
    "pptx": (b"PK\x03\x04",),
}
_TEXT = {"txt", "md", "csv", "tsv", "json", "xml", "yaml", "yml", "html", "py"}

_SAFE_NAME = re.compile(r"[^\w.\- ()\[\]]+")
# Device names Windows refuses as file names, whatever the extension.
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def safe_name(name: str) -> str:
    base = Path(name).name or "file"
    # A trailing dot or space is dropped by Windows, so the name would differ.
    cleaned = _SAFE_NAME.sub("_", base).rstrip(". ") or "file"
    if cleaned.split(".", 1)[0].upper() in _RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) <= 200:
        return cleaned
    # A long name is cut in the stem, never in the extension: the extension
    # decides the content check, the accept list and the MIME type.
    suffix = Path(cleaned).suffix[:20]
    return cleaned[: 200 - len(suffix)] + suffix


def check_content(name: str, head: bytes) -> None:
    ext = Path(name).suffix.lower().lstrip(".")
    if not head:
        raise Reject("the file is empty", key="file_empty")
    if ext in _MAGIC:
        if not any(head.startswith(m) for m in _MAGIC[ext]):
            raise Reject(f"the file is not a valid .{ext}", key="file_not_valid", vars={"ext": ext})
        if ext == "webp" and b"WEBP" not in head[:16]:
            raise Reject(
                "the file is not a valid .webp", key="file_not_valid", vars={"ext": "webp"}
            )
    elif ext in _TEXT:
        # The head may end inside a multibyte character: only invalid bytes count.
        try:
            codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
        except UnicodeDecodeError as exc:
            raise Reject("the file is not UTF-8 text", key="file_not_text") from exc


def _owner() -> str:
    """What tells one user's store from another's in a shared temp directory."""
    if hasattr(os, "getuid"):
        return str(os.getuid())
    import getpass

    return _SAFE_NAME.sub("_", getpass.getuser())


class Files:
    """Configuration and the store. One per app."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        max_session_mb: int = 200,
        default_max_mb: int = 50,
        max_total_mb: int = 2000,
    ) -> None:
        self.root = (
            Path(root) if root else Path(tempfile.gettempdir()) / f"millwork-files-{_owner()}"
        )
        self.max_session_mb = max_session_mb
        self.max_total_mb = max_total_mb
        self.max_session_bytes = max_session_mb * 1024 * 1024
        self.default_max_bytes = default_max_mb * 1024 * 1024
        self.max_total_bytes = max_total_mb * 1024 * 1024
        # Bytes on disk per session, counted as they are written so that uploads
        # in flight hold their space against both quotas. Writers run in worker
        # threads, so the check and the count move together under one lock.
        self._usage: dict[str, int] = {}
        self._lock = threading.Lock()

    def used(self, session_id: str | None = None) -> int:
        """Bytes held by one session, or by every session together."""
        with self._lock:
            if session_id is not None:
                return self._usage.get(session_id, 0)
            return sum(self._usage.values())

    def _take(self, session: Session[Any], size: int) -> None:
        """Hold ``size`` more bytes for the session, or refuse: against its quota,
        the process's, and a session that has closed meanwhile (its space is gone)."""
        with self._lock:
            if session.closed:
                raise Reject("the session closed", 410)
            held = self._usage.get(session.id, 0)
            if held + size > self.max_session_bytes:
                raise Reject("the session's file quota is used up", 413, key="file_quota")
            if sum(self._usage.values()) + size > self.max_total_bytes:
                raise Reject("the server's file space is used up", 507, key="file_space")
            self._usage[session.id] = held + size

    def _release(self, session_id: str, size: int) -> None:
        with self._lock:
            left = self._usage.get(session_id, 0) - size
            if left > 0:
                self._usage[session_id] = left
            else:
                self._usage.pop(session_id, None)

    # ------------------------------------------------------------- directories

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def _ensure_root(self) -> None:
        """The root is ours alone: created private, and never a path someone else owns.

        Windows has no file mode or owner id to check; its temp directory is
        per user already, and a root given explicitly is the app's own."""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not hasattr(os, "getuid"):
            return
        st = self.root.stat()
        if st.st_uid != os.getuid():
            raise RuntimeError(f"files root {self.root} is owned by another user")
        if st.st_mode & 0o077:
            os.chmod(self.root, 0o700)

    def discard(self, session_id: str) -> None:
        with self._lock:
            self._usage.pop(session_id, None)
        shutil.rmtree(self.session_dir(session_id), ignore_errors=True)

    def sweep(self, older_than: float) -> int:
        """Remove session directories untouched for ``older_than`` seconds. Startup only."""
        if not self.root.is_dir():
            return 0
        cutoff = time.time() - older_than
        removed = 0
        for d in self.root.iterdir():
            try:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed

    # ------------------------------------------------------------- storing

    def store(
        self,
        session: Session[Any],
        name: str,
        chunks: Iterable[bytes],
        *,
        mime: str | None = None,
        max_bytes: int | None = None,
        accept: list[str] | None = None,
        check: bool = True,
        node: str | None = None,
    ) -> FileRef:
        """Write a file into the session's directory from an iterable of chunks."""
        writer = self.begin(
            session, name, mime=mime, max_bytes=max_bytes, accept=accept, check=check, node=node
        )
        try:
            for chunk in chunks:
                writer.write(chunk)
            return writer.finish()
        except BaseException:
            writer.abort()
            raise

    def begin(
        self,
        session: Session[Any],
        name: str,
        *,
        mime: str | None = None,
        max_bytes: int | None = None,
        accept: list[str] | None = None,
        check: bool = True,
        node: str | None = None,
    ) -> FileWriter:
        """Start a file in the session's directory; ``write`` chunks, then ``finish``.

        The extension is checked here, the size, the quota and the content as the
        chunks come. ``mime`` is only used when the extension says nothing; what a
        browser declares is never trusted.
        """
        name = safe_name(name)
        ext = Path(name).suffix.lower()
        if accept:
            allowed = {a.lower() if a.startswith(".") else "." + a.lower() for a in accept}
            if ext not in allowed:
                expected = ", ".join(sorted(allowed))
                raise Reject(
                    f"{ext or 'this type'} is not accepted; expected {expected}",
                    key="file_not_accepted",
                    vars={"expected": expected},
                )
        file_id = secrets.token_urlsafe(12)
        self._ensure_root()
        directory = self.session_dir(session.id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return FileWriter(
            self,
            session,
            file_id=file_id,
            name=name,
            path=directory / f"{file_id}{ext}",
            mime=mime,
            limit=max_bytes or self.default_max_bytes,
            check=check,
            node=node,
        )


class FileWriter:
    """One file being written: validates as it goes, registers on ``finish``.

    ``write`` and ``finish`` are plain blocking calls, short enough for a thread
    per chunk; nothing waits inside them.
    """

    def __init__(
        self,
        files: Files,
        session: Session[Any],
        *,
        file_id: str,
        name: str,
        path: Path,
        mime: str | None,
        limit: int,
        check: bool,
        node: str | None,
    ) -> None:
        self._files = files
        self._session = session
        self.id = file_id
        self.name = name
        self.path = path
        self._mime = mime
        self._limit = limit
        self._node = node
        self._size = 0
        # Bytes counted against the quotas so far: exactly what abort gives back.
        self._reserved = 0
        self._head = b""
        self._checked = not check
        # Writes and the finish run in a thread, the abort on the loop: one
        # at a time, so an abort cannot pull the file from under a write.
        self._lock = threading.Lock()
        self.ref: FileRef | None = None
        """The file, once finished."""
        self._fh: Any = path.open("wb")
        self._done = False

    def write(self, chunk: bytes) -> None:
        with self._lock:
            self._write(chunk)

    def _write(self, chunk: bytes) -> None:
        if self._done:
            raise Reject("the upload is over")
        if not chunk:
            return
        try:
            if len(self._head) < 64:
                self._head += chunk[: 64 - len(self._head)]
            if self._size + len(chunk) > self._limit:
                mb = self._limit // (1024 * 1024)
                raise Reject(
                    f"the file is larger than {mb} MB", 413, key="file_too_large", vars={"mb": mb}
                )
            self._files._take(self._session, len(chunk))
            self._reserved += len(chunk)
            self._size += len(chunk)
            if not self._checked and len(self._head) >= 16:
                # Enough bytes to know the format: reject before the rest streams in.
                check_content(self.name, self._head)
                self._checked = True
            self._fh.write(chunk)
        except BaseException:
            self._abort()
            raise

    def finish(self) -> FileRef:
        with self._lock:
            return self._finish()

    def _finish(self) -> FileRef:
        if self._done:
            raise Reject("the upload is over")
        try:
            if not self._checked:
                check_content(self.name, self._head)
            self._fh.close()
        except BaseException:
            self._abort()
            raise
        self._done = True
        guessed = mimetypes.guess_type(self.name)[0]
        ref = FileRef(
            id=self.id,
            name=self.name,
            size=self._size,
            mime=guessed or self._mime or "application/octet-stream",
            path=self.path,
            session=self._session.id,
            node=self._node,
        )
        self._session.files.register(ref)
        self.ref = ref
        return ref

    def abort(self) -> None:
        """Nothing half-written is left behind. Safe to call more than once."""
        with self._lock:
            self._abort()

    def _abort(self) -> None:
        if self._done:
            return
        self._done = True
        self._files._release(self._session.id, self._reserved)
        self._reserved = 0
        with contextlib.suppress(Exception):
            self._fh.close()
        self.path.unlink(missing_ok=True)


class SessionFiles:
    """The files one session holds."""

    def __init__(self, session: Session[Any]) -> None:
        self._session = session
        self._refs: dict[str, FileRef] = {}

    def register(self, ref: FileRef) -> None:
        self._refs[ref.id] = ref

    def get(self, file_id: str) -> FileRef | None:
        return self._refs.get(file_id)

    def all(self) -> list[FileRef]:
        return list(self._refs.values())

    def remove(self, file_id: str) -> bool:
        """Forget a file and delete it from disk; its quota is freed. False if unknown."""
        ref = self._refs.pop(file_id, None)
        if ref is None:
            return False
        self._session.app.files._release(ref.session, ref.size)
        ref.path.unlink(missing_ok=True)
        return True

    def add(self, content: bytes | str | Path, *, name: str, mime: str | None = None) -> FileRef:
        """Make a session file from server-side data or an existing path."""
        if isinstance(content, Path):
            data: Iterable[bytes] = _read_chunks(content)
        elif isinstance(content, str):
            data = [content.encode("utf-8")]
        else:
            data = [content]
        files = self._session.app.files
        return files.store(
            self._session, name, data, mime=mime, max_bytes=files.max_session_bytes, check=False
        )


def _read_chunks(path: Path, size: int = 1 << 16) -> Iterable[bytes]:
    with path.open("rb") as fh:
        while chunk := fh.read(size):
            yield chunk


def content_to_file(session: Session[Any], content: Any, name: str, mime: str | None) -> FileRef:
    """What ``Download`` and ``s.download`` accept: a FileRef, bytes, text or a callable."""
    if callable(content):
        content = content()
    if isinstance(content, FileRef):
        return content
    if isinstance(content, bytes | bytearray):
        return session.files.add(bytes(content), name=name, mime=mime)
    if isinstance(content, str):
        return session.files.add(content, name=name, mime=mime or "text/plain")
    if isinstance(content, Path):
        return session.files.add(content, name=name, mime=mime)
    raise TypeError(f"cannot download a {type(content).__name__}")
