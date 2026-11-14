"""The catalogue, as Python classes.

Every component is a Pydantic model whose props the bundle understands.
Stateful components take ``value`` (server-owned) or ``default``
(client-owned), never both; ``_owner`` enforces that.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from millwork.files import FileRef
from millwork.forms import FormIssues, Issue
from millwork.icons import check_icon
from millwork.nodes import Component, Lazy, Showing, Text, Tone, lazy
from millwork.ui.charts import AreaChart, BarChart, LineChart, PieChart
from millwork.ui.chat import Accept, Action, Chat, Command
from millwork.ui.files import Download, FileCard, FileUpload, Image, Pdf
from millwork.ui.form import Form
from millwork.ui.table import Column, MenuItem, Table

Variant = Literal["primary", "secondary", "outline", "ghost", "link", "destructive"]
Size = Literal["sm", "md", "lg"]
Align = Literal["start", "center", "end", "stretch", "baseline"]
Justify = Literal["start", "center", "end", "between", "around", "evenly"]


class Option(BaseModel):
    """One choice in a Select, RadioGroup, CheckboxGroup, ToggleGroup. An
    ``options`` list also takes plain strings, ``(value, label)`` pairs and dicts."""

    model_config = ConfigDict(extra="forbid")

    value: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    disabled: bool = False
    group: str | None = None

    @field_validator("icon")
    @classmethod
    def _known_icon(cls, name: str | None) -> str | None:
        return check_icon(name)


def as_options(values: Any) -> list[Option]:
    """Accept strings, ``(value, label)`` pairs, dicts or ``Option``s."""
    out: list[Option] = []
    for v in values or []:
        if isinstance(v, Option):
            out.append(v)
        elif isinstance(v, str):
            out.append(Option(value=v, label=v))
        elif isinstance(v, tuple | list) and len(v) == 2:
            out.append(Option(value=str(v[0]), label=str(v[1])))
        elif isinstance(v, dict):
            out.append(Option(**v))
        else:
            raise TypeError(f"not an option: {v!r}")
    return out


class _Owned(Component):
    """A component with interaction state and one owner."""

    owner_pairs: ClassVar[tuple[tuple[str, str], ...]] = (
        ("value", "default"),
        ("checked", "default_checked"),
        ("open", "default_open"),
    )

    @model_validator(mode="after")
    def _owner(self) -> _Owned:
        for server, client in self.owner_pairs:
            if server in self.model_fields_set and client in self.model_fields_set:
                raise ValueError(
                    f"{type(self).__name__} takes {server} (server-owned) or {client} "
                    "(client-owned), not both"
                )
        return self

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
        ) -> None: ...


# ------------------------------------------------------------------ layout


class Header(Component):
    """The app bar: the theme's logo, a title, links, the page's actions (children)
    and the user menu with the theme choice and sign-out."""

    type: ClassVar[str] = "Header"
    title: str | None = None
    logo: bool = True
    links: list[Link] = []
    user_menu: bool = True

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            title: str | None = None,
            logo: bool = True,
            links: list[Link] = ...,
            user_menu: bool = True,
        ) -> None: ...


class Logo(Component):
    """The theme's logo, the light or dark file with the scheme; nothing when the
    theme has none. For a page outside the app bar: a login-like page, an error page."""

    type: ClassVar[str] = "Logo"

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
        ) -> None: ...


class Page(Component):
    """The root of a page: a column of its children with ``gap`` between them,
    under a ``header``, beside a ``Sidebar`` child when there is one."""

    type: ClassVar[str] = "Page"
    title: str | None = None
    header: Header | None = None
    padding: bool = True
    gap: int = 6
    max_width: str | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            title: str | None = None,
            header: Header | None = None,
            padding: bool = True,
            gap: int = 6,
            max_width: str | None = None,
        ) -> None: ...


class Stack(Component):
    type: ClassVar[str] = "Stack"
    gap: int = 4
    align: Align = "stretch"
    justify: Justify = "start"
    grow: bool = False
    divided: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            gap: int = 4,
            align: Align = "stretch",
            justify: Justify = "start",
            grow: bool = False,
            divided: bool = False,
        ) -> None: ...


class Row(Component):
    type: ClassVar[str] = "Row"
    gap: int = 4
    align: Align = "center"
    justify: Justify = "start"
    wrap: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            gap: int = 4,
            align: Align = "center",
            justify: Justify = "start",
            wrap: bool = False,
        ) -> None: ...


class Grid(Component):
    """Children in columns. ``cols`` is a count from 1 to 12, or counts by
    width: ``sm`` is the count on the narrowest screens, and ``md``, ``lg`` and
    ``xl`` take over from 768, 1024 and 1280 pixels up."""

    type: ClassVar[str] = "Grid"
    cols: int | dict[Literal["sm", "md", "lg", "xl"], int] = 2
    gap: int = 4

    @field_validator("cols")
    @classmethod
    def _counts(cls, cols: int | dict[str, int]) -> int | dict[str, int]:
        for count in cols.values() if isinstance(cols, dict) else [cols]:
            if not 1 <= count <= 12:
                raise ValueError(f"a grid has 1 to 12 columns, not {count}")
        return cols

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            cols: int | dict[Literal["sm", "md", "lg", "xl"], int] = 2,
            gap: int = 4,
        ) -> None: ...


class Card(Component):
    type: ClassVar[str] = "Card"
    payloads: ClassVar[dict[str, str]] = {
        "on_click": "None",
    }
    title: str | None = None
    description: str | None = None
    footer: Component | None = None
    padding: bool = True
    tone: Tone | None = None
    on_click: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            title: str | None = None,
            description: str | None = None,
            footer: Component | None = None,
            padding: bool = True,
            tone: Tone | None = None,
            on_click: Any = None,
        ) -> None: ...


class Split(Component):
    """Resizable panes. Sizes are percentages; the user's drag is client-owned."""

    type: ClassVar[str] = "Split"
    sizes: list[int] | None = None
    min_sizes: list[int] | None = None
    direction: Literal["horizontal", "vertical"] = "horizontal"
    # True: every pane collapses when dragged under its minimum; a list says which.
    collapsible: bool | list[bool] = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            sizes: list[int] | None = None,
            min_sizes: list[int] | None = None,
            direction: Literal["horizontal", "vertical"] = "horizontal",
            collapsible: bool | list[bool] = False,
        ) -> None: ...


