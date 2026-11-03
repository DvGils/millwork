"""Components, the tree they become, and the diff between two trees.

A page function returns a ``Component``. ``build`` walks it into a ``Tree``:
a flat table of wire ``Node``s with stable ids, plus the handlers those nodes
bound. ``diff`` turns the previous and the next ``Tree`` into patch ops.

Identity: a node's id is its parent's id, a slash, and either its ``key`` or
its position among the parent's children, counting ``None`` children so a
conditional sibling does not shift the ones after it. The position carries
the component type, so a different component in the same place is a
remove and an add, never a prop update on the wrong kind of node.
"""

from __future__ import annotations

import datetime as dt
import enum
import inspect
from collections.abc import Callable, Iterable, Mapping
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import to_jsonable_python

from millwork.icons import check_icon
from millwork.protocol import AddOp, ChildrenOp, Node, PatchOp, RemoveOp, SetOp, UnsetOp

Handler = Callable[..., Any]
ROOT_ID = "root"


@runtime_checkable
class Wireable(Protocol):
    """Anything that knows how to appear in props: tasks, file references."""

    def __millwork_wire__(self) -> Any: ...


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
    # What a handler receives after the session, for the props where it is not
    # one payload: a chat's feedback handler gets the message, the value and
    # the comment.
    handler_args: ClassVar[dict[str, tuple[str, ...]]] = {}
    # What the payload is, per handler prop, in the reference's words.
    payloads: ClassVar[dict[str, str]] = {}

    def wire_extra(self) -> dict[str, Any]:
        """Extra props computed at render time. Override in components that need it."""
        return {}

    @field_validator("icon", "prefix_icon", check_fields=False)
    @classmethod
    def _known_icon(cls, name: str | None) -> str | None:
        # The catalogue draws lucide icons. A component an app defines itself
        # means by ``icon`` whatever its own renderer draws.
        if cls.__module__.partition(".")[0] != "millwork":
            return name
        return check_icon(name)

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


class Tree:
    """A built page: flat nodes, the handlers they bound, and the root id."""

    def __init__(self) -> None:
        self.root: str = ROOT_ID
        self.nodes: dict[str, Node] = {}
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.callables: dict[tuple[str, str], Callable[..., Any]] = {}
        self.components: dict[str, Component] = {}
        # Nodes whose children include a run of keyless siblings of one type, and
        # that type: a list built from data, if the run grows or shrinks later.
        self.keyless_runs: dict[str, str] = {}

    def handler(self, node_id: str, event: str) -> Handler | None:
        return self.handlers.get((node_id, event))


def _flatten(children: Any) -> list[Any]:
    """Lists and tuples among children are spliced in, so a helper may return a list."""
    out: list[Any] = []
    for child in children:
        if isinstance(child, list | tuple):
            out.extend(_flatten(child))
        else:
            out.append(child)
    return out


def build(root: Component, root_id: str = ROOT_ID) -> Tree:
    tree = Tree()
    tree.root = root_id
    _walk(root, root_id, tree)
    return tree


def _walk(component: Component, node_id: str, tree: Tree) -> None:
    props: dict[str, Any] = {}
    for name, value in component:
        if name in ("children", "key") or name in component.wire_exclude:
            continue
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
            slot_id = f"{node_id}/@{name}"
            _walk(value, slot_id, tree)
            props[name] = {"$node": slot_id}
            continue
        if isinstance(value, list) and value and all(isinstance(v, Component) for v in value):
            items: list[Any] = []
            for index, item in enumerate(value):
                slot_id = f"{node_id}/@{name}.{item.key or index}"
                if slot_id in tree.nodes:
                    raise ValueError(f"duplicate key {item.key!r} in {name} of {node_id}")
                _walk(item, slot_id, tree)
                items.append({"$node": slot_id})
            props[name] = items
            continue
        if value is None and name not in component.model_fields_set:
            # Absent on the wire: a prop the page never set. An explicit ``value=None``
            # is sent as null and means "controlled, and empty".
            continue
        props[name] = wire_value(value)
    for name, value in component.wire_extra().items():
        if isinstance(value, Component):
            slot_id = f"{node_id}/@{name}"
            _walk(value, slot_id, tree)
            props[name] = {"$node": slot_id}
        elif (
            isinstance(value, dict)
            and value
            and all(isinstance(v, Component) for v in value.values())
        ):
            slots: dict[str, Any] = {}
            for key, child in value.items():
                slot_id = f"{node_id}/@{name}.{key}"
                _walk(child, slot_id, tree)
                slots[str(key)] = {"$node": slot_id}
            props[name] = slots
        else:
            props[name] = wire_value(value)
    for event, handler in getattr(component, "events", {}).items():
        tree.handlers[(node_id, event)] = handler
        props[f"on_{event}"] = True
    if props.get("hidden") is False:
        del props["hidden"]
    children_ids: list[str] = []
    for index, child in enumerate(component.children):
        if child is None:
            continue
        if isinstance(child, str):
            child = Text(child)
        if not isinstance(child, Component):
            raise TypeError(
                f"{type(component).__name__} child {index} is {type(child).__name__}, "
                "not a component or a string"
            )
        child_id = (
            f"{node_id}/{child.key}" if child.key else f"{node_id}/{index}:{child.wire_type()}"
        )
        if child_id in tree.nodes:
            raise ValueError(f"duplicate key {child.key!r} under {node_id}")
        children_ids.append(child_id)
        _walk(child, child_id, tree)
    _check_keys(component, node_id, tree)
    tree.nodes[node_id] = Node(
        id=node_id, type=component.wire_type(), props=props, children=children_ids
    )
    tree.components[node_id] = component


# Handler shapes already checked, by code object: a lambda is a new object each
# render and the same code every time, so the check is one per source line.
_HANDLER_SHAPES: dict[tuple[Any, int], str | None] = {}


def check_handler(prop: str, fn: Callable[..., Any], args: tuple[str, ...]) -> None:
    """A handler takes the session and then ``args``, one payload for most
    props. One that cannot fails here, when the tree is built, with the shape
    in the message, instead of at the click with a toast."""
    code = getattr(fn, "__code__", None)
    key = (code, len(args))
    if code is not None and key in _HANDLER_SHAPES:
        problem = _HANDLER_SHAPES[key]
    else:
        problem = _handler_problem(fn, 1 + len(args))
        if code is not None:
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


def wire_value(value: Any) -> Any:
    """Turn a prop value into JSON-ready data."""
    if value is None or isinstance(value, bool | int | float | str):
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
        if before is None:
            continue
        if before.type != node.type:
            ops.append(RemoveOp(id=node_id))
            ops.append(AddOp(node=node))
            continue
        changed = {k: v for k, v in node.props.items() if before.props.get(k, _MISSING) != v}
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
        elif isinstance(op, UnsetOp):
            for k in op.keys:
                out[op.id].props.pop(k, None)
        elif isinstance(op, ChildrenOp):
            out[op.id].children = list(op.children)
    return out


_MISSING = object()


# A run of this many keyless siblings of one type may be a list built from data,
# where a reorder would re-render every row instead of moving them. It is one
# only when its length changes between renders; a static layout never does.
KEYLESS_RUN = 4


def _check_keys(component: Component, node_id: str, tree: Tree) -> None:
    run: list[Component] = []
    for child in component.children:
        if isinstance(child, Component) and child.key is None:
            if run and type(child) is not type(run[-1]):
                run = []
            run.append(child)
            if len(run) == KEYLESS_RUN:
                tree.keyless_runs[node_id] = child.wire_type()
                return
        else:
            run = []
