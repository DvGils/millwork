from typing import Any, ClassVar

from hypothesis import given, settings
from hypothesis import strategies as st

from millwork.nodes import Component, Text, apply, build, diff
from millwork.protocol import AddOp, RemoveOp


class Box(Component):
    type: ClassVar[str] = "Box"
    label: str | None = None
    on_click: Any = None
    footer: Component | None = None


def test_build_assigns_positional_and_keyed_ids() -> None:
    tree = build(Box(Text("a"), None, Text("b"), Box(key="k")))
    assert tree.nodes["root"].children == ["root/0:Text", "root/2:Text", "root/k"]
    assert tree.nodes["root/2:Text"].props["content"] == "b"


def test_handlers_leave_the_wire_as_true() -> None:
    called: list[Any] = []
    tree = build(Box(on_click=lambda s, p: called.append(p)))
    assert tree.nodes["root"].props["on_click"] is True
    assert tree.handler("root", "click") is not None


def test_slot_props_become_nodes() -> None:
    tree = build(Box(footer=Box(label="f")))
    assert tree.nodes["root"].props["footer"] == {"$node": "root/@footer"}
    assert tree.nodes["root/@footer"].props["label"] == "f"


def test_diff_orders_adds_before_removes_and_detects_type_change() -> None:
    before = build(Box(Text("a")))
    after = build(Box(Box(key="x")))
    ops = diff(before, after)
    assert isinstance(ops[0], AddOp)
    assert any(isinstance(o, RemoveOp) and o.id == "root/0:Text" for o in ops)
    assert apply(before.nodes, ops) == after.nodes


labels = st.one_of(st.none(), st.text(max_size=5))


@st.composite
def components(draw: Any, depth: int = 0) -> Component:
    children: list[Any] = []
    if depth < 3:
        n = draw(st.integers(0, 3))
        for _ in range(n):
            kind = draw(st.sampled_from(["text", "box", "none"]))
            if kind == "text":
                children.append(Text(draw(st.text(max_size=4))))
            elif kind == "box":
                children.append(draw(components(depth + 1)))
            else:
                children.append(None)
    return Box(*children, label=draw(labels), hidden=draw(st.booleans()))


@settings(max_examples=200, deadline=None)
@given(components(), components())
def test_patch_reproduces_the_new_tree(a: Component, b: Component) -> None:
    before, after = build(a), build(b)
    assert apply(before.nodes, diff(before, after)) == after.nodes


def test_list_children_are_flattened() -> None:
    tree = build(Box([Text("a"), None, [Text("b")]], Text("c")))
    assert tree.nodes["root"].children == ["root/0:Text", "root/2:Text", "root/3:Text"]


def test_custom_component_names_its_type_and_binds_events() -> None:
    from millwork import ui

    tree = build(
        ui.Page(
            ui.Custom("Hello", key="h", props={"who": "Ada"}, events={"wave": lambda s, p: None})
        )
    )
    node = tree.nodes["root/h"]
    assert node.type == "Hello" and node.props["who"] == "Ada" and node.props["on_wave"] is True
    assert "name" not in node.props and "props" not in node.props
    assert tree.handler("root/h", "wave") is not None


class Rich(Component):
    """A component with every kind of prop the diff has to carry."""

    type: ClassVar[str] = "Rich"
    label: str | None = None
    count: int = 0
    tags: list[str] = []
    meta: dict[str, Any] | None = None
    footer: Component | None = None
    items: list[Component] = []
    on_click: Any = None


keys = st.sampled_from([None, "a", "b", "c"])
leaves = st.one_of(
    st.builds(Text, st.text(max_size=3), key=keys),
    st.builds(Box, label=labels, key=keys),
)


