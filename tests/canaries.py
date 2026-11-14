"""Markers for every prop a component can be sent, to see which of them the
page as data says. A prop that holds a list or a record gets a marker in
each place a person's text could be, and one that is read as a number
gets a number that no other has."""

from __future__ import annotations

import copy
import re
import types
from collections.abc import Iterator
from typing import Any, Literal, Union, get_args, get_origin

from millwork import outline
from millwork.forms import WIDGETS
from millwork.nodes import Component, Tree
from millwork.protocol import Node


def catalogue() -> dict[str, type[Component]]:
    """Every kind of component millwork has, by the type it is sent as."""
    import millwork.ui
    import millwork.ui.chat
    import millwork.ui.files
    import millwork.ui.form
    import millwork.ui.table  # noqa: F401

    found: dict[str, type[Component]] = {}

    def walk(cls: type[Component]) -> None:
        for sub in cls.__subclasses__():
            if sub.__module__.startswith("millwork.") and "type" in vars(sub):
                found[sub.type] = sub
            walk(sub)

    walk(Component)
    return found


def m(name: str) -> str:
    return f"<<{name}>>"


NUMBERS: dict[str, str] = {}


def n(name: str) -> int:
    """A number that marks a prop: found again in a text by its digits,
    whatever it was multiplied by ten to and however it was grouped."""
    number = 7_100_001 + len(NUMBERS)
    NUMBERS[str(number)] = name
    return number


# Props that hold more than a text, each with a marker wherever a text is.
SHAPED: dict[str, Any] = {
    "options": [
        {
            "value": m("options.value"),
            "label": m("options.label"),
            "description": m("options.description"),
            "icon": m("options.icon"),
            "group": m("options.group"),
        }
    ],
    "items": [
        {
            "id": m("items.id"),
            "label": m("items.label"),
            "icon": m("items.icon"),
            "confirm": m("items.confirm"),
            "status": "done",
            "note": m("items.note"),
            "lines": [m("items.lines")],
        }
    ],
    "rows": [{"shown": m("rows.shown"), "kept": m("rows.kept"), "extra": m("rows.extra")}],
    "columns": [
        {"key": "shown", "header": m("columns.header")},
        {"key": "kept", "header": m("columns.hidden"), "hidden": True},
    ],
    "keys": [m("keys")],
    "selected": [m("selected")],
    "row_actions": [{"id": m("row_actions.id"), "label": m("row_actions.label")}],
    "tone_rows": [m("tone_rows")],
    "tone_cells": [{"shown": m("tone_cells")}],
    "default_sort": [[m("default_sort"), "asc"]],
    "data": [{"x": m("data.x"), "s": n("data.s"), "value": n("data.value"), "o": n("data.other")}],
    "series": [{"key": "s", "label": m("series.label"), "color": m("series.color")}],
    "trend": [n("trend")],
    "delta": n("delta"),
    "messages": [
        {
            "id": m("messages.id"),
            "role": "user",
            "parts": [
                {"type": "text", "text": m("messages.text")},
                {"type": "reasoning", "text": m("messages.reasoning")},
                {"type": "tool-search", "input": m("messages.tool"), "output": m("messages.out")},
                {"type": "file", "fileId": m("messages.file"), "url": m("messages.url")},
            ],
            "metadata": {"feedback": m("messages.metadata")},
        }
    ],
    "schema": {
        "title": m("schema.title"),
        "fields": [
            {
                "name": m("fields.name"),
                "pointer": "/" + m("fields.pointer"),
                "label": m("fields.label"),
                "help": m("fields.help"),
                "placeholder": m("fields.placeholder"),
                "default": m("fields.default"),
                "widget": "select",
                "options": [
                    {"value": m("fields.options.value"), "label": m("fields.options.label")}
                ],
            },
            {
                "name": m("hidden.name"),
                "label": m("hidden.label"),
                "help": m("hidden.help"),
                "default": m("hidden.default"),
                "widget": "hidden",
            },
        ],
    },
    "initial": {m("fields.pointer"): m("initial"), "field": m("initial.other")},
    "overrides": {"/field": {"help": m("overrides")}},
    "labels": {"field": {"label": m("labels")}},
    "issues": [{"pointer": m("issues.pointer"), "message": m("issues.message")}],
    "task": {
        "id": m("task.id"),
        "label": m("task.label"),
        "message": m("task.message"),
        "status": "failed",
        "progress": n("task.progress"),
        "steps": [{"label": m("task.steps.label"), "status": "done", "note": m("task.steps.note")}],
        "error": {"type": m("task.error.type"), "message": m("task.error.message")},
    },
    "file": {"id": m("file.id"), "name": m("file.name"), "mime": m("file.mime")},
    "actions": [{"id": m("actions.id"), "label": m("actions.label"), "icon": m("actions.icon")}],
    "accept": [m("accept")],
    "suggestions": [m("suggestions")],
    "commands": [{"name": m("commands.name"), "description": m("commands.description")}],
    "tools": [{"id": m("tools.id"), "label": m("tools.label")}],
    "names": {"user": m("names")},
    "marks": [{"value": 1, "label": m("marks")}],
    "sizes": [m("sizes")],
    "value": m("value"),
}
# Names a node can be sent that no component class has as a field.
SENT_ONLY = (
    "data",
    "series",
    "keys",
    "schema",
    "task",
    "tone_rows",
    "tone_cells",
    "track",
    "inline",
    "busy",
    "live_suggestions",
    "form_id",
)