class Sidebar(_Owned):
    """A collapsible side panel. ``Page`` with a ``Sidebar`` child lays out around it."""

    type: ClassVar[str] = "Sidebar"
    payloads: ClassVar[dict[str, str]] = {
        "on_toggle": "True when open",
    }
    side: Literal["left", "right"] = "left"
    width: str | None = None
    collapsible: Literal["offcanvas", "icon", "none"] = "offcanvas"
    open: bool | None = None
    default_open: bool | None = None
    title: str | None = None
    on_toggle: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            side: Literal["left", "right"] = "left",
            width: str | None = None,
            collapsible: Literal["offcanvas", "icon", "none"] = "offcanvas",
            open: bool | None = None,
            default_open: bool | None = None,
            title: str | None = None,
            on_toggle: Any = None,
        ) -> None: ...


class Tabs(_Owned):
    type: ClassVar[str] = "Tabs"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the chosen tab's value",
    }
    value: str | None = None
    default: str | None = None
    variant: Literal["line", "pill"] = "line"
    on_change: Any = None

    shows_some: ClassVar[bool] = True

    @model_validator(mode="after")
    def _tabs_are_not_lazy(self) -> Tabs:
        if any(isinstance(child, Lazy) for child in self.children):
            raise ValueError(
                "a lazy part goes inside a ui.Tab, not in its place: the tabs are "
                "needed to tell which one is open"
            )
        return self

    def tab_ids(self) -> list[str]:
        return [c.id for c in self.children if isinstance(c, Tab)]

    def open_tabs(self) -> list[str]:
        """The ids of the tabs that can be chosen."""
        return [c.id for c in self.children if isinstance(c, Tab) and not c.disabled]

    def shown(self, told: str | None) -> str | None:
        """The id of the open tab. With ``value`` the page says which it is.
        Otherwise the browser does, and ``told`` is what it last said. Until
        it has spoken this is the tab it opens on: ``default``, or the
        first tab, and the first that can be chosen when that one is not
        among the tabs."""
        if "value" in self.model_fields_set:
            return self.value
        tabs = self.tab_ids()
        if told in tabs:
            return told
        first = self.default if self.default is not None else (tabs[0] if tabs else None)
        if first in tabs:
            return first
        return next(iter(self.open_tabs()), None)

    def showing(self, told: str | None) -> Showing:
        which = self.shown(told)
        return Showing(
            shows=lambda child: not isinstance(child, Tab) or child.id == which,
            asks="value" not in self.model_fields_set,
        )

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            value: str | None = None,
            default: str | None = None,
            variant: Literal["line", "pill"] = "line",
            on_change: Any = None,
        ) -> None: ...


class Tab(Component):
    type: ClassVar[str] = "Tab"
    id: str
    label: str
    icon: str | None = None
    badge: str | None = None
    disabled: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            id: str,
            label: str,
            icon: str | None = None,
            badge: str | None = None,
            disabled: bool = False,
        ) -> None: ...


class Accordion(_Owned):
    type: ClassVar[str] = "Accordion"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the open items' values",
    }
    multiple: bool = False
    value: list[str] | None = None
    default: list[str] | None = None
    on_change: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            multiple: bool = False,
            value: list[str] | None = None,
            default: list[str] | None = None,
            on_change: Any = None,
        ) -> None: ...


