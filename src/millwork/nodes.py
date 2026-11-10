"""Components, the tree they become, and the diff between two trees.

A page function returns a ``Component``. ``build`` walks it into a ``Tree``:
a flat table of wire ``Node``s with stable ids, plus the handlers those nodes
bound. ``diff`` turns the previous and the next ``Tree`` into patch ops.

Identity: a node's id is its parent's id, a slash, and either its ``key`` or
its position among the parent's children, counting ``None`` children so a
conditional sibling does not shift the ones after it. The position carries
the component type, so a different component in the same place is a
remove and an add, never a prop update on the wrong kind of node.

A lazy part (``ui.lazy``) is a function that is called when the walk gets to
it. Where the part does not show, in a tab that is not the open one, the
walk leaves the function alone and takes the part's nodes from the tree
before, as they were when it last showed.
"""

from __future__ import annotations

import datetime as dt
import enum
import functools
import inspect
import time
import types
from collections.abc import Callable, Collection, Iterable, Mapping
from pathlib import PurePath
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    NamedTuple,
    Protocol,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import to_jsonable_python

from millwork import context
from millwork.icons import check_icon
from millwork.protocol import (
    AddOp,
    ChildrenOp,
    Node,
    PatchOp,
    RemoveOp,
    SetOp,
    SpliceOp,
    UnsetOp,
)

Handler = Callable[..., Any]
ROOT_ID = "root"


@runtime_checkable
class Wireable(Protocol):
    """Anything that knows how to appear in props: tasks, file references."""

    def __millwork_wire__(self) -> Any: ...


class Wired:
    """A ``wire_extra`` value that is JSON-ready as it stands. The tree takes it
    as it is instead of walking it again, which a table of thousands of rows
    would pay for on every render."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


class Component(BaseModel):
    """Base of every catalogue component. Subclasses set ``type``.

    Children are positional: ``Card(Text("a"), Button("b"), title="t")``. A
    bare string child becomes a ``Text``; ``None`` is skipped but keeps its
    position. Props named ``on_*`` are handlers and never reach the wire;
    the wire sees ``on_*: true`` so the bundle knows which events to emit.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    type: ClassVar[str] = "component"
    key: str | None = None
    hidden: bool = False
    cls: str | None = None
    children: list[Any] = []

    def __init__(self, *children: Any, **props: Any) -> None:
        if children and "children" in props:
            raise TypeError("children are positional or keyword, not both")
        if children:
            props["children"] = list(children)
        if "children" in props:
            props["children"] = _flatten(props["children"])
        super().__init__(**props)

    # Fields that never reach the wire as they are (a callable evaluated at
    # render, say); ``wire_extra`` supplies what goes instead.
    wire_exclude: ClassVar[frozenset[str]] = frozenset()
    # Fields whose default is a word of the framework's, by the theme string
    # that holds it: left alone, the field goes out in the theme's words.
    theme_words: ClassVar[dict[str, str]] = {}
    # What a handler receives after the session, for the props where it is not
    # one payload: a chat's feedback handler gets the message, the value and
    # the comment.
    handler_args: ClassVar[dict[str, tuple[str, ...]]] = {}
    # What the payload is, per handler prop, in the reference's words.
    payloads: ClassVar[dict[str, str]] = {}
    # True for a component that does nothing without a session behind it: it
    # talks to Python over the socket whatever its handlers are. A page drawn
    # before anyone has signed in cannot hold one.
    needs_session: ClassVar[bool] = False
    # True for a component that shows some of its children at a time, and
    # says which through ``showing``.
    shows_some: ClassVar[bool] = False

    def showing(self, told: str | None) -> Showing | None:
        """Which children show now, for a component that shows some of them
        at a time. ``told`` is what the tab last said it shows."""
        return None

    def wire_extra(self) -> dict[str, Any]:
        """Extra props computed at render time. Override in components that need it."""
        return {}

    @field_validator("icon", "prefix_icon", check_fields=False)
    @classmethod
    def _known_icon(cls, name: str | None) -> str | None:
        # The catalogue draws its own icons. A component an app defines
        # itself means by ``icon`` whatever its own renderer draws. What
        # tells the two apart is whose ``type`` the class goes by, so a
        # catalogue component an app gave another name is still checked.
        for klass in cls.__mro__:
            if klass is not Component and "type" in vars(klass):
                if klass.__module__.partition(".")[0] == "millwork":
                    return check_icon(name)
                break
        return name

    def in_theme_words(self, name: str) -> Any:
        """One of the ``theme_words`` fields as it is shown: the theme's word
        while the field holds the framework's own, otherwise its value. A
        value the app passed, or a subclass set as its default, is the app's
        even where it reads the same."""
        from millwork.theme import STRINGS

        value = getattr(self, name)
        key = self.theme_words[name]
        session = context._session.get()
        if session is None or name in self.model_fields_set or value != STRINGS[key]:
            return value
        return session.app.theme.text(key)

    def wire_type(self) -> str:
        """The node type on the wire; a custom component names its own."""
        return self.type


