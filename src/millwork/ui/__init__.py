"""The catalogue, as Python classes.

Every component is a Pydantic model whose props the bundle understands.
Stateful components take ``value`` (server-owned) or ``default``
(client-owned), never both; ``_owner`` enforces that.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from millwork.files import FileRef
from millwork.forms import FormIssues, Issue
from millwork.icons import check_icon
from millwork.nodes import Component, Text
from millwork.ui.charts import AreaChart, BarChart, LineChart, PieChart
from millwork.ui.chat import Accept, Action, Chat, Command
from millwork.ui.files import Download, FileCard, FileUpload, Image, Pdf
from millwork.ui.form import Form
from millwork.ui.table import Column, MenuItem, Table

Tone = Literal["default", "muted", "primary", "accent", "success", "warning", "destructive"]
Variant = Literal["primary", "secondary", "outline", "ghost", "link", "destructive"]
Size = Literal["sm", "md", "lg"]
Align = Literal["start", "center", "end", "stretch", "baseline"]
Justify = Literal["start", "center", "end", "between", "around", "evenly"]


class Option(BaseModel):
    """One choice in a Select, RadioGroup, CheckboxGroup, ToggleGroup."""

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


# ------------------------------------------------------------------ layout


class Header(Component):
    """The app bar: the theme's logo, a title, links, the page's actions (children)
    and the user menu with the theme choice and sign-out."""

    type: ClassVar[str] = "Header"
    title: str | None = None
    logo: bool = True
    links: list[Link] = []
    user_menu: bool = True


class Logo(Component):
    """The theme's logo, the light or dark file with the scheme; nothing when the
    theme has none. For a page outside the app bar: a login-like page, an error page."""

    type: ClassVar[str] = "Logo"


class Page(Component):
    type: ClassVar[str] = "Page"
    title: str | None = None
    header: Header | None = None
    padding: bool = True
    max_width: str | None = None


class Stack(Component):
    type: ClassVar[str] = "Stack"
    gap: int = 4
    align: Align = "stretch"
    justify: Justify = "start"
    grow: bool = False
    divided: bool = False


class Row(Component):
    type: ClassVar[str] = "Row"
    gap: int = 4
    align: Align = "center"
    justify: Justify = "start"
    wrap: bool = False


class Grid(Component):
    type: ClassVar[str] = "Grid"
    cols: int | dict[str, int] = 2
    gap: int = 4


class Card(Component):
    type: ClassVar[str] = "Card"
    title: str | None = None
    description: str | None = None
    footer: Component | None = None
    padding: bool = True
    tone: Tone | None = None
    on_click: Any = None


class Split(Component):
    """Resizable panes. Sizes are percentages; the user's drag is client-owned."""

    type: ClassVar[str] = "Split"
    sizes: list[int] | None = None
    min_sizes: list[int] | None = None
    direction: Literal["horizontal", "vertical"] = "horizontal"
    # True: every pane collapses when dragged under its minimum; a list says which.
    collapsible: bool | list[bool] = False


class Sidebar(_Owned):
    """A collapsible side panel. ``Page`` with a ``Sidebar`` child lays out around it."""

    type: ClassVar[str] = "Sidebar"
    side: Literal["left", "right"] = "left"
    width: str | None = None
    collapsible: Literal["offcanvas", "icon", "none"] = "offcanvas"
    open: bool | None = None
    default_open: bool | None = None
    title: str | None = None
    on_toggle: Any = None


class Tabs(_Owned):
    type: ClassVar[str] = "Tabs"
    value: str | None = None
    default: str | None = None
    variant: Literal["line", "pill"] = "line"
    on_change: Any = None


class Tab(Component):
    type: ClassVar[str] = "Tab"
    id: str
    label: str
    icon: str | None = None
    badge: str | None = None
    disabled: bool = False


class Accordion(_Owned):
    type: ClassVar[str] = "Accordion"
    multiple: bool = False
    value: list[str] | None = None
    default: list[str] | None = None
    on_change: Any = None


