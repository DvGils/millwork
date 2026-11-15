"""The catalogue as a lookup table: every component with its props, their
types and defaults, the models they take, the session's and the app's
calls, the icon names, the form widgets and the formats. ``millwork
reference`` prints it and the manual serves it at ``/llms.txt``, for a
reader, human or model, who needs the shape of a thing rather than a
chapter about it."""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
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
from millwork.signal import Signal
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
    "can",
    "clipboard",
    "print",
    "download",
    "logout",
    "reset",
    "focus",
    "highlight",
    "outline",
    "named",
    "refresh",
    "follow",
    "connected",
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
    "spawn",
)
TASK_API = ("done", "ok", "cancelled", "result", "cancel")
REPORTER_API = ("set", "plan", "step", "log", "check")
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
    "request",
    "settle",
    "stream",
    "outline",
    "marks",
    "touch",
    "time_out",
)


# What a thing is called elsewhere, by its name here: the words someone
# who knows another framework, or the web, looks for it by. Several words
# between two commas are one name, found whole.
ALIASES = {
    "The reference": "cls, key, hidden, children, positional, handler, payload, tailwind classes",
    "ui.Accordion": "collapse, expand, faq, disclosure",
    "ui.Alert": "banner, callout, notice, warning message",
    "ui.Assistant": "chat bubble, floating chat, copilot, helper widget",
    "ui.Badge": "chip, tag, pill, status",
    "ui.BarChart": "chart, graph, plot, histogram, visualization",
    "ui.AreaChart": "chart, graph, plot, visualization",
    "ui.LineChart": "chart, graph, plot, time series, visualization",
    "ui.PieChart": "chart, graph, donut, visualization",
    "ui.Button": "click, action, submit, cta",
    "ui.Card": "panel, box, tile, container",
    "ui.Chat": "llm, assistant, messages, conversation, streaming, prompt, chatbot",
    "ui.Checkbox": "tick, check, boolean",
    "ui.Code": "code block, snippet, syntax highlighting, pre",
    "ui.Collapsible": "expand, collapse, disclosure, details, expander",
    "ui.Combobox": "autocomplete, typeahead, searchable dropdown",
    "ui.Custom": "react component, javascript, jsx, plugin, extension",
    "ui.DatePicker": "calendar, date range, date input",
    "ui.Dialog": "modal, popup, overlay, lightbox",
    "ui.Download": "export, save a file, csv",
    "ui.DropdownMenu": "context menu, actions menu, kebab, more options",
    "ui.Empty": "empty state, no data, nothing here, blank slate",
    "ui.FileUpload": "upload, dropzone, attach, drag and drop, file uploader",
    "ui.Form": "pydantic, model, validation, fields, schema",
    "ui.Grid": "columns, responsive layout",
    "ui.Header": "navbar, top bar, app bar",
    "ui.Image": "picture, img, photo",
    "ui.Input": "text field, textbox, text input, search box, debounce",
    "ui.Kbd": "keycap, keyboard key, key hint",
    "ui.Link": "anchor, href, url",
    "ui.Markdown": "rich text, formatted text",
    "ui.MultiSelect": "multi select, tags, chips, several choices",
    "ui.NumberInput": "number, stepper, numeric",
    "ui.Page": "layout, shell, frame, root",
    "ui.Progress": "progress bar, loading, percentage",
    "ui.RadioGroup": "radio buttons, single choice",
    "ui.Row": "horizontal, flex, inline",
    "ui.ScrollArea": "scroll, overflow",
    "ui.Select": "dropdown, picker, selectbox, choice, option",
    "ui.Sheet": "drawer, side panel, slide-over",
    "ui.Sidebar": "navigation, nav, menu, drawer",
    "ui.Skeleton": "loading placeholder, shimmer",
    "ui.Slider": "range",
    "ui.Spinner": "loading, busy, wait",
    "ui.Split": "resizable panes, splitter",
    "ui.Stack": "vertical, flex, column, div, container",
    "ui.Stat": "kpi, metric, big number, dashboard number, tile",
    "ui.Steps": "stepper, wizard, timeline",
    "ui.Switch": "toggle, on off, boolean",
    "ui.Table": "grid, datatable, dataframe, data editor, rows, sort, filter, pagination",
    "ui.Tabs": "tab strip, tabbed",
    "ui.Text": "label, paragraph, write, span, heading",
    "ui.Textarea": "multiline, long text",
    "ui.ToggleGroup": "segmented control, button group",
    "ui.Tooltip": "hint, hover, title",
    "s.toast": "notification, notify, snackbar, flash message, sonner",
    "s.confirm": "are you sure, yes no, alert dialog, confirmation",
    "s.ask": "prompt, modal, question, input dialog",
    "s.highlight": "spotlight, tour, point at, coach mark, onboarding, guide",
    "s.outline": "page content, dom, accessibility tree, agent context",
    "s.focus": "cursor, keyboard, autofocus",
    "s.navigate": "redirect, route, go to, switch page, location",
    "s.navigate_to": "redirect, route, go to, await",
    "s.refresh": "rerender, rerun, update, redraw",
    "s.follow": "subscribe, live update, realtime",
    "mw.Signal": "broadcast, pubsub, publish, subscribe, realtime, other sessions, shared",
    "s.task": "background job, async, worker, long running",
    "s.thread": "background, blocking, sync, freezing the page",
    "s.later": "timer, delay, timeout, interval",
    "s.download": "export, save a file",
    "s.clipboard": "copy, paste, copied",
    "s.logout": "sign out, log out",
    "app.route": "api, endpoint, rest, http, webhook",
    "app.mount": "asgi, fastapi, starlette, sub app, static files",
    "app.middleware": "request hook, cors",
    "app.spawn": "background listener, startup worker",
    "app.on_startup": "lifespan, init, boot",
    "app.on_shutdown": "lifespan, cleanup, exit",
}