Tone = Literal["default", "muted", "primary", "accent", "success", "warning", "destructive"]
TextVariant = Literal["body", "muted", "caption", "label", "title", "heading", "subheading", "mono"]
TextAlign = Literal["left", "center", "right"]


class Text(Component):
    type: ClassVar[str] = "Text"
    content: str = ""
    variant: TextVariant = "body"
    truncate: bool = False
    align: TextAlign | None = None
    tone: Tone | None = None

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            content: str = "",
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            variant: TextVariant = "body",
            truncate: bool = False,
            align: TextAlign | None = None,
            tone: Tone | None = None,
        ) -> None: ...
    else:

        def __init__(self, content: str = "", **props: Any) -> None:
            super().__init__(content=content, **props)


class Showing(NamedTuple):
    """What a component that shows some of its children at a time shows now."""

    shows: Callable[[Any], bool]
    """Whether a child of it shows."""
    asks: bool
    """Whether the tab has to say what it shows, since the page does not."""


class Lazy(Component):
    """What a call of a ``ui.lazy`` function leaves in the page: the function
    and what it was called with. The walk calls it and puts what it returns
    in this place, so no node is ever a ``Lazy``."""

    type: ClassVar[str] = "Lazy"
    fn: Any = None
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = {}

    @property
    def code(self) -> Any:
        """What tells one lazy function from another across renders. A
        function defined inside the page function is a new object at every
        render and the same code."""
        return getattr(self.fn, "__code__", self.fn)

    def result(self) -> Component | None:
        """Call the function: the component it returns, or None for nothing."""
        out = self.fn(*self.args, **self.kwargs)
        name = getattr(self.fn, "__qualname__", "a lazy function")
        if inspect.isawaitable(out):
            if inspect.iscoroutine(out):
                out.close()
            raise TypeError(f"{name} is async, and a lazy part is built in one go like a page")
        if isinstance(out, Lazy):
            return out.result()
        if isinstance(out, str):
            return Text(out)
        if out is None or isinstance(out, Component):
            return out
        raise TypeError(f"{name} returned {type(out).__name__}, not a component")

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            fn: Any = None,
            args: tuple[Any, ...] = ...,
            kwargs: dict[str, Any] = ...,
        ) -> None: ...


def lazy[**P](fn: Callable[P, Component | None]) -> Callable[P, Component]:
    """Make a function that returns a part of a page lazy: the part is kept
    up to date only while it shows.

        @ui.lazy
        def history(s: mw.Session[State]) -> ui.Component:
            return ui.Table(s.state.history, columns=COLUMNS)

        ui.Tabs(
            ui.Tab(overview(s), id="overview", label="Overview"),
            ui.Tab(history(s), id="history", label="History"),
        )

    A call puts the function and its arguments in the page. The function
    runs when the page is first drawn, after that at every render in which
    its tab is the open one, and once more as the tab is left. While
    another tab is open the part stays in the browser as it was when it
    was left, and costs the render nothing. Anywhere but inside a
    ``ui.Tab`` the part is built at every render, like the rest of the
    page.

    The arguments are worked out at the call, like those of any call. The
    function follows the rule of a page function: it builds its part from
    the state, and does nothing else.
    """
    if inspect.iscoroutinefunction(fn):
        raise TypeError(
            f"{fn.__qualname__} is async, and a lazy part is built in one go like a page"
        )

    @functools.wraps(fn)
    def placed(*args: P.args, **kwargs: P.kwargs) -> Component:
        return Lazy.model_construct(fn=fn, args=args, kwargs=kwargs)

    return placed