class AccordionItem(Component):
    type: ClassVar[str] = "AccordionItem"
    id: str
    title: str


class Collapsible(_Owned):
    type: ClassVar[str] = "Collapsible"
    title: str
    open: bool | None = None
    default_open: bool | None = None
    on_toggle: Any = None


class Dialog(Component):
    """``open`` is always server-owned: a dialog is state the app reasons about."""

    type: ClassVar[str] = "Dialog"
    open: bool = False
    title: str | None = None
    description: str | None = None
    footer: Component | None = None
    size: Literal["sm", "md", "lg", "xl", "full"] = "md"
    dismissable: bool = True
    on_close: Any = None


class Sheet(Component):
    type: ClassVar[str] = "Sheet"
    open: bool = False
    side: Literal["left", "right", "top", "bottom"] = "right"
    title: str | None = None
    description: str | None = None
    on_close: Any = None


class ScrollArea(Component):
    type: ClassVar[str] = "ScrollArea"
    height: str | None = None


class Separator(Component):
    type: ClassVar[str] = "Separator"
    orientation: Literal["horizontal", "vertical"] = "horizontal"
    label: str | None = None


class Empty(Component):
    type: ClassVar[str] = "Empty"
    title: str
    description: str | None = None
    icon: str | None = None
    action: Component | None = None


# ------------------------------------------------------------------ text


class Markdown(Component):
    type: ClassVar[str] = "Markdown"
    content: str = ""
    tight: bool = False

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

    def __init__(self, content: str = "", **props: Any) -> None:
        super().__init__(content=content, **props)


class Badge(Component):
    type: ClassVar[str] = "Badge"
    label: str = ""
    tone: Tone = "default"
    icon: str | None = None

    def __init__(self, label: str = "", **props: Any) -> None:
        super().__init__(label=label, **props)


class Kbd(Component):
    type: ClassVar[str] = "Kbd"
    keys: list[str]


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

    _href = field_validator("href")(staticmethod(safe_href))


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


class Alert(Component):
    type: ClassVar[str] = "Alert"
    title: str | None = None
    description: str | None = None
    tone: Tone = "default"
    icon: str | None = None
    dismissable: bool = False
    actions: list[Component] = []
    on_dismiss: Any = None


# ------------------------------------------------------------------ inputs


class Button(Component):
    type: ClassVar[str] = "Button"
    label: str = ""
    variant: Variant = "primary"
    size: Size = "md"
    icon: str | None = None
    icon_position: Literal["start", "end"] = "start"
    disabled: bool = False
    loading: bool = False
    tooltip: str | None = None
    confirm: str | None = None
    # The key of a Form on the page: the button submits it, from anywhere.
    form: str | None = None
    on_click: Any = None

    def __init__(self, label: str = "", **props: Any) -> None:
        super().__init__(label=label, **props)


class ButtonGroup(Component):
    """Buttons joined into one control."""

    type: ClassVar[str] = "ButtonGroup"


class DropdownMenu(Component):
    """A menu behind a trigger button. ``on_select`` receives the item's id."""

    type: ClassVar[str] = "DropdownMenu"
    trigger: Component
    items: list[MenuItem]
    align: Literal["start", "end"] = "start"
    on_select: Any = None


class Field(Component):
    """A label, help text and an error around one control, for a form built by hand."""

    type: ClassVar[str] = "Field"
    label: str
    help: str | None = None
    error: str | None = None
    required: bool = False


class ToggleGroup(_Owned):
    type: ClassVar[str] = "ToggleGroup"
    options: list[Option]
    value: str | list[str] | None = None
    default: str | list[str] | None = None
    multiple: bool = False
    size: Size = "md"
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))


class Input(_Owned):
    type: ClassVar[str] = "Input"
    value: str | None = None
    default: str | None = None
    placeholder: str | None = None
    kind: Literal["text", "password", "email", "number", "search", "url"] = "text"
    prefix_icon: str | None = None
    suffix: str | None = None
    disabled: bool = False
    readonly: bool = False
    clearable: bool = False
    debounce_ms: int = 250
    on_change: Any = None
    on_submit: Any = None