# The names a part of the reference speaks of in its own words, and that
# have no entry of their own: asked for by one of them, the part is given.
NAMED_IN = {
    "The app": ("mw.App", "mw.NotFound", "mw.Forbidden"),
    "The session": ("mw.session", "s.state", "s.user", "s.path", "s.params", "s.files", "s.tasks"),
    "Tasks": ("mw.Task", "mw.progress", "mw.Cancelled"),
    "Lazy parts": ("ui.lazy",),
    "Forms": ("ui.FormIssues",),
    "Testing": ("TestApp",),
    "Models components take": ("ui.Tone",),
}
# What stands before the first part: how a page, a handler and a
# component are written.
OPENING = "The reference"


@dataclass(frozen=True)
class Entry:
    """One thing the reference has: a component, a model, a call, or what a
    part says before its list. ``names`` are the other names it is asked
    for by."""

    name: str
    part: str
    text: str
    aliases: str = ""
    names: tuple[str, ...] = ()


# The calls the reference lists, by the name each is listed under.
_CALLS: dict[str, Callable[..., Any] | property] = {}
_BULLET = re.compile(r"- `([A-Za-z_][\w.]*)[(`]")


@functools.lru_cache(maxsize=1)
def entries() -> list[Entry]:
    """The reference cut into what can be looked up by name. A call comes
    with all its docstring says, where the reference has its first words."""
    out: list[Entry] = []
    part = name = OPENING
    block: list[str] = []

    def close() -> None:
        text = "\n".join(block).strip()
        if text:
            names = NAMED_IN.get(name, ()) if name == part else ()
            out.append(Entry(name, part, text, ALIASES.get(name, ""), names))
        block.clear()

    for line in reference().splitlines():
        call = _BULLET.match(line)
        said = call.group(1) if call else ""
        listed = part not in ("Components", "Models components take")
        if line.startswith("## "):
            close()
            part = name = line[3:]
        elif line.startswith("### "):
            close()
            name = line[4:]
        elif said in _CALLS:
            fn = _CALLS[said]
            doc = inspect.getdoc(fn.fget if isinstance(fn, property) else fn) or ""
            signature = "" if isinstance(fn, property) else _signature(fn, skip_self=True)
            out.append(Entry(said, part, f"`{said}{signature}`\n\n{doc}", ALIASES.get(said, "")))
        elif listed and "." in said:
            # A call the reference writes out itself: a sign-in provider.
            out.append(Entry(said, part, line[2:], ALIASES.get(said, "")))
        elif not line.startswith("# "):
            block.append(line)
    close()
    return out


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
        "`millwork reference <words>` gives what this table and the manual say of",
        "one thing, and `millwork reference --index` lists the names.",
        "",
        "## Components",
        "",
    ]
    for name in ui.__all__:
        obj = getattr(ui, name)
        if isinstance(obj, type) and issubclass(obj, Component) and obj is not Component:
            out.extend(_component(name, obj))
    out += [
        "## Lazy parts",
        "",
        "`@ui.lazy` on a function that returns a component makes its part of the",
        "page lazy. A call, `history(s)`, goes where a child goes. The function runs",
        "when the page is first drawn and then at every render in which the `ui.Tab`",
        "it sits in is the open one. While another tab is open the part stays in the",
        "browser as it was when the tab was left and a render skips it. Outside a `ui.Tab` it",
        "is built at every render. The function builds from the state and does no",
        "I/O, like a page function, and its arguments are worked out at every",
        "render. A `ui.Tab` itself is not lazy.",
        "",
    ]
    out += [
        "## Models components take",
        "",
        "`ui.Tone` is the type of every `tone`: "
        + ", ".join(f"`{tone}`" for tone in get_args(ui.Tone))
        + ". It annotates a table of tones an app keeps, as in `dict[str, ui.Tone]`.",
        "",
    ]
    for model in MODELS:
        out.extend(_model(f"ui.{model.__name__}", model))
    out += [
        "## The session",
        "",
        "`s` in a page or handler, or `mw.session()` from code that was not handed",
        "it. `s.state` is the session's instance of the model the app declares,",
        "kept across pages. `s.user` is the signed-in user or `None`, `s.path` the",
        "page's path, `s.params` the URL's parameters, `s.files` the session's",
        "files, `s.tasks` the list of its tasks. With `App(identify_visitors=True)`",
        "`s.visitor.id` names the browser the session was opened from, the same",
        "in every tab of it, signed in or not. The id comes from a signed cookie,",
        "and an app without sign-in pins what it keeps outside the session to it.",
        "A route of the app's own finds the same visitor in",
        "`request.state.visitor`, or `None` for a browser that brought no id.",
        "",
    ]
    for name in SESSION_API:
        out.append(_call(f"s.{name}", getattr(Session, name)))
    signal = (inspect.getdoc(Signal) or "").split("\n\n")[0].replace("\n", " ")
    out.append(f"- `mw.Signal()`: {signal}")
    _CALLS["mw.Signal"] = Signal
    out.append(_call("signal.fire", Signal.fire))
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
        "outside a task. `task.cancel()` stops a coroutine at the await it is",
        "waiting on. Work in a thread cannot be stopped from outside, and ends at",
        "its next `p.check()`, or when it raises `mw.Cancelled` itself.",
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
        "to admit or `None` to refuse. `allow=` on a page, a route or a mount is",
        "a plain function of the user, and of the path parameters it names, that",
        "returns `True` for who may open it. It is asked at every way in, and",
        "`s.can(path)` asks it for a link. Routes and mounts need a sign-in",
        "unless `public=True`. `recheck(user)` returns the user as they are now,",
        "or `None` to end the sign-in, asked at most once per `recheck_every`.",
        "`on_logout(user)` returns where the tab",
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
        "`page.failures`. `page.find(key or type, within=, **props)` gives a node with",
        "`.props`, and `.rows` on a table. On a `ui.Custom` what was given in `props=` is",
        "in `.props` itself, as `.props['zoom']`, and `page.event(node, name, payload)`",
        "sends one of its events. `page.state`, `page.toasts`, `page.commands` and",
        "`page.stream` are what the tab would have seen. A handler that calls",
        "`s.confirm` or `s.ask` waits for `page.answer(value)`. `open(path,",
        "visitor=)` opens the page from a browser with that visitor id, and two",
        "pages opened with the same one are two tabs of it.",
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
        "and the name of a `ui.Icon`, by lucide's name. Any other name is refused.",
        "An icon is also a file of the app's own under `public/`, by its path, such",
        "as `/public/icons/rocket.svg`. The path starts with `/public/`, holds no",
        "segment that starts with a dot, and ends in `.svg`, `.png`, `.webp` or",
        "`.jpg`. An SVG is drawn in the text's color and any other image as it is.",
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
    _CALLS[name] = fn
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
    # A session's method that is a function of its own module takes the
    # session as ``s``.
    if skip_self and params and params[0].name in ("self", "cls", "s"):
        params = params[1:]
    parts = []
    starred = False
    for p in params:
        text = p.name
        if p.kind is p.KEYWORD_ONLY and not starred:
            # What follows is given by name.
            parts.append("*")
            starred = True
        if p.kind is p.VAR_POSITIONAL:
            text = "*" + text
            starred = True
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