def _built(value: Component) -> Component | None:
    """A component as it is, and a lazy one as what it comes to: for a place
    that is not among the children, where a part is built every time."""
    return value.result() if isinstance(value, Lazy) else value


class Part:
    """A lazy part of a built page: where it sits, whose result it is, and
    everything it came to, the lazy parts inside it included."""

    __slots__ = ("child", "code", "key", "kind", "shown", "tree")

    def __init__(
        self,
        key: str,
        code: Any,
        tree: Tree,
        child: str | None,
        kind: tuple[type, str] | None,
        shown: bool,
    ) -> None:
        self.key = key
        self.code = code
        self.tree = tree
        self.child = child
        # The class and wire type of what it came to, when that has no key.
        self.kind = kind
        # Whether its place showed when it was built.
        self.shown = shown


class Tree:
    """A built page: flat nodes, the handlers they bound, and the root id."""

    def __init__(self) -> None:
        self.root: str = ROOT_ID
        self.nodes: dict[str, Node] = {}
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.callables: dict[tuple[str, str], Callable[..., Any]] = {}
        self.components: dict[str, Component] = {}
        # The nodes that do nothing without a session behind them.
        self.session_bound: list[str] = []
        # Nodes whose children include a run of keyless siblings of one type, and
        # that type: a list built from data, if the run grows or shrinks later.
        self.keyless_runs: dict[str, str] = {}
        # The lazy parts in it, by where they sit, and the ones among them
        # that were not built this time but taken from the tree before.
        self.parts: dict[str, Part] = {}
        self.kept: list[Part] = []
        # Seconds spent in lazy functions while it was built.
        self.spent = 0.0

    def handler(self, node_id: str, event: str) -> Handler | None:
        return self.handlers.get((node_id, event))

    def take(self, other: Tree) -> None:
        """Everything of another tree becomes part of this one."""
        self.nodes.update(other.nodes)
        self.handlers.update(other.handlers)
        self.callables.update(other.callables)
        self.components.update(other.components)
        self.session_bound.extend(other.session_bound)
        self.keyless_runs.update(other.keyless_runs)
        self.parts.update(other.parts)

    def kept_part(self, node_id: str) -> str | None:
        """Where the lazy part sits that holds this node as it was at an
        earlier render, or None for a node that was built this time."""
        for part in self.kept:
            if node_id in part.tree.nodes:
                return part.key
        return None


def _flatten(children: Any) -> list[Any]:
    """Lists and tuples among children are spliced in, so a helper may return a list."""
    out: list[Any] = []
    for child in children:
        if isinstance(child, list | tuple):
            out.extend(_flatten(child))
        else:
            out.append(child)
    return out


class _Duplicate(ValueError):
    """Two children of one parent came to the same id."""


class _Build:
    """What one walk of a page goes by, and what it counts on the way."""

    __slots__ = ("met", "parts", "showing", "spent", "wanted")

    def __init__(
        self, parts: Mapping[str, Part], showing: Mapping[str, str], wanted: Collection[str]
    ) -> None:
        self.parts = parts
        self.showing = showing
        self.wanted = wanted
        self.met = 0
        self.spent = 0.0


