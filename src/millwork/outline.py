"""The page as data: what a page holds for the person in front of it, said
by each of its components.

It is made from what went to the tab, the nodes of the session's tree, and
holds less than that. Each kind of component has an entry in ``SAYS`` that
names what of it a person reads: a label, a text, a value, the columns a
table has. Nothing else of a component is said, and a component of a kind
that has no entry, an app's own, says its type and its name and no more.
So a table's rows go to the tab whole and only the columns it shows are in
here, in the form the cells have, and a hidden component is sent and not in
here at all. What is read from a page may end up in a model's prompt, and
whoever kept something off the screen did not mean it to.

What a press would bring up is in it, and says whether it shows now: a
closed dialog that it is closed, a group that it is folded where the page
holds that, and that it may be where the browser keeps it.

Two forms: a structure of plain dicts and lists, for code and for tools,
and a text for a model to read, a line for a component with what it holds
indented under it.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import math
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeGuard

if TYPE_CHECKING:
    from millwork.nodes import Tree
    from millwork.protocol import Node

__all__ = ["SAYS", "Says", "as_text", "outline", "pointed"]

# How many options, menu items and suggestions are named before the rest
# is counted, and how many columns of a table and fields of a form.
LISTED = 12
COLUMNS = 30
FIELDS = 60
# What a text cannot hold: what is not drawn, and what turns the text
# after it around.
_UNSEEN = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


class _Limits:
    def __init__(
        self,
        rows: int,
        chars: int,
        showing: dict[str, Any] | None = None,
        issues: dict[str, list[Any]] | None = None,
        currency: str | None = None,
    ) -> None:
        self.rows = max(rows, 0)
        self.chars = max(chars, 0)
        # The tab each tab strip is on, as the browser said.
        self.showing = showing or {}
        # What each form was told is wrong with it at its last submit.
        self.issues = issues or {}
        # What an amount of money is in, by the app's theme.
        self.currency = currency

    def cut(self, text: Any) -> str:
        """A text on one line, and no longer than ``chars``."""
        line = " ".join(_UNSEEN.sub(" ", str(text)).split())
        return line if len(line) <= self.chars else line[: self.chars].rstrip() + "..."

    def some(self, name: str, items: list[Any]) -> dict[str, Any]:
        """The first of a list of names under ``name``, each cut, and under
        ``<name>_more`` how many there are beyond those."""
        out: dict[str, Any] = {name: [self.cut(item) for item in items[:LISTED]]}
        if len(items) > LISTED:
            out[f"{name}_more"] = len(items) - LISTED
        return out


def _finite(value: Any) -> TypeGuard[int | float]:
    """Whether a value is a number that can be written out."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return abs(value) < 1e300 and math.isfinite(value)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _option(option: Any) -> tuple[Any, str]:
    """An option's value and what it reads as."""
    if isinstance(option, dict):
        value = option.get("value", option.get("id"))
        return value, str(option.get("label") or value or "")
    return option, str(option)


def _number(value: Any, style: str | None, currency: str | None = None) -> str:
    """A number to the digits the page shows: none for ``integer``, one at
    most for ``percent``, two for ``currency`` and three at most otherwise,
    rounded as the browser rounds. The page groups the digits and writes
    the decimal mark as the theme's locale does. Here it is plain digits
    with a point, which reads the same in any language, and an amount of
    money is followed by what it is in. A text that is no number is shown
    as it is, and nothing stands for a number that is not one, which
    reaches the tab as nothing."""
    if isinstance(value, bool):
        value = int(value)
    try:
        with decimal.localcontext() as context:
            context.prec = 400
            # By the digits the number is written with, as the browser
            # rounds: 1.005 goes up, though the float is a hair under it.
            n = decimal.Decimal(value.strip() if isinstance(value, str) else repr(value))
            if not n.is_finite():
                return ""
            digits = {"integer": 0, "percent": 1, "currency": 2}.get(style or "", 3)
            if style == "percent":
                n *= 100
            rounded = n.quantize(decimal.Decimal(1).scaleb(-digits), decimal.ROUND_HALF_UP)
            text = f"{rounded:f}"
    except (decimal.InvalidOperation, TypeError, ValueError):
        return str(value) if isinstance(value, str) else ""
    if style == "currency":
        return f"{text} {currency}" if currency else text
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + "%" if style == "percent" else text


def _cell(value: Any, style: str | None, currency: str | None = None) -> str:
    """What a table's cell shows for a value in a column's format."""
    if value is None or (isinstance(value, str) and not value.strip() and style != "text"):
        return ""
    if style in ("number", "integer", "percent", "currency"):
        return _number(value, style, currency)
    if style in ("date", "datetime"):
        try:
            when = dt.datetime.fromisoformat(str(value))
        except ValueError:
            # The browser reads more ways of writing a date than this does,
            # and shows the day of one it can read. A text with a time of
            # day in it may be one of those, and is not passed on.
            return "" if re.search(r"\d:\d\d", str(value)) else str(value)
        return when.date().isoformat() if style == "date" else when.isoformat(" ", "minutes")
    if style == "bool":
        return "yes" if value else "no"
    return _plain(value)


