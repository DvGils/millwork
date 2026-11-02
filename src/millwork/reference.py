"""The catalogue as a lookup table: every component with its props, their
types and defaults, the models they take, the session's and the app's
calls, the icon names, the form widgets and the formats. ``millwork
reference`` prints it and the manual serves it at ``/llms.txt``, for a
reader, human or model, who needs the shape of a thing rather than a
chapter about it."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from millwork import ui
from millwork.app import App, PageDef
from millwork.forms import WIDGETS
from millwork.icons import ICONS
from millwork.nodes import Component
from millwork.session import Session
from millwork.theme import Theme
from millwork.ui.table import Format

MODELS = (
    ui.Option,
    ui.Column,
    ui.MenuItem,
    ui.Command,
    ui.Action,
    ui.Accept,
    ui.FileRef,
    ui.Issue,
)
SESSION_API = (
    "text",
    "toast",
    "navigate",
    "navigate_to",
    "clipboard",
    "download",
    "logout",
    "reset",
    "refresh",
    "task",
    "thread",
    "later",
    "spawn",
    "ask",
    "confirm",
    "chat",
    "drop_chat",
    "end",
)
APP_API = (
    "page",
    "not_found",
    "forbidden",
    "route",
    "mount",
    "middleware",
    "on_startup",
    "on_shutdown",
)


def reference() -> str:
    """The whole reference as Markdown."""
    from millwork import __version__

    out = [
        f"# millwork {__version__} reference",
        "",
        "A page is a Python function of the session's state that returns a tree of",
        "components. A handler bound to an `on_*` prop takes `(session, payload)` and",
        "may be sync or async; the page renders again when it returns. Children are",
        "positional: `ui.Card(ui.Text('a'), ui.Button('b'), title='t')`. Every",
        "component takes `key`, `hidden` and `cls` (Tailwind classes). A prop a",
        "component does not have is refused. The manual at millwork-ui.com explains",
        "each chapter; this is the table of what exists.",
        "",
        "## Components",
        "",
    ]
    for name in ui.__all__:
        obj = getattr(ui, name)
        if isinstance(obj, type) and issubclass(obj, Component) and obj is not Component:
            out.extend(_component(name, obj))
    out += ["## Models components take", ""]
    for model in MODELS:
        out.extend(_model(f"ui.{model.__name__}", model))
    out += [
        "## The session",
        "",
        "`s` in a page or handler. `s.state` is the session's instance of the model",
        "the app declares, kept across pages. `s.user` is the signed-in user or",
        "`None`, `s.params` the URL's parameters, `s.files` the session's files,",
        "`s.tasks` its tasks.",
        "",
    ]
    for name in SESSION_API:
        out.append(_call(f"s.{name}", getattr(Session, name)))
    out += ["", "## The app", "", "`mw.App" + _signature(App.__init__, skip_self=True) + "`", ""]
    for name in APP_API:
        out.append(_call(f"app.{name}", getattr(App, name)))
    out.append(_call("page.connect", PageDef.connect))
    out.append(_call("page.close", PageDef.close))
    out += ["", "## The theme", "", "`public/theme.json`, or `App(theme=)`.", ""]
    out.extend(_fields(Theme))
    out += [
        "",
        "## Form widgets",
        "",
        "`ui.Form(overrides={'/field': {'widget': ...}})` picks one of:",
        "",
        ", ".join(f"`{w}`" for w in WIDGETS),
        "",
        "## Formats",
        "",
        "`ui.Column(format=)` and a chart's `format=`:",
        "",
        ", ".join(f"`{f}`" for f in get_args(Format)),
        "",
        "## Icons",
        "",
        "The `icon` of a button, link, tab, badge, stat, alert, menu item or option,",
        "by lucide's name. Any other name is refused.",
        "",
        ", ".join(ICONS),
        "",
    ]
    return "\n".join(out)


def _component(name: str, cls: type[Component]) -> list[str]:
    out = [f"### ui.{name}", ""]
    doc = _own_doc(cls)
    if doc:
        out += [doc, ""]
    positional = _positional(cls)
    head = [
        *(f"{p}={d!r}" if d is not inspect.Parameter.empty else p for p, d in positional.items()),
        "*children",
    ]
    out += [f"`ui.{name}({', '.join(head)}, **props)`", ""]
    out.extend(
        _fields(
            cls,
            skip=frozenset({"key", "hidden", "cls", "children"}),
            handler_args=cls.handler_args,
            positional=positional,
        )
    )
    out.append("")
    return out


def _own_doc(cls: type) -> str:
    """The first paragraph of the class's own docstring, not an inherited one."""
    doc = cls.__dict__.get("__doc__")
    return inspect.cleandoc(doc).split("\n\n")[0].replace("\n", " ") if doc else ""