def build(
    root: Component,
    root_id: str = ROOT_ID,
    *,
    last: Tree | None = None,
    showing: Mapping[str, str] | None = None,
    wanted: Collection[str] = (),
) -> Tree:
    """Walk a page into a tree.

    ``last`` is the tree the page was before. A lazy part that does not
    show now is taken from it as it stands, where it has one. ``showing``
    is what the tab said it shows, by node id, and ``wanted`` names lazy
    parts to build whether they show or not.
    """
    found = _built(root)
    if found is None:
        raise TypeError("a lazy function that is the whole page returned nothing")
    parts = last.parts if last is not None else {}
    try:
        return _build(found, root_id, _Build(parts, showing or {}, wanted))
    except _Duplicate:
        if not parts:
            raise
        # A part as it was drawn earlier can hold a key that a sibling built
        # now has taken. Built from nothing, the page is whatever it is.
        return _build(found, root_id, _Build({}, showing or {}, wanted))


def _build(root: Component, root_id: str, how: _Build) -> Tree:
    tree = Tree()
    tree.root = root_id
    _walk(root, root_id, tree, how, True)
    tree.spent = how.spent
    return tree


def _part(
    lazy: Lazy, node_id: str, index: int, tree: Tree, how: _Build, shows: bool
) -> tuple[str | None, tuple[type, str] | None]:
    """Put a lazy child of ``node_id`` into the tree, and return the id of
    what it came to, or None for nothing, with its kind for the count of
    keyless siblings.

    A part is built where it shows, where it is wanted, and where the tree
    before has nothing to take. It is built once more in the render in
    which its place stops showing, so that what is kept is the part as it
    was when it was left, with whatever the handler that left it changed.
    From the render after that it is taken as it was.
    """
    key = f"{node_id}/{index}"
    how.met += 1
    before = how.parts.get(key)
    if (
        before is not None
        and not shows
        and not before.shown
        and key not in how.wanted
        and before.code is lazy.code
        and before.tree.nodes.keys().isdisjoint(tree.nodes)
    ):
        tree.take(before.tree)
        tree.parts[key] = before
        tree.kept.append(before)
        return before.child, before.kind
    started = time.perf_counter()
    result = lazy.result()
    how.spent += time.perf_counter() - started
    # Walked into a tree of its own, which is what a later render takes over.
    inside = Tree()
    child: str | None = None
    kind: tuple[type, str] | None = None
    if result is not None:
        if result.key:
            child = f"{node_id}/{result.key}"
        else:
            kind = (type(result), result.wire_type())
            child = f"{node_id}/{index}:{kind[1]}"
        _walk(result, child, inside, how, shows)
        if not inside.nodes.keys().isdisjoint(tree.nodes):
            raise _Duplicate(f"duplicate key {result.key!r} under {node_id}")
    tree.take(inside)
    tree.kept.extend(inside.kept)
    tree.parts[key] = Part(key, lazy.code, inside, child, kind, shows)
    return child, kind


class _Shape:
    """What the walk knows of a component class before it meets one of them:
    its fields in the order they go out, each with the default an instance
    holds when it was given nothing for it."""

    __slots__ = ("events", "extra", "extras", "fields")

    def __init__(self, cls: type[Component]) -> None:
        skip = frozenset({"children", "key"}) | cls.wire_exclude
        checked = bool(cls.model_config.get("validate_default"))
        fields: list[tuple[str, Any]] = []
        for name, field in cls.model_fields.items():
            if name in skip:
                continue
            default = field.default
            if (
                name in cls.theme_words
                or field.default_factory is not None
                or type(default) not in _SCALARS
                or checked
                or field.validate_default
            ):
                # Nothing to know ahead: a word of the theme's is looked up
                # per session, a list or a dict is the instance's own copy,
                # and a default that is validated can come out as anything.
                default = _MISSING
            fields.append((name, default))
        self.fields = tuple(fields)
        self.extra = cls.wire_extra is not Component.wire_extra
        self.events = "events" in cls.model_fields or hasattr(cls, "events")
        self.extras = cls.model_config.get("extra") == "allow"


_SCALARS = frozenset({str, int, float, bool, type(None)})
_SHAPES: dict[type[Component], _Shape] = {}


