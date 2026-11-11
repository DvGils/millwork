"""Files on a page: upload, cards, viewers, downloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal

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
    needs_session: ClassVar[bool] = True
    payloads: ClassVar[dict[str, str]] = {
        "on_upload": "the FileRefs",
        "on_reject": "{'name': filename, 'reason': why}",
    }
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

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            accept: list[str] | None = None,
            multiple: bool = False,
            max_files: int = 10,
            max_size_mb: int | None = None,
            label: str | None = None,
            description: str | None = None,
            dropzone: bool = True,
            disabled: bool = False,
            on_upload: Any = None,
            on_reject: Any = None,
        ) -> None: ...


class FileCard(Component):
    type: ClassVar[str] = "FileCard"
    payloads: ClassVar[dict[str, str]] = {
        "on_action": "the chosen action's id",
        "on_click": "None",
    }
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

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            file: FileRef | None = None,
            name: str | None = None,
            size: int | None = None,
            kind: str | None = None,
            url: str | None = None,
            status: Literal["ready", "loading", "error"] = "ready",
            meta: str | None = None,
            actions: list[MenuItem] = ...,
            on_action: Any = None,
            on_click: Any = None,
        ) -> None: ...


class Image(Component):
    type: ClassVar[str] = "Image"
    payloads: ClassVar[dict[str, str]] = {
        "on_click": "None",
    }
    src: FileRef | str
    alt: str = ""
    _src = field_validator("src")(staticmethod(_safe_src))
    size: Literal["sm", "md", "lg", "full"] = "md"
    fit: Literal["cover", "contain"] = "contain"
    on_click: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            src: FileRef | str,
            alt: str = "",
            size: Literal["sm", "md", "lg", "full"] = "md",
            fit: Literal["cover", "contain"] = "contain",
            on_click: Any = None,
        ) -> None: ...


class Pdf(Component):
    """A PDF in the browser's own viewer. A form or a link inside the document
    looks like part of the app, so show files the app made or the person
    uploaded themselves, not documents from strangers."""

    type: ClassVar[str] = "Pdf"
    src: FileRef | str
    page: int | None = None
    _src = field_validator("src")(staticmethod(_safe_src))
    height: str = "70vh"

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            src: FileRef | str,
            page: int | None = None,
            height: str = "70vh",
        ) -> None: ...


class Download(Component):
    """A button that downloads a file, bytes, text, or what a callable returns on click."""

    type: ClassVar[str] = "Download"
    needs_session: ClassVar[bool] = True
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"content"})
    theme_words: ClassVar[dict[str, str]] = {"label": "download"}

    label: str = "Download"
    filename: str
    content: Any
    mime: str | None = None
    variant: Literal["primary", "secondary", "outline", "ghost", "link"] = "outline"
    size: Literal["sm", "md", "lg"] = "md"
    icon: str | None = "download"
    disabled: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            label: str | None = None,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            filename: str,
            content: Any,
            mime: str | None = None,
            variant: Literal["primary", "secondary", "outline", "ghost", "link"] = "outline",
            size: Literal["sm", "md", "lg"] = "md",
            icon: str | None = "download",
            disabled: bool = False,
        ) -> None: ...
    else:

        def __init__(self, label: str | None = None, **props: Any) -> None:
            # Passed on only when given, so a label left out stays the
            # framework's word and follows the theme.
            if label is not None:
                props["label"] = label
            super().__init__(**props)

    def wire_extra(self) -> dict[str, Any]:
        # A session file downloads by id, straight over the socket: no click round
        # trip, no copy of the file.
        if isinstance(self.content, FileRef):
            from millwork import context

            s = context.current()
            if s is not None and s.id == self.content.session:
                return {"file_id": self.content.id}
        return {}