def _positional(cls: type[Component]) -> dict[str, Any]:
    """The parameters before ``*children`` of the nearest explicit ``__init__``,
    with their defaults."""
    for klass in cls.__mro__:
        if klass is Component:
            break
        init = klass.__dict__.get("__init__")
        if init is None:
            continue
        return {
            p.name: p.default
            for p in list(inspect.signature(init).parameters.values())[1:]
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        }
    return {}


def _model(name: str, model: type[BaseModel]) -> list[str]:
    out = [f"### {name}", ""]
    doc = _own_doc(model)
    if doc:
        out += [doc, ""]
    out.extend(_fields(model))
    out.append("")
    return out


def _fields(
    model: type[BaseModel],
    skip: frozenset[str] = frozenset(),
    handler_args: dict[str, tuple[str, ...]] | None = None,
    positional: dict[str, Any] | None = None,
) -> list[str]:
    out = []
    for fname, field in model.model_fields.items():
        if fname in skip or fname.startswith("_"):
            continue
        if fname.startswith("on_"):
            args = (handler_args or {}).get(fname, ("payload",))
            out.append(f"- `{fname}`: handler `(session, {', '.join(args)})`")
            continue
        line = f"- `{fname}: {_type(field.annotation)}`"
        given = (positional or {}).get(fname, inspect.Parameter.empty)
        if given is not inspect.Parameter.empty:
            line += f" = `{given!r}`"
        elif field.default is not PydanticUndefined:
            line += f" = `{field.default!r}`"
        elif field.default_factory is not None:
            try:
                line += f" = `{field.default_factory()!r}`"  # type: ignore[call-arg]
            except TypeError:
                line += " = `...`"
        else:
            line += " (required)"
        if field.description:
            line += f". {field.description}"
        out.append(line)
    return out


def _call(name: str, fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn)
    first = doc.split("\n\n")[0].replace("\n", " ") if doc else ""
    return f"- `{name}{_signature(fn, skip_self=True)}`" + (f": {first}" if first else "")


def _signature(fn: Callable[..., Any], skip_self: bool) -> str:
    params = list(inspect.signature(fn).parameters.values())
    if skip_self and params and params[0].name in ("self", "cls"):
        params = params[1:]
    parts = []
    for p in params:
        text = p.name
        if p.kind is p.VAR_POSITIONAL:
            text = "*" + text
        elif p.kind is p.VAR_KEYWORD:
            text = "**" + text
        elif p.default is not p.empty:
            text += f"={p.default!r}"
        parts.append(text)
    return "(" + ", ".join(parts) + ")"


def _type(t: Any) -> str:
    if t is None or t is type(None):
        return "None"
    origin = get_origin(t)
    if origin is Literal:
        return " | ".join(repr(a) for a in get_args(t))
    if origin in (Union, UnionType):
        return " | ".join(_type(a) for a in get_args(t))
    if origin is not None:
        name = getattr(origin, "__name__", str(origin))
        args = get_args(t)
        if name == "Callable" and args:
            return "callable"
        return f"{name}[{', '.join(_type(a) for a in args)}]" if args else name
    if isinstance(t, type):
        return t.__name__
    return str(t).replace("typing.", "")