def marked(name: str) -> dict[str, Any]:
    """Every prop any component has, each with its marker. ``name`` is the
    kind it is for: a table's ``keys`` are row keys and a Kbd's are the
    keys of a keyboard."""
    props: dict[str, Any] = {}
    for cls in catalogue().values():
        for field in cls.model_fields:
            if field not in ("children", "hidden", "key"):
                props[field] = m(field)
    for field in SENT_ONLY:
        props[field] = m(field)
    props.update(copy.deepcopy(SHAPED))
    if name == "Progress":
        props["value"] = n("value.number")
    return props


def said(name: str, props: dict[str, Any] | None = None) -> set[str]:
    """The markers the page as data says for a component of this kind that
    was sent these props, or every prop there is."""
    tree = Tree()
    tree.root = "root"
    tree.nodes["root"] = Node(id="root", type=name, props=props or marked(name), children=[])
    whole = outline.outline(tree, rows=5, chars=500)
    text = repr(whole) + outline.as_text(whole)
    found = set(re.findall(r"<<([^<>]+)>>", text))
    digits = re.sub(r"[,.]", "", text)
    return found | {name for number, name in NUMBERS.items() if number in digits}


def _without(value: Any, markers: set[Any]) -> Any:
    """A prop's value without the places these markers are in."""
    if isinstance(value, dict):
        return {k: _without(v, markers) for k, v in value.items() if not _is(v, markers)}
    if isinstance(value, list):
        return [_without(v, markers) for v in value if not _is(v, markers)]
    return value


def _is(value: Any, markers: set[Any]) -> bool:
    return isinstance(value, str | int) and not isinstance(value, bool) and value in markers


def _choices(annotation: Any) -> Iterator[Any]:
    """The values a field can be given that are not a text of the app's:
    the ones it names, and yes and no."""
    if annotation is bool:
        yield from (True, False)
    elif get_origin(annotation) is Literal:
        yield from get_args(annotation)
    elif get_origin(annotation) in (Union, types.UnionType):
        for inner in get_args(annotation):
            yield from _choices(inner)


def shapes(name: str) -> Iterator[dict[str, Any]]:
    """Every prop there is, and that again for each value a field of this
    kind can be given by name: what is said may hang on one of them."""
    yield marked(name)
    cls = catalogue().get(name)
    for field, info in cls.model_fields.items() if cls is not None else ():
        for value in _choices(info.annotation):
            yield {**marked(name), field: value}
    if name == "Form":
        # Each way a field can be drawn, with and without options.
        for widget in WIDGETS:
            for options in (True, False):
                props = marked(name)
                field = props["schema"]["fields"][0]
                field["widget"] = widget
                if not options:
                    del field["options"]
                yield props
    for status in ("pending", "running", "done", "failed", "cancelled"):
        props = marked(name)
        props["task"]["status"] = status
        yield props


def said_ever(name: str) -> set[str]:
    """Every marker a kind can say: what it says of every prop there is,
    in each shape, and what it says in the place of each of those when
    that one is not there, down to where taking more away brings out
    nothing new."""
    numbers = {int(number): mark for number, mark in NUMBERS.items()}
    total: set[str] = set()
    seen: list[dict[str, Any]] = []
    todo = list(shapes(name))
    while todo:
        props = todo.pop()
        if props in seen or len(seen) > 2000:
            continue
        seen.append(props)
        now = said(name, props)
        total |= now
        if not now:
            continue
        gone: set[Any] = {m(mark) for mark in now} | {
            number for number, mark in numbers.items() if mark in now
        }
        # Without the places that were said, and without each prop that
        # held one of them.
        todo.append({k: _without(v, gone) for k, v in props.items() if not _is(v, gone)})
        for prop in props:
            if repr(_without({prop: props[prop]}, gone)) != repr({prop: props[prop]}):
                todo.append({k: v for k, v in props.items() if k != prop})
    return total