def _walk(component: Component, node_id: str, tree: Tree, how: _Build, shows: bool) -> None:
    cls = type(component)
    shape = _SHAPES.get(cls)
    if shape is None:
        shape = _SHAPES[cls] = _Shape(cls)
    props: dict[str, Any] = {}
    if component.needs_session:
        tree.session_bound.append(node_id)
    given = component.model_fields_set
    values = component.__dict__
    fields = shape.fields
    if shape.extras and component.__pydantic_extra__:
        # A class of an app's own that takes props it does not declare.
        values = {**values, **component.__pydantic_extra__}
        fields += tuple((name, _MISSING) for name in component.__pydantic_extra__)
    for name, default in fields:
        value = values.get(name, _MISSING)
        if value is _MISSING:
            # An instance put together without it.
            continue
        if value is default:
            # Most props of most components are what the class gives them.
            # The very object of the default needs no looking at. That is
            # asked of the value and not of what the instance says it was
            # given, since a field can be filled in behind its back.
            if value is not None:
                props[name] = value
            elif name in given:
                props[name] = None
            continue
        if name in component.theme_words:
            value = component.in_theme_words(name)
        if callable(value) and not isinstance(value, type):
            if name.startswith("on_"):
                check_handler(name, value, component.handler_args.get(name, ("payload",)))
                tree.handlers[(node_id, name[3:])] = value
                props[name] = True
            else:
                tree.callables[(node_id, name)] = value
                props[name] = {"$callable": True}
            continue
        if isinstance(value, Component):
            value = _built(value)
            if value is not None:
                slot_id = f"{node_id}/@{name}"
                _walk(value, slot_id, tree, how, shows)
                props[name] = {"$node": slot_id}
            continue
        if isinstance(value, list) and value and all(isinstance(v, Component) for v in value):
            items: list[Any] = []
            for index, item in enumerate(value):
                item = _built(item)
                if item is None:
                    continue
                slot_id = f"{node_id}/@{name}.{item.key or index}"
                if slot_id in tree.nodes:
                    raise ValueError(f"duplicate key {item.key!r} in {name} of {node_id}")
                _walk(item, slot_id, tree, how, shows)
                items.append({"$node": slot_id})
            props[name] = items
            continue
        if value is None and name not in given:
            # Absent on the wire: a prop the page never set. An explicit ``value=None``
            # is sent as null and means "controlled, and empty".
            continue
        props[name] = wire_value(value)
    for name, value in (component.wire_extra() if shape.extra else {}).items():
        if isinstance(value, Wired):
            props[name] = value.value
        elif isinstance(value, Component):
            value = _built(value)
            if value is not None:
                slot_id = f"{node_id}/@{name}"
                _walk(value, slot_id, tree, how, shows)
                props[name] = {"$node": slot_id}
        elif (
            isinstance(value, dict)
            and value
            and all(isinstance(v, Component) for v in value.values())
        ):
            slots: dict[str, Any] = {}
            for key, child in value.items():
                child = _built(child)
                if child is None:
                    continue
                slot_id = f"{node_id}/@{name}.{key}"
                _walk(child, slot_id, tree, how, shows)
                slots[str(key)] = {"$node": slot_id}
            props[name] = slots
        else:
            props[name] = wire_value(value)
    if shape.events:
        for event, handler in getattr(component, "events", {}).items():
            tree.handlers[(node_id, event)] = handler
            props[f"on_{event}"] = True
    if props.get("hidden") is False:
        del props["hidden"]
    children_ids: list[str] = []
    view = component.showing(how.showing.get(node_id)) if cls.shows_some else None
    met = how.met
    # A run of keyless siblings of one class may be a list built from data,
    # where a change redraws every row instead of moving them. It is one
    # only when its length changes between renders, which the session sees.
    run_of: type | None = None
    run = 0
    for index, child in enumerate(component.children):
        kind: tuple[type, str] | None = None
        if child is None:
            run = 0
            continue
        inner = shows and (view is None or view.shows(child))
        if isinstance(child, Lazy):
            child_id, kind = _part(child, node_id, index, tree, how, inner)
            if child_id is not None:
                children_ids.append(child_id)
        else:
            words = isinstance(child, str)
            if words:
                child = Text(child)
            if not isinstance(child, Component):
                raise TypeError(
                    f"{type(component).__name__} child {index} is {type(child).__name__}, "
                    "not a component or a string"
                )
            if child.key:
                child_id = f"{node_id}/{child.key}"
            else:
                child_id = f"{node_id}/{index}:{child.wire_type()}"
                if not words:
                    # A bare string can take no key, so it is no row of a list.
                    kind = (type(child), child.wire_type())
            if child_id in tree.nodes:
                raise _Duplicate(f"duplicate key {child.key!r} under {node_id}")
            children_ids.append(child_id)
            _walk(child, child_id, tree, how, inner)
        if kind is None:
            run = 0
        else:
            if kind[0] is not run_of:
                run_of, run = kind[0], 0
            run += 1
            if run == KEYLESS_RUN:
                tree.keyless_runs.setdefault(node_id, kind[1])
    if view is not None and view.asks and how.met > met:
        # A lazy part below goes by what shows here, and the page does not
        # say what that is, so the tab does.
        props["track"] = True
    tree.nodes[node_id] = Node(
        id=node_id, type=component.wire_type(), props=props, children=children_ids
    )
    tree.components[node_id] = component