class Textarea(_Owned):
    type: ClassVar[str] = "Textarea"
    value: str | None = None
    default: str | None = None
    placeholder: str | None = None
    rows: int = 3
    autosize: bool = False
    max_length: int | None = None
    disabled: bool = False
    readonly: bool = False
    debounce_ms: int = 250
    on_change: Any = None
    on_submit: Any = None


class NumberInput(_Owned):
    type: ClassVar[str] = "NumberInput"
    value: float | None = None
    default: float | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    suffix: str | None = None
    placeholder: str | None = None
    disabled: bool = False
    on_change: Any = None


class Combobox(_Owned):
    """A searchable single choice. ``options`` filters in the tab; ``on_search(query)``
    returns the options for what was typed, answered over the socket without a render.
    ``allow_custom`` lets typed text that matches nothing be the value."""

    type: ClassVar[str] = "Combobox"
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


class MultiSelect(_Owned):
    """Several choices from a list, shown as chips; typing filters the list."""

    type: ClassVar[str] = "MultiSelect"
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


class Select(_Owned):
    type: ClassVar[str] = "Select"
    options: list[Option]
    value: str | None = None
    default: str | None = None
    placeholder: str | None = None
    clearable: bool = False
    disabled: bool = False
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))


class Checkbox(_Owned):
    type: ClassVar[str] = "Checkbox"
    label: str | None = None
    description: str | None = None
    checked: bool | None = None
    default_checked: bool | None = None
    disabled: bool = False
    on_change: Any = None


class CheckboxGroup(_Owned):
    type: ClassVar[str] = "CheckboxGroup"
    options: list[Option]
    value: list[str] | None = None
    default: list[str] | None = None
    label: str | None = None
    disabled: bool = False
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))


class RadioGroup(_Owned):
    type: ClassVar[str] = "RadioGroup"
    options: list[Option]
    value: str | None = None
    default: str | None = None
    label: str | None = None
    orientation: Literal["vertical", "horizontal"] = "vertical"
    disabled: bool = False
    on_change: Any = None

    _options = field_validator("options", mode="before")(staticmethod(as_options))


class Switch(_Owned):
    type: ClassVar[str] = "Switch"
    label: str | None = None
    description: str | None = None
    checked: bool | None = None
    default_checked: bool | None = None
    disabled: bool = False
    on_change: Any = None


class Slider(_Owned):
    type: ClassVar[str] = "Slider"
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


class Tooltip(Component):
    type: ClassVar[str] = "Tooltip"
    content: str


class Custom(Component):
    """An app's own component: ``components/<name>.jsx``, compiled in the tab.

    ``props`` arrive as React props next to ``emit`` and ``children``; events
    the component emits reach ``on_event`` as ``(session, (name, payload))``,
    or a handler per event name through ``events``.
    """

    type: ClassVar[str] = "Custom"
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"name", "props", "events"})

    name: str
    props: dict[str, Any] = {}
    events: dict[str, Any] = {}
    on_event: Any = None

    def __init__(self, name: str, *children: Any, **kw: Any) -> None:
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


class Steps(Component):
    """A step tree on Trace: the task's steps, or ``items`` given directly."""

    type: ClassVar[str] = "Steps"
    items: list[Any] | None = None
    task: Any = None
    compact: bool = False


class Skeleton(Component):
    type: ClassVar[str] = "Skeleton"
    rows: int = 3
    shape: Literal["text", "card", "table"] = "text"


class Spinner(Component):
    type: ClassVar[str] = "Spinner"
    size: Size = "md"
    label: str | None = None


__all__ = [
    "Accept",
    "Action",
    "Accordion",
    "AccordionItem",
    "Alert",
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
    "Command",
    "Custom",
    "Component",
    "Dialog",
    "Download",
    "FileCard",
    "FileRef",
    "FileUpload",
    "Empty",
    "Form",
    "FormIssues",
    "Grid",
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
    "Tooltip",
    "as_options",
]