class AccordionItem(Component):
    type: ClassVar[str] = "AccordionItem"
    id: str
    title: str

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            id: str,
            title: str,
        ) -> None: ...


class SidebarGroup(_Owned):
    """A labeled group of links in a ``Sidebar``, folded to its label or open.
    The browser keeps whether it is open unless ``open`` is given, and
    ``collapsible=False`` makes it a plain heading over its links."""

    type: ClassVar[str] = "SidebarGroup"
    payloads: ClassVar[dict[str, str]] = {
        "on_toggle": "True when open",
    }
    label: str
    open: bool | None = None
    default_open: bool | None = None
    collapsible: bool = True
    on_toggle: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            label: str,
            open: bool | None = None,
            default_open: bool | None = None,
            collapsible: bool = True,
            on_toggle: Any = None,
        ) -> None: ...


class Floating(Component):
    """Children pinned over the page in a bottom corner, for a status chip or
    a panel that should stay at hand while the page scrolls. ``draggable``
    lets the reader move it where they want it and ``resizable`` lets them
    pull its edges, down to a small floor, and the browser remembers both
    for this component. It never leaves the browser window and shrinks to
    fit when the window does."""

    type: ClassVar[str] = "Floating"
    side: Literal["left", "right"] = "right"
    draggable: bool = False
    resizable: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            side: Literal["left", "right"] = "right",
            draggable: bool = False,
            resizable: bool = False,
        ) -> None: ...


class Assistant(_Owned):
    """A floating button that becomes a window. Minimized, it is a round
    button in a corner of the page that the reader can drag about. Opened,
    it is a window that grows from where the button is, holds a chat or
    anything else that should be at hand wherever the reader is, and is
    dragged by its header and resized from its edges, unless ``draggable``
    is off, which fixes both. Minimized again, it is the button where the
    button was, or at the window's near corner once the window has been
    moved. ``pinned`` keeps the button in its corner: it cannot be dragged,
    and the window always opens from there and folds back to it. The
    browser remembers where the button is and how big the window was. On a
    phone the window is a sheet. ``open`` makes Python the owner of whether
    it is open, with ``on_toggle`` reporting the clicks; otherwise the
    browser holds it, starting from ``default_open``."""

    type: ClassVar[str] = "Assistant"
    payloads: ClassVar[dict[str, str]] = {
        "on_toggle": "True when open",
    }
    label: str = "Assistant"
    title: str | None = None
    icon: str = "message-square"
    side: Literal["left", "right"] = "right"
    draggable: bool = True
    pinned: bool = False
    open: bool | None = None
    default_open: bool | None = None
    on_toggle: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            label: str = "Assistant",
            title: str | None = None,
            icon: str = "message-square",
            side: Literal["left", "right"] = "right",
            draggable: bool = True,
            pinned: bool = False,
            open: bool | None = None,
            default_open: bool | None = None,
            on_toggle: Any = None,
        ) -> None: ...


class Collapsible(_Owned):
    type: ClassVar[str] = "Collapsible"
    payloads: ClassVar[dict[str, str]] = {
        "on_toggle": "True when open",
    }
    title: str
    open: bool | None = None
    default_open: bool | None = None
    on_toggle: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            title: str,
            open: bool | None = None,
            default_open: bool | None = None,
            on_toggle: Any = None,
        ) -> None: ...


class Dialog(Component):
    """``open`` is always server-owned: a dialog is state the app reasons about."""

    type: ClassVar[str] = "Dialog"
    payloads: ClassVar[dict[str, str]] = {
        "on_close": "None",
    }
    open: bool = False
    title: str | None = None
    description: str | None = None
    footer: Component | None = None
    size: Literal["sm", "md", "lg", "xl", "full"] = "md"
    dismissable: bool = True
    on_close: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            open: bool = False,
            title: str | None = None,
            description: str | None = None,
            footer: Component | None = None,
            size: Literal["sm", "md", "lg", "xl", "full"] = "md",
            dismissable: bool = True,
            on_close: Any = None,
        ) -> None: ...


class Sheet(Component):
    type: ClassVar[str] = "Sheet"
    payloads: ClassVar[dict[str, str]] = {
        "on_close": "None",
    }
    open: bool = False
    side: Literal["left", "right", "top", "bottom"] = "right"
    # How wide a sheet at the left or right may get, on the Dialog's scale.
    size: Literal["sm", "md", "lg", "xl", "full"] = "sm"
    title: str | None = None
    description: str | None = None
    on_close: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            open: bool = False,
            side: Literal["left", "right", "top", "bottom"] = "right",
            size: Literal["sm", "md", "lg", "xl", "full"] = "sm",
            title: str | None = None,
            description: str | None = None,
            on_close: Any = None,
        ) -> None: ...