# Handler shapes already checked. A lambda is a new object each render and
# the same code every time, and so is a ``functools.partial`` around one
# function, so the check is one per source line and per way of filling a
# function in, not one per render.
_HANDLER_SHAPES: dict[tuple[Any, ...], str | None] = {}


def _shape_of(fn: Callable[..., Any]) -> tuple[Any, ...] | None:
    """What a handler's shape hangs on, or None for one that has to be asked
    each time: its code, whether it is bound to an object, and for a partial
    how many arguments are filled in already and which by name."""
    filled = 0
    named: frozenset[str] = frozenset()
    while isinstance(fn, functools.partial):
        filled += len(fn.args)
        named |= frozenset(fn.keywords)
        fn = fn.func
    code = getattr(fn, "__code__", None)
    if code is None:
        return None
    return (code, isinstance(fn, types.MethodType), filled, named)


def check_handler(prop: str, fn: Callable[..., Any], args: tuple[str, ...]) -> None:
    """A handler takes the session and then ``args``, one payload for most
    props. One that cannot fails here, when the tree is built, with the shape
    in the message, instead of at the click with a toast."""
    shape = _shape_of(fn)
    key = (shape, len(args))
    if shape is not None and key in _HANDLER_SHAPES:
        problem = _HANDLER_SHAPES[key]
    else:
        problem = _handler_problem(fn, 1 + len(args))
        if shape is not None:
            _HANDLER_SHAPES[key] = problem
    if problem:
        raise TypeError(f"{prop} takes a handler of (session, {', '.join(args)}); {problem}")


def _handler_problem(fn: Callable[..., Any], count: int) -> str | None:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    try:
        signature.bind(*([None] * count))
    except TypeError:
        name = getattr(fn, "__name__", type(fn).__name__)
        return f"{name}{signature} does not take {count} positional arguments"
    return None


_PLAIN = frozenset({str, int, float, bool, type(None)})


def wire_value(value: Any) -> Any:
    """Turn a prop value into JSON-ready data."""
    # The plain types first, by exact type: most of what a page sends is these,
    # and a list of rows is thousands of them.
    kind = type(value)
    if kind in _PLAIN:
        return value
    if kind is dict:
        return {k if type(k) is str else str(k): wire_value(v) for k, v in value.items()}
    if kind is list or kind is tuple:
        return [wire_value(v) for v in value]
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Wireable):
        return value.__millwork_wire__()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): wire_value(v) for k, v in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, bytes | bytearray):
        return [wire_value(v) for v in value]
    try:
        return to_jsonable_python(value)
    except Exception as exc:
        raise TypeError(f"cannot send a {type(value).__name__} as a prop") from exc