def _shown(value: Any, style: Any, limits: _Limits) -> str:
    """A cell, cut as a text is. A number is given whole: one that is short
    of its last digits is another number."""
    text = _cell(value, style if isinstance(style, str) else None, limits.currency)
    if style in ("number", "integer", "percent", "currency") and len(text) <= 40:
        return " ".join(text.split())
    return limits.cut(text)


def _plain(value: Any) -> str:
    """A value as the tab writes it out when it has no format for it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            # Sent as nothing.
            return ""
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, dict):
        # Nothing a person can read is drawn for one.
        return ""
    if isinstance(value, list):
        return ",".join(_plain(v) for v in value if not isinstance(v, dict | list))
    return "" if value is None else str(value)


# ----------------------------------------------------- what the richer kinds say


def _button(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not _text(props.get("label")):
        # A button with an icon alone is read by its tooltip.
        if _text(props.get("tooltip")):
            out["label"] = limits.cut(props["tooltip"])
        elif _text(props.get("icon")):
            out["icon"] = limits.cut(props["icon"])
    if props.get("confirm"):
        out["state"] = ["asks first"]
    if _text(props.get("form")):
        out["submits"] = limits.cut(props["form"])
    return out


def _input(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if _text(props.get("kind")) and props["kind"] not in ("text", "password"):
        out["kind"] = limits.cut(props["kind"])
    if _text(props.get("suffix")):
        out["suffix"] = limits.cut(props["suffix"])
    return out


def _bounds(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    return {
        name: limits.cut(_plain(props[name]))
        for name in ("min", "max")
        if isinstance(props.get(name), int | float | str) and _plain(props[name])
    }


def _number_input(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    out = _bounds(props, limits)
    if _text(props.get("suffix")):
        out["suffix"] = limits.cut(props["suffix"])
    return out


def _table(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    rows = _list(props.get("rows"))
    every = [c for c in _list(props.get("columns")) if isinstance(c, dict) and not c.get("hidden")]
    shown = every[:COLUMNS]

    def header(column: dict[str, Any]) -> str:
        # A header that was given is the one shown, an empty one too.
        given = column.get("header")
        return limits.cut(given if isinstance(given, str) else column.get("key", ""))

    out: dict[str, Any] = {
        "columns": [header(c) for c in shown],
        "column_count": len(every),
        "row_count": len(rows),
        # As the table was given them. The person may have sorted them
        # since, or be on another page of them.
        "rows": [
            [_shown(_dict(row).get(str(c.get("key"))), c.get("format"), limits) for c in shown]
            for row in rows[: limits.rows]
        ],
    }
    state = []
    if _list(props.get("selected")):
        # Rows are picked by a key that is no column: how many, not which.
        out["selected_count"] = len(props["selected"])
    for sort in _list(props.get("default_sort"))[:1]:
        if isinstance(sort, list | tuple) and len(sort) == 2 and sort[1] in ("asc", "desc"):
            named = next((header(c) for c in every if c.get("key") == sort[0]), None)
            # By a field that has no column the rows are sorted as well.
            by = _quoted(named) if named is not None else "a field that has no column"
            state.append(f"shown sorted by {by} {sort[1]}")
    if isinstance(props.get("page_size"), int) and 0 < props["page_size"] < len(rows):
        state.append(f"{props['page_size']} to a page")
    if props.get("selection") in ("row", "rows"):
        state.append("rows can be selected")
    if props.get("on_row_click"):
        state.append("rows can be pressed")
    if props.get("search"):
        state.append("has a search box")
    if props.get("filters"):
        state.append("has a filter for each column")
    actions = [str(_dict(a).get("label") or "") for a in _list(props.get("row_actions"))]
    if any(actions):
        out.update(limits.some("row_actions", [a for a in actions if a]))
    if not rows and _text(props.get("empty")):
        out["empty"] = limits.cut(props["empty"])
    if _text(props.get("summary")):
        out["help"] = limits.cut(props["summary"])
    if state:
        out["state"] = state
    return out


def _at(record: Any, pointer: Any) -> Any:
    """What a form's draft holds at a field's pointer, or nothing."""
    for name in str(pointer).split("/")[1:]:
        if not isinstance(record, dict) or name not in record:
            return None
        record = record[name]
    return record


def _fields(fields: Any, limits: _Limits, values: Any = None) -> dict[str, Any]:
    """A form's fields, under ``fields``, as the form draws them: not one
    it keeps to itself. ``values`` is what the form shows in them, for one
    that cannot be typed in. A field for a password gives none."""
    drawn = [f for f in _list(fields) if isinstance(f, dict) and f.get("widget") != "hidden"]
    said: list[dict[str, Any]] = []
    for field in drawn[:FIELDS]:
        widget = field.get("widget")
        one: dict[str, Any] = {
            "name": limits.cut(field.get("name") or ""),
            "kind": limits.cut(widget or ""),
        }
        if _text(field.get("label")):
            one["label"] = limits.cut(field["label"])
        if field.get("required"):
            one["required"] = True
        if _text(field.get("help")):
            one["help"] = limits.cut(field["help"])
        options = [_option(o) for o in _list(field.get("options"))] or [
            # One of several shapes, chosen by name.
            (_dict(v).get("tag"), str(_dict(v).get("label") or ""))
            for v in _list(field.get("variants"))
        ]
        if options:
            one.update(limits.some("options", [label for _, label in options]))
        # A field that holds fields. A list has the fields of one item,
        # which are there to be filled in once an item is added.
        inner = field.get("fields")
        if values is None and not inner:
            inner = _dict(field.get("item")).get("fields")
        if inner:
            one.update(_fields(inner, limits, values))
        elif values is not None and widget != "password":
            value = _at(values, field.get("pointer"))
            if isinstance(value, str | int | float | bool):
                read = {v: label for v, label in options if isinstance(v, str | int | float)}
                if not options or value in read:
                    one["value"] = limits.cut(read.get(value, _plain(value)))
        said.append(one)
    out: dict[str, Any] = {"fields": said} if said else {}
    if len(drawn) > FIELDS:
        out["fields_more"] = len(drawn) - FIELDS
    return out


def _issues(issues: Any, limits: _Limits) -> dict[str, Any]:
    said = [f"{_dict(i).get('pointer', '')}: {_dict(i).get('message', '')}" for i in _list(issues)]
    return limits.some("issues", said)


def _form(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    # A form that cannot be typed in shows what it was given. Any other
    # keeps what is typed into it in the browser.
    values = _dict(props.get("initial")) if props.get("read_only") else None
    out: dict[str, Any] = {"fields": []}
    out.update(_fields(_dict(props.get("schema")).get("fields"), limits, values))
    if values is None:
        out["state"] = ["values kept in the browser"]
    buttons = [props.get(name) for name in ("submit", "cancel")]
    if any(_text(b) for b in buttons):
        out["buttons"] = [limits.cut(b) for b in buttons if _text(b)]
    if _list(props.get("issues")):
        out.update(_issues(props["issues"], limits))
    return out


def _chart(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    data = _list(props.get("data"))
    series = [s for s in _list(props.get("series")) if isinstance(s, dict)]
    keys = [str(s.get("key")) for s in series] or ["value"]
    names = [limits.cut(s.get("label") or s.get("key") or "") for s in series] or ["value"]
    style = props.get("format") if isinstance(props.get("format"), str) else None

    def point(value: Any) -> str:
        # A value in the chart's own format, and nothing for what is no
        # number, which the chart leaves a gap for.
        if isinstance(value, str | bool) or value is None:
            return ""
        return _number(value, style, limits.currency)

    return {
        # The first column is what stands along the axis, which has no name.
        "columns": ["", *names][:COLUMNS],
        "column_count": len(names) + 1,
        "row_count": len(data),
        "rows": [
            [limits.cut(_plain(_dict(row).get("x"))), *(point(_dict(row).get(k)) for k in keys)][
                :COLUMNS
            ]
            for row in data[: limits.rows]
        ],
    }


def _shown_messages(props: dict[str, Any], limits: _Limits) -> list[Any]:
    """The last of a chat's messages, as many as rows of a table are given."""
    messages = _list(props.get("messages"))
    return messages[-limits.rows :] if limits.rows else []