class ScrollArea(Component):
    type: ClassVar[str] = "ScrollArea"
    height: str | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            height: str | None = None,
        ) -> None: ...


class Separator(Component):
    type: ClassVar[str] = "Separator"
    orientation: Literal["horizontal", "vertical"] = "horizontal"
    label: str | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            orientation: Literal["horizontal", "vertical"] = "horizontal",
            label: str | None = None,
        ) -> None: ...


class Empty(Component):
    type: ClassVar[str] = "Empty"
    title: str
    description: str | None = None
    icon: str | None = None
    action: Component | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            title: str,
            description: str | None = None,
            icon: str | None = None,
            action: Component | None = None,
        ) -> None: ...


# ------------------------------------------------------------------ text


class Markdown(Component):
    type: ClassVar[str] = "Markdown"
    content: str = ""
    tight: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            content: str = "",
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            tight: bool = False,
        ) -> None: ...
    else:

        def __init__(self, content: str = "", **props: Any) -> None:
            super().__init__(content=content, **props)


class Code(Component):
    type: ClassVar[str] = "Code"
    content: str = ""
    language: str | None = None
    title: str | None = None
    copyable: bool = True
    wrap: bool = False
    max_height: str | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            content: str = "",
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            language: str | None = None,
            title: str | None = None,
            copyable: bool = True,
            wrap: bool = False,
            max_height: str | None = None,
        ) -> None: ...
    else:

        def __init__(self, content: str = "", **props: Any) -> None:
            super().__init__(content=content, **props)


class Badge(Component):
    type: ClassVar[str] = "Badge"
    label: str = ""
    tone: Tone = "default"
    icon: str | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            label: str = "",
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            tone: Tone = "default",
            icon: str | None = None,
        ) -> None: ...
    else:

        def __init__(self, label: str = "", **props: Any) -> None:
            super().__init__(label=label, **props)


class Icon(Component):
    """An icon on its own: one of the bundle's by name, or a file under
    ``public/`` by its path. ``label`` says what it means to someone who
    cannot see it. Without one it is decoration."""

    type: ClassVar[str] = "Icon"
    name: str
    size: Size = "md"
    tone: Tone = "default"
    label: str | None = None

    @field_validator("name")
    @classmethod
    def _an_icon(cls, name: str) -> str:
        if not name:
            raise ValueError("an icon needs a name, or the path of a file under /public/")
        check_icon(name)
        return name

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            name: str,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            size: Size = "md",
            tone: Tone = "default",
            label: str | None = None,
        ) -> None: ...
    else:

        def __init__(self, name: str, **props: Any) -> None:
            super().__init__(name=name, **props)


class Kbd(Component):
    type: ClassVar[str] = "Kbd"
    keys: list[str]

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            keys: list[str],
        ) -> None: ...


def safe_href(value: str) -> str:
    """Only http(s), mailto and same-origin paths: nothing a browser would execute."""
    v = value.strip()
    lower = v.lower()
    if v.startswith("/") and not v.startswith("//") and "\\" not in v:
        return v
    if lower.startswith(("http://", "https://", "mailto:")):
        return v
    raise ValueError(f"unsafe href {value!r}: use http(s), mailto or a path")


class Link(Component):
    type: ClassVar[str] = "Link"
    label: str
    href: str
    target: Literal["_self", "_blank"] = "_self"
    icon: str | None = None
    # The link to the page the session is on: ``aria-current="page"`` in the tab.
    active: bool = False

    _href = field_validator("href")(staticmethod(safe_href))

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            label: str,
            href: str,
            target: Literal["_self", "_blank"] = "_self",
            icon: str | None = None,
            active: bool = False,
        ) -> None: ...


Header.model_rebuild()


class Stat(Component):
    """A headline number. ``delta`` is the change, shown with its direction
    and coloured by whether up is ``good``; ``trend`` draws a sparkline."""

    type: ClassVar[str] = "Stat"
    label: str
    value: str
    hint: str | None = None
    tone: Tone | None = None
    icon: str | None = None
    delta: float | None = None
    delta_format: Literal["percent", "number"] = "percent"
    good: Literal["up", "down"] = "up"
    trend: list[float] | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            label: str,
            value: str,
            hint: str | None = None,
            tone: Tone | None = None,
            icon: str | None = None,
            delta: float | None = None,
            delta_format: Literal["percent", "number"] = "percent",
            good: Literal["up", "down"] = "up",
            trend: Iterable[float] | None = None,
        ) -> None: ...