def diff(old: Tree | None, new: Tree) -> list[PatchOp]:
    """Patch ops that take the client from ``old`` to ``new``.

    Adds come first so references resolve, then updates, then removes.
    """
    if old is None:
        raise ValueError("diff needs a previous tree; use a mount for the first render")
    ops: list[PatchOp] = []
    for node_id, node in new.nodes.items():
        if node_id not in old.nodes:
            ops.append(AddOp(node=node))
    for node_id, node in new.nodes.items():
        before = old.nodes.get(node_id)
        if before is None or before is node:
            # New, which was said above, or the very node of the tree before:
            # a lazy part that was taken over as it was.
            continue
        if before.type != node.type:
            ops.append(RemoveOp(id=node_id))
            ops.append(AddOp(node=node))
            continue
        changed = {k: v for k, v in node.props.items() if before.props.get(k, _MISSING) != v}
        for name in list(changed):
            was, now = before.props.get(name), changed[name]
            if type(was) is list and type(now) is list and len(now) >= SPLICE_MIN:
                edits = _edits(was, now)
                if edits is not None:
                    del changed[name]
                    ops.append(SpliceOp(id=node_id, prop=name, edits=edits))
        if changed:
            ops.append(SetOp(id=node_id, props=changed))
        gone = [k for k in before.props if k not in node.props]
        if gone:
            ops.append(UnsetOp(id=node_id, keys=gone))
        if before.children != node.children:
            ops.append(ChildrenOp(id=node_id, children=node.children))
    for node_id in old.nodes:
        if node_id not in new.nodes:
            ops.append(RemoveOp(id=node_id))
    return ops


# A list at least this long is patched by its changes when that is less to send
# than the list: a table's rows, a chart's points.
SPLICE_MIN = 16


def _edits(old: list[Any], new: list[Any]) -> list[tuple[int, int, list[Any]]] | None:
    """What turns ``old`` into ``new``, as ``(start, delete, items)`` in positions
    of ``old``, ascending. ``None`` when that is more than half the list, since
    then the list itself is as good. Lists of one length are compared place by
    place, so cells changed here and there are each their own edit; a list that
    grew or shrank is one edit between what its two ends still share, which is
    an append, an insert or a removal."""
    n_old, n_new = len(old), len(new)
    edits: list[tuple[int, int, list[Any]]] = []
    sent = 0
    if n_old == n_new:
        i = 0
        while i < n_new:
            if old[i] == new[i]:
                i += 1
                continue
            j = i + 1
            while j < n_new and old[j] != new[j]:
                j += 1
            edits.append((i, j - i, new[i:j]))
            sent += j - i
            i = j
    else:
        shared = min(n_old, n_new)
        head = 0
        while head < shared and old[head] == new[head]:
            head += 1
        tail = 0
        while tail < shared - head and old[n_old - 1 - tail] == new[n_new - 1 - tail]:
            tail += 1
        edits.append((head, n_old - head - tail, new[head : n_new - tail]))
        sent = n_new - head - tail
    return None if sent * 2 > n_new else edits


def apply(nodes: dict[str, Node], ops: list[PatchOp]) -> dict[str, Node]:
    """Apply patch ops to a node table, the way the bundle does. For tests."""
    out = {k: v.model_copy(deep=True) for k, v in nodes.items()}
    for op in ops:
        if isinstance(op, AddOp):
            out[op.node.id] = op.node.model_copy(deep=True)
        elif isinstance(op, RemoveOp):
            out.pop(op.id, None)
        elif isinstance(op, SetOp):
            out[op.id].props.update(op.props)
        elif isinstance(op, SpliceOp):
            old = out[op.id].props[op.prop]
            new: list[Any] = []
            at = 0
            for start, delete, items in op.edits:
                new += old[at:start]
                new += items
                at = start + delete
            out[op.id].props[op.prop] = new + old[at:]
        elif isinstance(op, UnsetOp):
            for k in op.keys:
                out[op.id].props.pop(k, None)
        elif isinstance(op, ChildrenOp):
            out[op.id].children = list(op.children)
    return out


_MISSING = object()


# A run of this many keyless siblings of one class is taken for a list that may
# have been built from data.
KEYLESS_RUN = 4