def _chat(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    messages = _list(props.get("messages"))
    said = []
    for message in _shown_messages(props, limits):
        text = " ".join(
            str(p.get("text"))
            for p in _list(_dict(message).get("parts"))
            if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
        )
        said.append([limits.cut(_dict(message).get("role") or ""), limits.cut(text)])
    out: dict[str, Any] = {"message_count": len(messages)}
    if said:
        out["messages"] = said
    suggestions = [s for s in _list(props.get("suggestions")) if isinstance(s, str)]
    if suggestions and not messages:
        out.update(limits.some("items", suggestions))
    if _text(props.get("welcome")) and not messages:
        out["text"] = limits.cut(props["welcome"])
    return out


def _carried(props: dict[str, Any], limits: _Limits) -> set[str]:
    """The names of the components the messages that are given carry."""
    names = set()
    for message in _shown_messages(props, limits):
        for part in _list(_dict(message).get("parts")):
            slot = _dict(_dict(part).get("data")).get("slot")
            if isinstance(slot, str):
                names.add(slot)
    return names


def _steps(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    items = [
        i
        for i in _list(props.get("items")) or _list(_dict(props.get("task")).get("steps"))
        if isinstance(i, dict)
    ]
    said = []
    for item in items:
        line = f"{item.get('label')} ({item.get('status')})"
        if _text(item.get("note")):
            line += f": {item['note']}"
        said.append(limits.cut(line))
    if not said:
        return {}
    # The steps around the one that is under way, which is the one that is
    # asked about.
    last = max((n for n, i in enumerate(items) if i.get("status") != "pending"), default=0)
    start = max(0, min(last - LISTED + 2, len(said) - LISTED))
    out: dict[str, Any] = {"items": said[start : start + LISTED]}
    if start:
        out["items_before"] = start
    if len(said) > start + LISTED:
        out["items_more"] = len(said) - start - LISTED
    return out


def _menu(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    labels = [str(_dict(i).get("label") or "") for i in _list(props.get("items"))]
    return limits.some("items", [label for label in labels if label]) if any(labels) else {}


def _stat(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if props.get("value") is not None:
        out["value"] = limits.cut(props["value"])
    delta = props.get("delta")
    if _finite(delta):
        style = "number" if props.get("delta_format") == "number" else "percent"
        way = "up" if delta > 0 else "down" if delta < 0 else "level"
        out["delta"] = f"{way} {_number(abs(delta), style)}"
    return out


def _progress(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    task = _dict(props.get("task"))
    status = task.get("status")
    out: dict[str, Any] = {}
    label = props.get("label") or task.get("label")
    if _text(label):
        out["label"] = limits.cut(label)
    said = props.get("description") or task.get("message")
    if not said and status == "failed":
        said = _dict(task.get("error")).get("message")
    if _text(said):
        out["help"] = limits.cut(said)
    raw = task.get("progress") if task else props.get("value")
    # In whole percents, and not where the bar is told to show none or its
    # task ended without finishing, which stands in the number's place.
    if _finite(raw) and props.get("percent") is not False and status not in ("failed", "cancelled"):
        out["value"] = f"{math.floor(raw * 100 + 0.5)}%"
    if status in ("failed", "cancelled", "done"):
        out["state"] = [str(status)]
    return out


def _file(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    out: dict[str, Any] = {}
    name = props.get("name") or _dict(props.get("file")).get("name")
    if _text(name):
        out["label"] = limits.cut(name)
    if _text(props.get("meta")):
        out["help"] = limits.cut(props["meta"])
    if props.get("status") in ("loading", "error"):
        out["state"] = [str(props["status"])]
    actions = [str(_dict(a).get("label") or "") for a in _list(props.get("actions"))]
    if any(actions):
        out.update(limits.some("items", [a for a in actions if a]))
    return out


def _download(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    return {"file": limits.cut(props["filename"])} if _text(props.get("filename")) else {}


def _upload(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    accept = [str(a) for a in _list(props.get("accept"))]
    return limits.some("accepts", accept) if accept else {}


def _kbd(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    keys = [str(k) for k in _list(props.get("keys"))]
    return {"text": limits.cut("+".join(keys))} if keys else {}


def _tab(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    badge = props.get("badge")
    return {"badge": limits.cut(badge)} if isinstance(badge, str | int) and badge != "" else {}


def _waiting(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    # A page that is all of these is not an empty one.
    return {"state": ["stands in for what is loading"]}


def _field(props: dict[str, Any], limits: _Limits) -> dict[str, Any]:
    return {"error": limits.cut(props["error"])} if _text(props.get("error")) else {}


# --------------------------------------------------------------- the table


@dataclass(frozen=True)
class Says:
    """What a kind of component says of itself. Every prop whose value is
    said is named here or read in ``more``, and no other is. Beside those,
    ``hidden`` and ``on_click`` are read of every kind, and what a tab
    strip and an accordion hold open, each for a word of state."""

    # Props that hold the name a person reads, the first that has one.
    label: tuple[str, ...] = ()
    # The prop that holds its text.
    text: str | None = None
    # Props that hold a line of help, the first that has one.
    help: tuple[str, ...] = ()
    placeholder: bool = False
    href: bool = False
    # The prop a control's value is in, when the page holds it.
    held: str | None = None
    # Whether it has ``options``, which a value is then said by.
    options: bool = False
    # The prop that lets a text be typed in where the options are, which
    # is then what it shows.
    typed: str | None = None
    # The prop that says whether it is open, and the word for when not.
    folds: str | None = None
    folded: str = "closed"
    # Whether the browser keeps that when the page does not say.
    browser: bool = True
    # Whether the page says by sending the prop at all, an empty one too.
    # Otherwise it says only with a yes or a no.
    by_presence: bool = True
    # A prop and the value of it with which it does not fold at all.
    fixed: tuple[str, Any] | None = None
    # Props that are true or not, and the word for each.
    flags: tuple[tuple[str, str], ...] = ()
    # Props that hold components.
    slots: tuple[str, ...] = ()
    more: Callable[[dict[str, Any], _Limits], dict[str, Any]] | None = None
    # Only places others: passed over in the text when it has no name.
    places: bool = False
    # Read, not used: a keyless one gets no id in the text.
    passive: bool = False


_OFF = (("disabled", "disabled"),)
_FIELD = (("disabled", "disabled"), ("readonly", "read only"))
_CHART = Says(more=_chart)

SAYS: dict[str, Says] = {
    # Places others.
    "Page": Says(label=("title",), slots=("header",), places=True),
    "Stack": Says(places=True),
    "Row": Says(places=True),
    "Grid": Says(places=True),
    "Split": Says(places=True),
    "ScrollArea": Says(places=True),
    "ButtonGroup": Says(places=True),
    "Floating": Says(places=True),
    "Field": Says(
        label=("label",),
        help=("help",),
        flags=(("required", "required"),),
        more=_field,
        places=True,
    ),
    "Card": Says(label=("title",), help=("description",), slots=("footer",), places=True),
    "Header": Says(label=("title",), slots=("links",)),
    "Sidebar": Says(
        label=("title",), folds="open", folded="folded away", fixed=("collapsible", "none")
    ),
    "SidebarGroup": Says(
        label=("label",), folds="open", folded="folded", fixed=("collapsible", False)
    ),
    "Collapsible": Says(label=("title",), folds="open", folded="folded"),
    "Accordion": Says(places=True),
    "AccordionItem": Says(label=("title",)),
    "Tabs": Says(),
    "Tab": Says(label=("label",), flags=_OFF, more=_tab),
    "Dialog": Says(
        label=("title",), help=("description",), folds="open", browser=False, slots=("footer",)
    ),
    "Sheet": Says(label=("title",), help=("description",), folds="open", browser=False),
    # The window's own title, and the name of its button when it has none.
    "Assistant": Says(
        label=("title", "label"), folds="open", folded="minimized", by_presence=False
    ),
    # Read.
    "Text": Says(text="content", passive=True),
    "Markdown": Says(text="content", passive=True),
    "Code": Says(label=("title",), text="content", passive=True),
    "Kbd": Says(more=_kbd, passive=True),
    "Badge": Says(label=("label",), passive=True),
    "Separator": Says(label=("label",), passive=True),
    "Icon": Says(label=("label",), passive=True),
    "Image": Says(label=("alt",), passive=True),
    "Spinner": Says(label=("label",), more=_waiting, passive=True),
    "Skeleton": Says(more=_waiting, passive=True),
    "Logo": Says(passive=True),
    "Pdf": Says(),
    "Tooltip": Says(text="content", passive=True),
    "Alert": Says(label=("title",), help=("description",), slots=("actions",)),
    "Empty": Says(label=("title",), help=("description",), slots=("action",)),
    "Stat": Says(label=("label",), help=("hint",), more=_stat),
    "Progress": Says(more=_progress),
    "Steps": Says(more=_steps),
    "FileCard": Says(more=_file),
    # Pressed.
    "Button": Says(label=("label",), href=True, flags=(*_OFF, ("loading", "busy")), more=_button),
    "Link": Says(label=("label",), href=True, flags=(("active", "the page it is on"),)),
    "Download": Says(label=("label",), flags=_OFF, more=_download),
    "DropdownMenu": Says(slots=("trigger",), more=_menu),
    "SignIn": Says(label=("label",)),
    # Filled in.
    "Input": Says(placeholder=True, held="value", flags=_FIELD, more=_input),
    "Textarea": Says(placeholder=True, held="value", flags=_FIELD),
    "NumberInput": Says(placeholder=True, held="value", flags=_OFF, more=_number_input),
    "Slider": Says(held="value", flags=_OFF, more=_bounds),
    "DatePicker": Says(placeholder=True, held="value", flags=_OFF, more=_bounds),
    "Select": Says(placeholder=True, held="value", options=True, flags=_OFF),
    "Combobox": Says(
        placeholder=True, held="value", options=True, typed="allow_custom", flags=_OFF
    ),
    "MultiSelect": Says(placeholder=True, held="value", options=True, flags=_OFF),
    "RadioGroup": Says(label=("label",), held="value", options=True, flags=_OFF),
    "CheckboxGroup": Says(label=("label",), held="value", options=True, flags=_OFF),
    "ToggleGroup": Says(held="value", options=True),
    "Checkbox": Says(label=("label",), help=("description",), held="checked", flags=_OFF),
    "Switch": Says(label=("label",), help=("description",), held="checked", flags=_OFF),
    "FileUpload": Says(label=("label",), help=("description",), flags=_OFF, more=_upload),
    # Data.
    "Table": Says(more=_table),
    "Form": Says(flags=(*_OFF, ("read_only", "read only")), more=_form),
    "Chat": Says(
        placeholder=True,
        flags=(*_OFF, ("busy", "busy")),
        slots=("tools", "inline"),
        more=_chat,
    ),
    "BarChart": _CHART,
    "LineChart": _CHART,
    "AreaChart": _CHART,
    "PieChart": _CHART,
}

# Words that say a component does not show now, and words that say it may
# not, where the browser keeps whether it does.
_NOT_SHOWING = {"closed", "folded", "folded away", "minimized", "not the open tab"}
_MAY_NOT_SHOW = {
    "may be folded",
    "may be folded away",
    "may be minimized",
    "may not be the open tab",
}
# Slots that stand before what a component holds. The others stand after.
_BEFORE = {"header", "trigger"}


def _slots(props: dict[str, Any], names: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    """The components a node holds in the props named: one, a list of them,
    or several by name, as a chat holds what its replies carry."""
    for name in names:
        value = props.get(name)
        if isinstance(value, dict) and "$node" not in value:
            items = list(value.values())
        else:
            items = _list(value) or [value]
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("$node"), str):
                yield name, item["$node"]


def _held(value: Any, limits: _Limits) -> Any:
    """What a control holds, as a value of the outline's own: a text cut,
    a number that is one, and of a list the first."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if value.is_integer() else value
    if isinstance(value, list):
        return [_held(v, limits) for v in value if not isinstance(v, list | dict)]
    return None if isinstance(value, dict) else limits.cut(value)


def _entry(tree: Tree, node: Node, limits: _Limits) -> dict[str, Any]:
    """What one component says of itself, without what it holds."""
    props = node.props
    component = tree.components.get(node.id)
    out: dict[str, Any] = {"id": node.id, "type": node.type}
    if component is not None and component.key:
        out["key"] = component.key
    says = SAYS.get(node.type)
    if says is None:
        # A kind that is not in the table: an app's own component. What it
        # draws from what it is given is not known here, so nothing is said.
        return out
    state: list[str] = []
    for name in says.label:
        if _text(props.get(name)):
            out["label"] = limits.cut(props[name])
            break
    if says.text and _text(props.get(says.text)):
        out["text"] = limits.cut(props[says.text])
    for name in says.help:
        if _text(props.get(name)):
            out["help"] = limits.cut(props[name])
            break
    if says.placeholder and _text(props.get("placeholder")):
        out["placeholder"] = limits.cut(props["placeholder"])
    if says.href and _text(props.get("href")):
        out["href"] = limits.cut(props["href"])

    options = [_option(o) for o in _list(props.get("options"))] if says.options else []
    if options:
        out.update(limits.some("options", [label for _, label in options]))
    if says.held is not None:
        if props.get("kind") == "password":
            state.append("secret")
        elif says.held in props:
            # The page holds it, and an empty one is held as well.
            value = props[says.held]
            if says.options:
                # By the name the person sees, not by what stands behind
                # it. What no option gives a name to is not said.
                read = {v: label for v, label in options if isinstance(v, str | int | float)}
                chosen = value if isinstance(value, list) else [value]
                known = [read[v] for v in chosen if isinstance(v, str | int | float) and v in read]
                unread = any(v not in (None, "") for v in chosen) and len(known) < len(chosen)
                typed = bool(
                    unread and says.typed and props.get(says.typed) and isinstance(value, str)
                )
                if unread and not typed:
                    state.append("holds a value that is none of the options given")
                if not typed:
                    # What was typed in where that is allowed is what shows.
                    value = known if isinstance(value, list) else (known[0] if known else None)
                if not unread or typed or isinstance(value, list):
                    out["value"] = _held(value, limits)
            else:
                out["value"] = _held(value, limits)
            if isinstance(out.get("value"), list) and len(out["value"]) > LISTED:
                out["value_more"] = len(out["value"]) - LISTED
                del out["value"][LISTED:]
        else:
            # Kept in the browser: the server is told of a change when the
            # page asked to be, and does not hold what the field shows.
            state.append("value kept in the browser")

    if says.more is not None:
        extra = says.more(props, limits)
        state += extra.pop("state", [])
        out.update(extra)
    told = limits.issues.get(node.id) if node.type == "Form" else None
    if told:
        # What its last submit was turned down for, which went to the tab
        # by itself.
        out.update(_issues([*_list(props.get("issues")), *told], limits))
    if says.folds is not None and not (says.fixed and props.get(says.fixed[0]) == says.fixed[1]):
        opened = props.get(says.folds)
        held = says.folds in props if says.by_presence else isinstance(opened, bool)
        if not held and says.browser:
            # The browser keeps it, and the person may have folded it.
            state.append(f"may be {says.folded}")
        elif not opened:
            state.append(says.folded)
    for flag, word in says.flags:
        if props.get(flag):
            state.append(word)
    if props.get("on_click") and node.type != "Button":
        state.append("can be pressed")
    if state:
        out["state"] = state
    return out


def _mark(entry: dict[str, Any], word: str) -> None:
    entry["state"] = [*entry.get("state", []), word]


def _walk(
    tree: Tree, node_id: str, limits: _Limits, slot: str | None = None
) -> dict[str, Any] | None:
    node = tree.nodes.get(node_id)
    if node is None or node.props.get("hidden"):
        return None
    out = _entry(tree, node, limits)
    if slot is not None:
        out["slot"] = slot
    says = SAYS.get(node.type)
    props = node.props
    if node.type == "Chat" and isinstance(props.get("inline"), dict):
        # What the replies carry, of the messages that are given.
        carried = _carried(props, limits)
        props = {**props, "inline": {k: v for k, v in props["inline"].items() if k in carried}}
    before: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    for name, child_id in _slots(props, says.slots if says is not None else ()):
        child = _walk(tree, child_id, limits, name)
        if child is not None:
            (before if name in _BEFORE else after).append(child)
    children = [w for w in (_walk(tree, i, limits) for i in node.children) if w]
    if node.type == "Tabs":
        # The page holds which tab is open, or the browser says, which it
        # does for a strip the session asked to hear of. Of any other the
        # browser keeps it.
        held = "value" in props
        open_tab = props.get("value")
        if not held and props.get("track"):
            open_tab = limits.showing.get(node_id)
            held = open_tab is not None
        for child in children:
            if child["type"] != "Tab":
                continue
            if not held:
                _mark(child, "may not be the open tab")
            elif tree.nodes[child["id"]].props.get("id") != open_tab:
                _mark(child, "not the open tab")
            elif child.get("label"):
                out["open"] = child["label"]
    if node.type == "Accordion":
        value = props.get("value")
        unfolded = {str(v) for v in (value if isinstance(value, list) else [value]) if v}
        for child in children:
            if child["type"] != "AccordionItem":
                continue
            if "value" not in props:
                _mark(child, "may be folded")
            elif str(tree.nodes[child["id"]].props.get("id")) not in unfolded:
                _mark(child, "folded")
    inside = [*before, *children, *after]
    if inside:
        out["children"] = inside
    return out


def _find(
    entry: dict[str, Any], node_id: str, under: list[str]
) -> tuple[dict[str, Any], list[str]] | None:
    """The entry of one component in an outline, and what it is inside of
    that does not show now, or may not."""
    if entry["id"] == node_id:
        return entry, under
    words = [
        s if s in _NOT_SHOWING else f"that {s}"
        for s in entry.get("state", [])
        if s in _NOT_SHOWING or s in _MAY_NOT_SHOW
    ]
    for child in entry.get("children", []):
        found = _find(child, node_id, [*under, *words])
        if found is not None:
            return found
    return None


def _shows(entry: dict[str, Any]) -> bool:
    return not any(word in _NOT_SHOWING for word in entry.get("state", []))


def outline(
    tree: Tree | None,
    *,
    within: str | Sequence[str] | None = None,
    rows: int = 5,
    chars: int = 200,
    showing: dict[str, Any] | None = None,
    issues: dict[str, list[Any]] | None = None,
    currency: str | None = None,
) -> dict[str, Any] | None:
    """What the page holds for the person, as a structure: a dict for each
    component, with what it holds under ``children``. ``within`` is the id
    of a component to start at, or the ids a name finds, of which it is
    the first that shows. None for a page that is not there, and for a
    component that is hidden, inside a hidden one, or not on the page.
    ``currency`` is what an amount of money is in."""
    if tree is None:
        return None
    whole = _walk(tree, tree.root, _Limits(rows, chars, showing, issues, currency))
    if whole is None or within is None:
        return whole
    # From the top, so that what the component is inside of is known: one
    # inside a hidden component is not given, and one inside a closed
    # dialog says so.
    ids = [within] if isinstance(within, str) else within
    found = [f for f in (_find(whole, node_id, []) for node_id in ids) if f is not None]
    if not found:
        return None
    entry, under = next((f for f in found if not f[1] and _shows(f[0])), found[0])
    if under:
        entry = {**entry, "state": [*entry.get("state", []), f"inside something {under[-1]}"]}
    return entry


def pointed(tree: Tree) -> dict[str, int]:
    """How many components each key on the page finds when it is used as a
    name: the ones that have the key, and the ones whose id ends in it."""
    found = {c.key: 0 for c in tree.components.values() if c.key}
    for node_id in tree.nodes:
        component = tree.components.get(node_id)
        hit = {component.key} if component is not None and component.key else set()
        at = -1
        while True:
            tail = node_id[at + 1 :]
            if tail in found:
                hit.add(tail)
            at = node_id.find("/", at + 1)
            if at == -1:
                break
        for key in hit:
            found[key] += 1
    return found


# -------------------------------------------------------------------- text
#
# Every word of the text is one of two things. What the app gave stands in
# quotes, or bare where it is one plain word. What is bare and is no such
# word is said by the outline itself.

_INLINE = (
    "open",
    "kind",
    "min",
    "max",
    "suffix",
    "href",
    "delta",
    "badge",
    "icon",
    "file",
    "submits",
)
_LISTS = (
    ("options", "options"),
    ("items", "items"),
    ("row_actions", "each row has"),
    ("accepts", "accepts"),
    ("buttons", "buttons"),
    ("issues", "its last submit was turned down for"),
)
_BARE = re.compile(r"[-@/]?[A-Za-z0-9][A-Za-z0-9_.,:%@/+-]*")


# What would end a line, or is not drawn, inside quotes.
_ESCAPED = re.compile("[\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def _quoted(text: Any) -> str:
    said = json.dumps(str(text), ensure_ascii=False)
    return _ESCAPED.sub(lambda found: f"\\u{ord(found.group()):04x}", said)


def _word(text: Any) -> str:
    """Something of the app's where a word of the outline's could stand: as
    it is when it is one plain word, and in quotes otherwise."""
    text = str(text)
    return text if _BARE.fullmatch(text) else _quoted(text)


def _keys(entry: dict[str, Any], seen: dict[str, int]) -> None:
    if entry.get("key"):
        seen[entry["key"]] = seen.get(entry["key"], 0) + 1
    for child in entry.get("children", []):
        _keys(child, seen)


def _line(entry: dict[str, Any], keys: dict[str, int]) -> str:
    says = SAYS.get(entry["type"])
    state = entry.get("state", [])
    # The name of a kind of the app's own is the app's.
    words = [entry["type"].lower() if says is not None else _word(entry["type"].lower())]
    if entry.get("label"):
        words.append(_quoted(entry["label"]))
    if entry.get("text"):
        words.append(_quoted(entry["text"]))
    # The name to point at it with: its key when that finds no other
    # component, and its id otherwise. One that is only read needs none.
    if entry.get("key") and keys.get(entry["key"]) == 1:
        words.append(f"key={_word(entry['key'])}")
    elif entry.get("key") or says is None or not says.passive or "can be pressed" in state:
        words.append(f"id={_word(entry['id'])}")
    if entry.get("slot") and entry["slot"] != entry["type"].lower():
        words.append(f"in its {entry['slot']}")
    if "value" in entry:
        value = entry["value"]
        said = _quoted(value) if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if entry.get("value_more"):
            said += f" and {entry['value_more']} more"
        words.append(f"value={said}")
    for name in _INLINE:
        if entry.get(name) is not None:
            words.append(f"{name}={_word(entry[name])}")
    if entry.get("placeholder"):
        words.append("placeholder " + _quoted(entry["placeholder"]))
    if "row_count" in entry:
        columns, rows = entry["column_count"], entry["row_count"]
        words.append(f"{columns} column{'s' * (columns != 1)}, {rows} row{'s' * (rows != 1)}")
    if "selected_count" in entry:
        words.append(f"{entry['selected_count']} selected")
    if "message_count" in entry:
        messages = entry["message_count"]
        words.append(f"{messages} message{'s' * (messages != 1)}")
    if entry.get("error"):
        words.append("error " + _quoted(entry["error"]))
    if entry.get("empty"):
        words.append("shows " + _quoted(entry["empty"]))
    words += state
    if entry.get("help"):
        words.append(_quoted(entry["help"]))
    return "  ".join(words)


def _named(entry: dict[str, Any], name: str) -> str:
    """A list of names, with how many stand before and after those given."""
    said = [_quoted(item) for item in entry[name]]
    if entry.get(f"{name}_before"):
        said.insert(0, f"{entry[f'{name}_before']} before")
    if entry.get(f"{name}_more"):
        said.append(f"and {entry[f'{name}_more']} more")
    return ", ".join(said)


def _field_lines(entry: dict[str, Any], pad: str) -> Iterator[str]:
    for field in entry.get("fields", []):
        words = [f"field {_word(field.get('name'))}"]
        if field.get("label"):
            words.append(_quoted(field["label"]))
        if field.get("kind"):
            words.append(_word(field["kind"]))
        if field.get("required"):
            words.append("required")
        if "value" in field:
            words.append(f"value={_quoted(field['value'])}")
        if field.get("options"):
            words.append("one of " + _named(field, "options"))
        if field.get("help"):
            words.append(_quoted(field["help"]))
        yield pad + "  ".join(words)
        yield from _field_lines(field, pad + "  ")
    if entry.get("fields_more"):
        yield f"{pad}and {entry['fields_more']} more"


def _says_nothing(entry: dict[str, Any]) -> bool:
    return not any(k not in ("id", "type", "children") for k in entry)


def _row(cells: list[Any], of: int) -> str:
    return " | ".join(map(_word, cells)) + (" | ..." if of > len(cells) else "")


def _lines(entry: dict[str, Any], depth: int, keys: dict[str, int]) -> Iterator[str]:
    says = SAYS.get(entry["type"])
    # One that only places others, or is only read, and says nothing.
    plain = says is not None and (says.places or says.passive) and _says_nothing(entry)
    pad = "  " * depth
    if not plain:
        yield pad + _line(entry, keys)
        depth += 1
        pad = "  " * depth
        for name, word in _LISTS:
            if entry.get(name):
                yield f"{pad}{word}: {_named(entry, name)}"
        if entry.get("columns"):
            yield pad + _row(entry["columns"], entry["column_count"])
            for row in entry.get("rows", []):
                yield pad + _row(row, entry["column_count"])
            if entry["row_count"] > len(entry.get("rows", [])):
                yield pad + "..."
        if entry.get("messages"):
            if entry["message_count"] > len(entry["messages"]):
                yield pad + "..."
            for who, said in entry["messages"]:
                yield f"{pad}{_word(who)}: {_quoted(said)}"
        yield from _field_lines(entry, pad)
    for child in entry.get("children", []):
        yield from _lines(child, depth, keys)


def as_text(entry: dict[str, Any] | None, keys: dict[str, int] | None = None) -> str:
    """The structure as text: a line for a component, with what it holds
    indented under it and a line each for a table's rows, a form's fields
    and the like. A component that only places others or is only read, and
    says nothing, is passed over. ``keys`` is how many components of the
    whole page each key finds, as ``pointed`` counts them: a key is a name
    to point with only when it finds one. Without it the keys are counted
    in what is given, which misses a key that an id elsewhere ends in."""
    if not entry:
        return ""
    if keys is None:
        keys = {}
        _keys(entry, keys)
    return "\n".join(_lines(entry, 0, keys))