class Alert(Component):
    type: ClassVar[str] = "Alert"
    payloads: ClassVar[dict[str, str]] = {
        "on_dismiss": "None",
    }
    title: str | None = None
    description: str | None = None
    tone: Tone = "default"
    icon: str | None = None
    dismissable: bool = False
    actions: list[Component] = []
    on_dismiss: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            title: str | None = None,
            description: str | None = None,
            tone: Tone = "default",
            icon: str | None = None,
            dismissable: bool = False,
            actions: list[Component] = ...,
            on_dismiss: Any = None,
        ) -> None: ...


# ------------------------------------------------------------------ inputs


class Button(Component):
    type: ClassVar[str] = "Button"
    payloads: ClassVar[dict[str, str]] = {
        "on_click": "None",
    }
    label: str = ""
    variant: Variant = "primary"
    size: Size = "md"
    icon: str | None = None
    icon_position: Literal["start", "end"] = "start"
    disabled: bool = False
    loading: bool = False
    tooltip: str | None = None
    # Asked before the handler runs; a cancelled question drops the click.
    confirm: str | None = None
    # The key of a Form on the page: the button submits it, from anywhere.
    form: str | None = None
    # Where the button goes: a page of the app, opened on the session like a
    # ``Link``, or any other address. A button with one is a link in the tab,
    # so it opens in a new tab on a middle click and can be copied.
    href: str | None = None
    target: Literal["_self", "_blank"] = "_self"
    on_click: Any = None

    _href = field_validator("href")(staticmethod(lambda v: v if v is None else safe_href(v)))

    @model_validator(mode="after")
    def _goes_or_acts(self) -> Button:
        if self.href is not None:
            for name in ("on_click", "confirm", "form"):
                if getattr(self, name):
                    raise ValueError(
                        f"a Button with href goes somewhere, so it takes no {name}; "
                        "navigate from the handler with s.navigate instead"
                    )
        return self

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            label: str = "",
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            variant: Variant = "primary",
            size: Size = "md",
            icon: str | None = None,
            icon_position: Literal["start", "end"] = "start",
            disabled: bool = False,
            loading: bool = False,
            tooltip: str | None = None,
            confirm: str | None = None,
            form: str | None = None,
            href: str | None = None,
            target: Literal["_self", "_blank"] = "_self",
            on_click: Any = None,
        ) -> None: ...
    else:

        def __init__(self, label: str = "", **props: Any) -> None:
            super().__init__(label=label, **props)


class ButtonGroup(Component):
    """Buttons joined into one control."""

    type: ClassVar[str] = "ButtonGroup"

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
        ) -> None: ...


class DropdownMenu(Component):
    """A menu behind a trigger button. ``on_select`` receives the item's id."""

    type: ClassVar[str] = "DropdownMenu"
    payloads: ClassVar[dict[str, str]] = {
        "on_select": "the chosen item's id",
    }
    trigger: Component
    items: list[MenuItem]
    align: Literal["start", "end"] = "start"
    on_select: Any = None

    @field_validator("trigger")
    @classmethod
    def _opens_the_menu(cls, trigger: Component) -> Component:
        if getattr(trigger, "href", None) is not None:
            raise ValueError("a DropdownMenu's trigger opens the menu, so it takes no href")
        return trigger

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            trigger: Component,
            items: list[MenuItem],
            align: Literal["start", "end"] = "start",
            on_select: Any = None,
        ) -> None: ...


class Field(Component):
    """A label, help text and an error around one control, for a form built by hand."""

    type: ClassVar[str] = "Field"
    label: str
    help: str | None = None
    error: str | None = None
    required: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            label: str,
            help: str | None = None,
            error: str | None = None,
            required: bool = False,
        ) -> None: ...


class ToggleGroup(_Owned):
    type: ClassVar[str] = "ToggleGroup"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the chosen value, a list when multiple",
    }
    options: list[Option]
    value: str | list[str] | None = None
    default: str | list[str] | None = None
    multiple: bool = False
    size: Size = "md"
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            options: Sequence[Option | str | tuple[str, str] | Mapping[str, Any]],
            value: str | list[str] | None = None,
            default: str | list[str] | None = None,
            multiple: bool = False,
            size: Size = "md",
            on_change: Any = None,
        ) -> None: ...


class Input(_Owned):
    type: ClassVar[str] = "Input"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the text",
        "on_submit": "the text, on Enter",
    }
    value: str | None = None
    default: str | None = None
    placeholder: str | None = None
    kind: Literal["text", "password", "email", "number", "search", "url"] = "text"
    prefix_icon: str | None = None
    suffix: str | None = None
    disabled: bool = False
    readonly: bool = False
    clearable: bool = False
    max_length: int | None = None
    counter: bool = False
    spellcheck: bool | None = None
    debounce_ms: int = 250
    clear_on_submit: bool = False
    on_change: Any = None
    on_submit: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            value: str | None = None,
            default: str | None = None,
            placeholder: str | None = None,
            kind: Literal["text", "password", "email", "number", "search", "url"] = "text",
            prefix_icon: str | None = None,
            suffix: str | None = None,
            disabled: bool = False,
            readonly: bool = False,
            clearable: bool = False,
            max_length: int | None = None,
            counter: bool = False,
            spellcheck: bool | None = None,
            debounce_ms: int = 250,
            clear_on_submit: bool = False,
            on_change: Any = None,
            on_submit: Any = None,
        ) -> None: ...


