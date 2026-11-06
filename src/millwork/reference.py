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
from millwork.auth import Auth, AzureAD, Dev, Google, Headers, OAuth, Password
from millwork.forms import WIDGETS
from millwork.icons import ICONS
from millwork.nodes import Component
from millwork.session import Session
from millwork.tasks import Reporter, StepHandle, Task
from millwork.testing import Page
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
TASK_API = ("done", "ok", "cancelled", "result", "cancel")
REPORTER_API = ("set", "plan", "step", "check")
PAGE_API = (
    "find",
    "find_all",
    "text",
    "click",
    "change",
    "submit",
    "select",
    "choose",
    "action",
    "upload",
    "send",
    "stop",
    "answer",
    "toast_action",
    "navigate",
    "event",
    "settle",
    "stream",
)


def reference() -> str:
    """The whole reference as Markdown."""
    from millwork import __version__

    out = [
        f"# millwork {__version__} reference",
        "",
        "A page is a Python function of the session's state that returns a tree of",
        "components. A handler bound to an `on_*` prop takes `(session, payload)` and",
        "may be sync or async; the page renders again when it returns. Each handler",
        "below says what its payload is. Children are positional:",
        "`ui.Card(ui.Text('a'), ui.Button('b'), title='t')`. Every component takes",
        "`key`, `hidden` and `cls` (Tailwind classes). A prop a component does not",
        "have is refused, and so is an icon name lucide does not have. The manual at",
        "millwork-ui.com explains each chapter; this is the table of what exists.",
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
        "`s` in a page or handler, or `mw.session()` from code that was not handed",
        "it. `s.state` is the session's instance of the model the app declares,",
        "kept across pages. `s.user` is the signed-in user or `None`, `s.path` the",
        "page's path, `s.params` the URL's parameters, `s.files` the session's",
        "files, `s.tasks` the list of its tasks.",
        "",
    ]
    for name in SESSION_API:
        out.append(_call(f"s.{name}", getattr(Session, name)))
    out += [
        "",
        "## Tasks",
        "",
        "`s.task(work)` returns a `mw.Task` and runs `work`, a coroutine or a sync",
        "function in a thread. Its `label`, `status` (`pending`, `running`, `done`,",
        "`failed`, `cancelled`), `progress`, `steps` and `error` show in",
        "`ui.Progress(task=)` and `ui.Steps(task=)`. `await task` gives the result.",
        "`on_done` is called as a handler with the task, not the result.",
        "",
    ]
    for name in TASK_API:
        out.append(_call(f"task.{name}", getattr(Task, name)))
    out += [
        "",
        "Inside the work, `mw.progress()` is the task's reporter, and does nothing",
        "outside a task. `raise mw.Cancelled` or `p.check()` ends a cancelled task.",
        "",
    ]
    for name in REPORTER_API:
        out.append(_call(f"p.{name}", getattr(Reporter, name)))
    out.append(_call("step.note", StepHandle.note))
    out += [
        "",
        "## Forms",
        "",
        "`ui.Form(Model, on_submit=)` builds the fields from a Pydantic model and",
        "hands the handler a validated instance. The handler rejects it with",
        "`raise ui.FormIssues([('/field', 'message')])`, which the form shows at",
        "the field.",
        "",
        "## The app",
        "",
        "`mw.App" + _signature(App.__init__, skip_self=True) + "`",
        "",
        "A page's path takes parameters: `/items/{id}` is a string, `{id:int}`,",
        "`{id:float}`, `{id:uuid}` convert, `{rest:path}` takes the remainder.",
        "They reach the page's `connect(session, **params)` and `s.params`. A",
        "connect hook raises `mw.NotFound(message)` or `mw.Forbidden(message)` to",
        "land the session on the app's not-found or forbidden page.",
        "",
    ]
    for name in APP_API:
        out.append(_call(f"app.{name}", getattr(App, name)))
    out.append(_call("page.connect", PageDef.connect))
    out.append(_call("page.close", PageDef.close))
    out += [
        "",
        "## Signing in",
        "",
        "`from millwork import auth`, then `App(auth=auth.Auth([...providers]))`.",
        "With auth every page asks for a login except one marked `public=True`,",
        "and `s.user` is the `auth.User`. `on_login(identity)` returns the `User`",
        "to admit or `None` to refuse. `on_logout(user)` returns where the tab",
        "goes after sign-out, a path or a URL, or `None` for the login page, and",
        "is asked as well when a sign-in expires under an open tab. `login=` lays",
        "the login page out from",
        "components that need no session, with a `ui.SignIn(provider_id)` where",
        "each way in goes.",
        "",
        "- `auth.Auth" + _signature(Auth.__init__, skip_self=True) + "`",
        "- `auth.AzureAD" + _signature(AzureAD, skip_self=False) + "`",
        "- `auth.Google" + _signature(Google, skip_self=False) + "`",
        "- `auth.OAuth" + _signature(OAuth.__init__, skip_self=True) + "`. `icon` is",
        "  `microsoft`, `google`, the path of an image under `public/`, or an icon name.",
        "- `auth.Password" + _signature(Password.__init__, skip_self=True) + "`",
        "- `auth.Headers" + _signature(Headers.__init__, skip_self=True) + "`",
        "- `auth.Dev" + _signature(Dev.__init__, skip_self=True) + "`",
        "",
    ]
    out += [
        "",
        "## Testing",
        "",
        "`from millwork.testing import TestApp`. `async with TestApp(app).open(path,",
        "user=) as page` opens a page as a session with no socket; what the app's",
        "code raises is raised in the test, or with `strict=False` collected in",
        "`page.failures`. `page.find(key or type, within=)` gives a node with",
        "`.props`, and `.rows` on a table. `page.state`, `page.toasts`, `page.commands` and",
        "`page.stream` are what the tab would have seen. A handler that calls",
        "`s.confirm` or `s.ask` waits for `page.answer(value)`.",
        "",
    ]
    for name in PAGE_API:
        out.append(_call(f"page.{name}", getattr(Page, name)))
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
            payloads=cls.payloads,
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
    payloads: dict[str, str] | None = None,
) -> list[str]:
    out = []
    for fname, field in model.model_fields.items():
        if fname in skip or fname.startswith("_"):
            continue
        if fname.startswith("on_"):
            args = (handler_args or {}).get(fname, ("payload",))
            line = f"- `{fname}`: handler `(session, {', '.join(args)})`"
            what = (payloads or {}).get(fname)
            if what:
                line += f", {'payload' if args == ('payload',) else 'arguments'} {what}"
            out.append(line)
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


def _call(name: str, fn: Callable[..., Any] | property) -> str:
    """A method as `name(args)`, a property as `name`, each with its docstring's first paragraph."""
    if isinstance(fn, property):
        doc = inspect.getdoc(fn.fget)
        call = ""
    else:
        doc = inspect.getdoc(fn)
        call = _signature(fn, skip_self=True)
    first = doc.split("\n\n")[0].replace("\n", " ") if doc else ""
    return f"- `{name}{call}`" + (f": {first}" if first else "")


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