@st.composite
def rich(draw: Any, depth: int = 0) -> Component:
    children: list[Any] = []
    used: set[str] = set()
    n = draw(st.integers(0, 3))
    for _ in range(n):
        kind = draw(st.sampled_from(["leaf", "rich", "none"]))
        if kind == "none":
            children.append(None)
            continue
        child = draw(rich(depth + 1)) if kind == "rich" and depth < 2 else draw(leaves)
        if child.key in used:
            child = child.model_copy(update={"key": None})
        if child.key:
            used.add(child.key)
        children.append(child)
    items = draw(st.lists(leaves, max_size=2, unique_by=lambda c: c.key or id(c)))
    # Optional props are sometimes left unset, so the diff also covers props that
    # are absent on the wire rather than null.
    optional: dict[str, Any] = {
        "label": labels,
        "meta": st.one_of(st.none(), st.fixed_dictionaries({"k": st.integers(0, 1)})),
        "footer": st.one_of(st.none(), leaves),
        "on_click": st.one_of(st.none(), st.just(lambda s, p: None)),
        "hidden": st.booleans(),
    }
    props = {name: draw(strategy) for name, strategy in optional.items() if draw(st.booleans())}
    return Rich(
        *children,
        key=draw(keys),
        count=draw(st.integers(0, 2)),
        tags=draw(st.lists(st.sampled_from(["x", "y"]), max_size=2)),
        items=items,
        **props,
    )


@settings(max_examples=300, deadline=None)
@given(rich(), rich())
def test_patch_carries_every_prop_kind_and_keeps_the_table_consistent(
    a: Component, b: Component
) -> None:
    from millwork.protocol import AddOp as Add
    from millwork.protocol import ChildrenOp, Patch, RemoveOp, SetOp, UnsetOp

    before, after = build(a), build(b)
    ops = diff(before, after)
    assert apply(before.nodes, ops) == after.nodes
    assert diff(after, after) == []
    # New nodes are added before any update refers to them; a node whose type
    # changed is removed before its replacement is added; plain removes come last.
    first_update = next(
        (i for i, op in enumerate(ops) if isinstance(op, SetOp | UnsetOp | ChildrenOp)), len(ops)
    )
    replaced = {op.id for op in ops if isinstance(op, RemoveOp)} & {
        op.node.id for op in ops if isinstance(op, Add)
    }
    for i, op in enumerate(ops):
        if isinstance(op, Add) and op.node.id not in replaced:
            assert i < first_update
        if isinstance(op, Add) and op.node.id in replaced:
            assert isinstance(ops[i - 1], RemoveOp) and ops[i - 1].id == op.node.id
        if isinstance(op, RemoveOp) and op.id not in replaced:
            assert all(isinstance(later, RemoveOp) for later in ops[i:])
    # ``build`` keeps its own table consistent, and the patch is plain JSON.
    for node in after.nodes.values():
        for child in node.children:
            assert child in after.nodes
        for value in node.props.values():
            if isinstance(value, dict) and "$node" in value:
                assert value["$node"] in after.nodes
    text = Patch(ops=ops).model_dump_json()
    assert Patch.model_validate_json(text).ops == ops
    # A handler never reaches the wire, and ``hidden`` only appears when set.
    for node in after.nodes.values():
        assert node.props.get("on_click") in (None, True)
        assert node.props.get("hidden") in (None, True)


def test_duplicate_keys_in_a_list_prop_are_refused() -> None:
    import pytest

    build(Rich(items=[Text("a", key="a"), Text("b", key="b"), Text("c")]))
    with pytest.raises(ValueError, match="duplicate key 'a' in items"):
        build(Rich(items=[Text("a", key="a"), Text("b", key="a")]))


def test_a_handler_must_take_session_and_payload() -> None:
    import pytest

    def fine(s: Any, payload: Any) -> None: ...
    def loose(*args: Any) -> None: ...
    def one(s: Any) -> None: ...

    build(Box(on_click=fine))
    build(Box(on_click=loose))
    build(Box(on_click=lambda s, v=None: None))
    with pytest.raises(
        TypeError, match=r"on_click takes a handler of \(session, payload\); one\(s"
    ):
        build(Box(on_click=one))
    with pytest.raises(TypeError, match="does not take 2 positional arguments"):
        build(Box(on_click=lambda: None))