class Textarea(_Owned):
    type: ClassVar[str] = "Textarea"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the text",
        "on_submit": "the text, on Ctrl+Enter",
    }
    value: str | None = None
    default: str | None = None
    placeholder: str | None = None
    rows: int = 3
    autosize: bool = False
    max_length: int | None = None
    counter: bool = False
    spellcheck: bool | None = None
    disabled: bool = False
    readonly: bool = False
    debounce_ms: int = 250
    clear_on_submit: bool = False
    on_change: Any = None
    on_submit: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            value: str | None = None,
            default: str | None = None,
            placeholder: str | None = None,
            rows: int = 3,
            autosize: bool = False,
            max_length: int | None = None,
            counter: bool = False,
            spellcheck: bool | None = None,
            disabled: bool = False,
            readonly: bool = False,
            debounce_ms: int = 250,
            clear_on_submit: bool = False,
            on_change: Any = None,
            on_submit: Any = None,
        ) -> None: ...


class NumberInput(_Owned):
    type: ClassVar[str] = "NumberInput"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the number, or None when cleared",
    }
    value: float | None = None
    default: float | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    suffix: str | None = None
    placeholder: str | None = None
    disabled: bool = False
    on_change: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            value: float | None = None,
            default: float | None = None,
            min: float | None = None,
            max: float | None = None,
            step: float | None = None,
            suffix: str | None = None,
            placeholder: str | None = None,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class Combobox(_Owned):
    """A searchable single choice. ``options`` filters in the tab; ``on_search(query)``
    returns the options for what was typed, answered over the socket without a render.
    ``allow_custom`` adds a row that takes the text as typed, so the value can be
    something that is no option."""

    type: ClassVar[str] = "Combobox"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the chosen value, or None",
        "on_search": "the text typed; the handler returns the options to show",
    }
    options: list[Option] = []
    value: str | None = None
    default: str | None = None
    placeholder: str | None = None
    allow_custom: bool = False
    clearable: bool = False
    disabled: bool = False
    on_change: Any = None
    on_search: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            options: Sequence[Option | str | tuple[str, str] | Mapping[str, Any]] = ...,
            value: str | None = None,
            default: str | None = None,
            placeholder: str | None = None,
            allow_custom: bool = False,
            clearable: bool = False,
            disabled: bool = False,
            on_change: Any = None,
            on_search: Any = None,
        ) -> None: ...


class MultiSelect(_Owned):
    """Several choices from a list, shown as chips; typing filters the list."""

    type: ClassVar[str] = "MultiSelect"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the chosen values, in order",
    }
    options: list[Option]
    value: list[str] | None = None
    default: list[str] | None = None
    placeholder: str | None = None
    searchable: bool = True
    # At most this many chosen; None is no limit.
    max: int | None = None
    # The chips can be dragged into order, or moved with Alt and the arrow keys.
    sortable: bool = False
    disabled: bool = False
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            options: Sequence[Option | str | tuple[str, str] | Mapping[str, Any]],
            value: list[str] | None = None,
            default: list[str] | None = None,
            placeholder: str | None = None,
            searchable: bool = True,
            max: int | None = None,
            sortable: bool = False,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


def _iso_date(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_iso_date(v) for v in value]
    return value


