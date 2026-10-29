"""Files on a page: upload, cards, viewers, downloads."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import field_validator

from millwork.files import FileRef
from millwork.nodes import Component
from millwork.ui.table import MenuItem


def _safe_src(value: Any) -> Any:
    if isinstance(value, str):
        from millwork.ui import safe_href

        return safe_href(value)
    return value


class FileUpload(Component):
    """Uploads go over the session's socket; the handler receives ``FileRef``s."""

    type: ClassVar[str] = "FileUpload"
    accept: list[str] | None = None
    multiple: bool = False
    max_files: int = 10
    max_size_mb: int | None = None
    label: str | None = None
    description: str | None = None
    dropzone: bool = True
    disabled: bool = False
    on_upload: Any = None
    on_reject: Any = None


class FileCard(Component):
    type: ClassVar[str] = "FileCard"
    file: FileRef | None = None
    name: str | None = None
    size: int | None = None
    kind: str | None = None
    url: str | None = None
    status: Literal["ready", "loading", "error"] = "ready"
    _url = field_validator("url")(staticmethod(_safe_src))
    meta: str | None = None
    actions: list[MenuItem] = []
    on_action: Any = None
    on_click: Any = None


class Image(Component):
    type: ClassVar[str] = "Image"
    src: FileRef | str
    alt: str = ""
    _src = field_validator("src")(staticmethod(_safe_src))
    size: Literal["sm", "md", "lg", "full"] = "md"
    fit: Literal["cover", "contain"] = "contain"
    on_click: Any = None


class Pdf(Component):
    type: ClassVar[str] = "Pdf"
    src: FileRef | str
    page: int | None = None
    _src = field_validator("src")(staticmethod(_safe_src))
    height: str = "70vh"


class Download(Component):
    """A button that downloads a file, bytes, text, or what a callable returns on click."""

    type: ClassVar[str] = "Download"
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"content"})

    label: str = "Download"
    filename: str
    content: Any
    mime: str | None = None
    variant: Literal["primary", "secondary", "outline", "ghost", "link"] = "outline"
    icon: str | None = "download"
    disabled: bool = False

    def __init__(self, label: str = "Download", **props: Any) -> None:
        super().__init__(label=label, **props)

    def wire_extra(self) -> dict[str, Any]:
        # A session file downloads by id, straight over the socket: no click round
        # trip, no copy of the file.
        if isinstance(self.content, FileRef):
            from millwork import context

            s = context.current()
            if s is not None and s.id == self.content.session:
                return {"file_id": self.content.id}
        return {}