class DatePicker(_Owned):
    """A date, or with ``range`` a ``[start, end]`` pair, as ISO strings (``date``
    objects are accepted and converted). ``min`` and ``max`` bound what can be picked."""

    type: ClassVar[str] = "DatePicker"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the ISO date, or [start, end] for a range, or None",
    }
    value: str | list[str | None] | None = None
    default: str | list[str | None] | None = None
    min: str | None = None
    max: str | None = None
    range: bool = False
    placeholder: str | None = None
    clearable: bool = False
    disabled: bool = False
    on_change: Any = None

    _dates = field_validator("value", "default", "min", "max", mode="before")(
        staticmethod(_iso_date)
    )

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            value: str | dt.date | list[str | dt.date | None] | None = None,
            default: str | dt.date | list[str | dt.date | None] | None = None,
            min: str | dt.date | None = None,
            max: str | dt.date | None = None,
            range: bool = False,
            placeholder: str | None = None,
            clearable: bool = False,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class Select(_Owned):
    type: ClassVar[str] = "Select"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the chosen value, or None",
    }
    options: list[Option]
    value: str | None = None
    default: str | None = None
    placeholder: str | None = None
    clearable: bool = False
    disabled: bool = False
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            options: Sequence[Option | str | tuple[str, str] | Mapping[str, Any]],
            value: str | None = None,
            default: str | None = None,
            placeholder: str | None = None,
            clearable: bool = False,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class Checkbox(_Owned):
    type: ClassVar[str] = "Checkbox"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "True when checked",
    }
    label: str | None = None
    description: str | None = None
    checked: bool | None = None
    default_checked: bool | None = None
    disabled: bool = False
    on_change: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            label: str | None = None,
            description: str | None = None,
            checked: bool | None = None,
            default_checked: bool | None = None,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class CheckboxGroup(_Owned):
    type: ClassVar[str] = "CheckboxGroup"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the checked values",
    }
    options: list[Option]
    value: list[str] | None = None
    default: list[str] | None = None
    label: str | None = None
    disabled: bool = False
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            options: Sequence[Option | str | tuple[str, str] | Mapping[str, Any]],
            value: list[str] | None = None,
            default: list[str] | None = None,
            label: str | None = None,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class RadioGroup(_Owned):
    type: ClassVar[str] = "RadioGroup"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the chosen value",
    }
    options: list[Option]
    value: str | None = None
    default: str | None = None
    label: str | None = None
    orientation: Literal["vertical", "horizontal"] = "vertical"
    disabled: bool = False
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            options: Sequence[Option | str | tuple[str, str] | Mapping[str, Any]],
            value: str | None = None,
            default: str | None = None,
            label: str | None = None,
            orientation: Literal["vertical", "horizontal"] = "vertical",
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class Switch(_Owned):
    type: ClassVar[str] = "Switch"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "True when on",
    }
    label: str | None = None
    description: str | None = None
    checked: bool | None = None
    default_checked: bool | None = None
    disabled: bool = False
    on_change: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            label: str | None = None,
            description: str | None = None,
            checked: bool | None = None,
            default_checked: bool | None = None,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class Slider(_Owned):
    type: ClassVar[str] = "Slider"
    payloads: ClassVar[dict[str, str]] = {
        "on_change": "the number",
    }
    min: float = 0
    max: float = 100
    step: float = 1
    value: float | None = None
    default: float | None = None
    show_value: bool = True
    # Labelled points under the track: values, or value to label.
    marks: list[float] | dict[float, str] | None = None
    disabled: bool = False
    on_change: Any = None

    def wire_extra(self) -> dict[str, Any]:
        if self.marks is None:
            return {}
        if isinstance(self.marks, dict):
            return {"marks": [{"value": v, "label": label} for v, label in self.marks.items()]}
        return {"marks": [{"value": v, "label": None} for v in self.marks]}

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            min: float = 0,
            max: float = 100,
            step: float = 1,
            value: float | None = None,
            default: float | None = None,
            show_value: bool = True,
            marks: list[float] | dict[float, str] | None = None,
            disabled: bool = False,
            on_change: Any = None,
        ) -> None: ...


class Tooltip(Component):
    type: ClassVar[str] = "Tooltip"
    content: str

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            content: str,
        ) -> None: ...


_OWN_NAMES = frozenset({"key", "cls", "hidden", "on_event"})


class Custom(Component):
    """An app's own component: ``components/<name>.jsx``, compiled in the tab.

    ``props`` arrive as React props next to ``emit`` and ``children``; events
    the component emits reach ``on_event`` as ``(session, (name, payload))``,
    or a handler per event name through ``events``. ``cls`` and ``hidden``
    are applied around the component, as for any other, so a prop may not
    be named after them, nor ``key`` or ``on_event``.
    """

    type: ClassVar[str] = "Custom"
    payloads: ClassVar[dict[str, str]] = {
        "on_event": "(name, payload) as the component emitted it",
    }
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"name", "props", "events"})

    name: str
    props: dict[str, Any] = {}
    events: dict[str, Any] = {}
    on_event: Any = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            name: str,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            props: dict[str, Any] = ...,
            events: dict[str, Any] = ...,
            on_event: Any = None,
        ) -> None: ...
    else:

        def __init__(self, name: str, *children: Any, **kw: Any) -> None:
            taken = set(kw.get("props") or ()) & _OWN_NAMES
            if taken:
                raise ValueError(
                    f"a prop of Custom({name!r}) is named {sorted(taken)!r}, which is the "
                    "component's own; give it another name"
                )
            super().__init__(*children, name=name, **kw)

    def wire_type(self) -> str:
        return self.name

    def wire_extra(self) -> dict[str, Any]:
        return dict(self.props)


# ------------------------------------------------------------------ data


class Progress(Component):
    """A bar; with ``task`` the value, label and message come from the task."""

    type: ClassVar[str] = "Progress"
    value: float | None = None
    label: str | None = None
    description: str | None = None
    task: Any = None
    percent: bool = True
    """Whether the value is written out next to the bar. Off, the bar is a
    plain meter."""

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            value: float | None = None,
            label: str | None = None,
            description: str | None = None,
            task: Any = None,
            percent: bool = True,
        ) -> None: ...


class Steps(Component):
    """A step tree on Trace: the task's steps, or ``items`` given directly."""

    type: ClassVar[str] = "Steps"
    items: list[Any] | None = None
    task: Any = None
    compact: bool = False

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            items: list[Any] | None = None,
            task: Any = None,
            compact: bool = False,
        ) -> None: ...


class SignIn(Component):
    """One way to sign in, put where the page wants it. ``provider`` is the id
    of one of the app's auth providers: an OAuth provider is drawn as its
    button, and ``"password"`` as the username and password form. ``intent``
    makes it the button for one of ``Auth(intents=)``, which names its
    provider when the app has more than one, and ``label`` replaces the
    words on the button. It is what ``Auth(login=)`` lays the login page
    out with, and it works on a public page of the app as well."""

    type: ClassVar[str] = "SignIn"
    provider: str
    intent: str | None = None
    label: str | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            provider: str,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            intent: str | None = None,
            label: str | None = None,
        ) -> None: ...
    else:

        def __init__(self, provider: str, **props: Any) -> None:
            super().__init__(provider=provider, **props)

    def wire_extra(self) -> dict[str, Any]:
        from millwork import context

        auth = context.auth()
        if auth is None:
            raise ValueError("ui.SignIn needs an app with auth")
        provider = auth.providers.get(self.provider)
        if provider is None or provider.kind not in ("oauth", "password"):
            offered = sorted(
                p.id for p in auth.providers.values() if p.kind in ("oauth", "password")
            )
            raise ValueError(
                f"ui.SignIn({self.provider!r}) names no provider with a sign-in of its own; "
                f"the app has {', '.join(offered) or 'none'}"
            )
        label = self.label
        # An intent's own words say nothing of the provider. Where there is
        # more than one to go through, the button names the one it is for.
        with_provider = False
        if self.intent is not None:
            if provider.kind != "oauth":
                raise ValueError(
                    "an intent goes with an OAuth provider, not with the password form"
                )
            if self.intent not in auth.intents:
                raise ValueError(
                    f"ui.SignIn(intent={self.intent!r}) is not one of Auth(intents=): "
                    f"{', '.join(sorted(auth.intents)) or 'none'}"
                )
            if not label:
                label = auth.intents[self.intent]
                with_provider = sum(p.kind == "oauth" for p in auth.providers.values()) > 1
        return {
            "kind": provider.kind,
            "name": provider.label,
            "icon": provider.icon,
            "label": label,
            "with_provider": with_provider,
        }


class Skeleton(Component):
    type: ClassVar[str] = "Skeleton"
    rows: int = 3
    shape: Literal["text", "card", "table"] = "text"

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            rows: int = 3,
            shape: Literal["text", "card", "table"] = "text",
        ) -> None: ...


class Spinner(Component):
    type: ClassVar[str] = "Spinner"
    size: Size = "md"
    label: str | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            size: Size = "md",
            label: str | None = None,
        ) -> None: ...


__all__ = [
    "Accept",
    "Action",
    "Accordion",
    "AccordionItem",
    "Alert",
    "Assistant",
    "AreaChart",
    "BarChart",
    "PieChart",
    "Badge",
    "Button",
    "Card",
    "Column",
    "Chat",
    "Checkbox",
    "Code",
    "CheckboxGroup",
    "Collapsible",
    "Combobox",
    "Command",
    "Custom",
    "Component",
    "Dialog",
    "Download",
    "FileCard",
    "FileRef",
    "FileUpload",
    "Floating",
    "Empty",
    "Form",
    "FormIssues",
    "Grid",
    "Header",
    "Icon",
    "Image",
    "Input",
    "Issue",
    "Kbd",
    "LineChart",
    "Link",
    "Markdown",
    "MenuItem",
    "NumberInput",
    "Option",
    "Page",
    "Pdf",
    "Progress",
    "RadioGroup",
    "Row",
    "ScrollArea",
    "Select",
    "Field",
    "DropdownMenu",
    "ButtonGroup",
    "DatePicker",
    "MultiSelect",
    "Separator",
    "Sheet",
    "Sidebar",
    "SidebarGroup",
    "SignIn",
    "Skeleton",
    "Slider",
    "Spinner",
    "Split",
    "Stack",
    "Stat",
    "Steps",
    "Switch",
    "Tab",
    "Table",
    "Tabs",
    "Text",
    "Logo",
    "Textarea",
    "ToggleGroup",
    "Tone",
    "Tooltip",
    "as_options",
    "lazy",
]
