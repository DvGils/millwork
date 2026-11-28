"""What a component of the catalog, as the page drew it, can have sent.

A tab is not trusted, and an event is a message anyone with a session can
write. A handler is given a value its component could have sent: a choice
that was on offer, a number inside the range, text of the length the
field takes. Anything else is refused before the handler, so a handler
reads its payload as what its component says it is.

One value that is not on offer is refused. A list is another matter,
since a tab keeps a list of its own: the choices ticked, the rows
selected, the columns sorted by. A choice or a row the page has taken
away since is still in it, and comes along with the next change. Such a
one is left out of the list and the rest is heard, so the change the
person made is not lost with it.

A component of an app's own is not known here. What a ``ui.Custom`` emits
is its handler's to read.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Callable, Collection, Iterator
from typing import Any

from millwork.nodes import Tree
from millwork.protocol import Node


class Refused(Exception):
    """A payload its component could not have sent. Its text ends a
    sentence that begins with the node."""


Check = Callable[[Tree, Node, Any], Any]


# ----------------------------------------------------------------- reach


def veiled(tree: Tree, node_id: str, custom: bool = False) -> str | None:
    """Why a node takes no events, or None when it does. A node takes none
    when it is hidden or inside something hidden, and when it is a
    ``Dialog`` or a ``Sheet`` that is closed or is inside one. A tab does
    not draw what is closed, and nobody presses what is hidden.

    A custom component goes on running while it is hidden, as a tab keeps
    it there, so what it emits then is still heard."""
    if tree.veiled is None:
        closed: set[str] = set()
        hidden: set[str] = set()
        for node in tree.nodes.values():
            if node.type in ("Dialog", "Sheet") and not node.props.get("open"):
                _under(tree, node.id, closed)
            if node.props.get("hidden"):
                _under(tree, node.id, hidden)
        tree.veiled = (frozenset(closed), frozenset(hidden))
    closed_ids, hidden_ids = tree.veiled
    at = tree.nodes.get(node_id)
    if node_id in closed_ids:
        own = at is not None and at.type in ("Dialog", "Sheet") and not at.props.get("open")
        return "is closed" if own else "is in something closed"
    if node_id in hidden_ids and not custom:
        own = at is not None and bool(at.props.get("hidden"))
        return "is hidden" if own else "is in something hidden"
    return None


def _under(tree: Tree, top: str, into: set[str]) -> None:
    """A node and everything in it, children and slots alike."""
    todo = [top]
    while todo:
        node_id = todo.pop()
        if node_id in into:
            continue
        into.add(node_id)
        node = tree.nodes.get(node_id)
        if node is not None:
            todo.extend(node.children)
            todo.extend(_slots(node.props))


def _slots(props: dict[str, Any]) -> Iterator[str]:
    """The nodes a node holds in its props: a footer, a trigger, a list of
    actions, the cells of a grid by name."""
    for value in props.values():
        if isinstance(value, dict):
            if "$node" in value:
                yield value["$node"]
            else:
                for inner in value.values():
                    if isinstance(inner, dict) and "$node" in inner:
                        yield inner["$node"]
        elif isinstance(value, list):
            for inner in value:
                if isinstance(inner, dict) and "$node" in inner:
                    yield inner["$node"]


# ---------------------------------------------------------------- values


def given(tree: Tree, node: Node, name: str, payload: Any, found: Collection[str] = ()) -> Any:
    """The payload of an event as its handler gets it, or ``Refused``. An
    event that is not known here goes on as it came. This is for a node
    of the catalog. A ``ui.Custom`` is drawn under a name of its own.

    ``found`` is what the node's search has answered with, which a
    ``Combobox`` offers next to the options on the page."""
    if (node.type, name) == ("Combobox", "change") and type(payload) is str and payload in found:
        return payload
    check = _CHECKS.get((node.type, name))
    return payload if check is None else check(tree, node, payload)


def _nothing(tree: Tree, node: Node, payload: Any) -> Any:
    """A press says nothing but that it happened."""
    return None


def _close(tree: Tree, node: Node, payload: Any) -> Any:
    """A dialog or a sheet that cannot be dismissed has no cross to press,
    and its tab sends nothing for Escape or a press outside."""
    if node.props.get("dismissable") is False:
        raise Refused("was sent, and it cannot be dismissed")
    return None


def _cancel(tree: Tree, node: Node, payload: Any) -> Any:
    """A form has a Cancel to press when it was given the word for it."""
    if not node.props.get("cancel"):
        raise Refused("was sent, and the form shows no Cancel")
    return None


def _flag(tree: Tree, node: Node, payload: Any) -> Any:
    if type(payload) is not bool:
        raise Refused(f"was sent {payload!r}, which is not true or false")
    return payload


def _text(payload: Any) -> str:
    if type(payload) is not str:
        raise Refused(f"was sent {_short(payload)}, which is not text")
    return payload


def _short(payload: Any) -> str:
    said = repr(payload)
    return said if len(said) <= 60 else said[:57] + "..."


def _held(node: Node) -> list[Any]:
    """What the component holds as the page drew it: the page's value, or
    the one it starts from. A choice that is held can be sent again, also
    one that is no longer among the choices."""
    out: list[Any] = []
    for name in ("value", "default", "selected"):
        value = node.props.get(name)
        out.extend(value if isinstance(value, list) else [value])
    return [v for v in out if v is not None]


def _on_offer(node: Node, field: str = "options", name: str = "value") -> set[Any]:
    """The choices that can be taken. A disabled one cannot."""
    return {
        choice[name]
        for choice in node.props.get(field) or []
        if isinstance(choice, dict) and not choice.get("disabled")
    }


def _one(clears: bool, field: str = "options", name: str = "value") -> Check:
    """One of the choices, or nothing where the component can be cleared."""

    def check(tree: Tree, node: Node, payload: Any) -> Any:
        if payload is None:
            if clears:
                return None
            raise Refused("was sent nothing, and it always has a choice")
        chosen = _text(payload)
        if chosen in _on_offer(node, field, name) or chosen in _held(node):
            return chosen
        raise Refused(f"was sent {_short(chosen)}, which is not one of its choices")

    return check


def _several(node: Node, payload: Any, offered: set[Any]) -> list[str]:
    """The choices of a list that are on offer or held, in the order they
    came. One that is neither was taken away since the tab last heard."""
    if not isinstance(payload, list):
        raise Refused(f"was sent {_short(payload)}, which is not a list")
    allowed = offered | {v for v in _held(node) if isinstance(v, str)}
    chosen = [choice for choice in payload if _text(choice) in allowed]
    if len(set(chosen)) != len(chosen):
        raise Refused("was sent a choice twice")
    return chosen


def _many(tree: Tree, node: Node, payload: Any) -> Any:
    chosen = _several(node, payload, _on_offer(node))
    most = node.props.get("max")
    if isinstance(most, int) and len(chosen) > max(most, len(_held(node))):
        raise Refused(f"was sent {len(chosen)} choices, and it takes {most}")
    return chosen


def _toggles(tree: Tree, node: Node, payload: Any) -> Any:
    if node.props.get("multiple"):
        return _several(node, payload, _on_offer(node))
    return _one(clears=True)(tree, node, payload)


def _combobox(tree: Tree, node: Node, payload: Any) -> Any:
    if payload is None:
        return None
    # A word of the person's own is on no list. What a search found is
    # let through before this, by what the search answered.
    if node.props.get("allow_custom"):
        return _text(payload)
    return _one(clears=True)(tree, node, payload)


def _parts(tree: Tree, node: Node, kind: str, open_only: bool) -> set[Any]:
    """The ids of the tabs or the items a node holds that are there."""
    out: set[Any] = set()
    for child_id in node.children:
        child = tree.nodes.get(child_id)
        if child is None or child.type != kind or child.props.get("hidden"):
            continue
        if open_only and child.props.get("disabled"):
            continue
        out.add(child.props.get("id"))
    return out


def _tab(tree: Tree, node: Node, payload: Any) -> Any:
    if _text(payload) not in _parts(tree, node, "Tab", open_only=True):
        raise Refused(f"was sent {_short(payload)}, which is not a tab that can be chosen")
    return payload


def _items(tree: Tree, node: Node, payload: Any) -> Any:
    opened = _several(node, payload, _parts(tree, node, "AccordionItem", open_only=False))
    if not node.props.get("multiple") and len(opened) > max(1, len(_held(node))):
        raise Refused(f"was sent {len(opened)} open items, and it has one open at a time")
    return opened


def _typed(tree: Tree, node: Node, payload: Any) -> Any:
    text = _text(payload)
    most = node.props.get("max_length")
    if isinstance(most, int) and len(text) > most:
        # A text the page itself put there can be longer, and stays so
        # while it is edited.
        held = max((len(v) for v in _held(node) if isinstance(v, str)), default=0)
        if len(text) > held:
            raise Refused(f"was sent {len(text)} characters, and it takes {most}")
    return text


def _number(payload: Any) -> float:
    real = type(payload) in (int, float) and math.isfinite(payload)
    if not real:
        raise Refused(f"was sent {_short(payload)}, which is not a number")
    return payload  # type: ignore[no-any-return]


def _within(node: Node, number: float, low: Any, high: Any) -> None:
    # A step that is no round number in binary can land a hair past the end.
    slack = 1e-9 * max(1.0, abs(number))
    below = isinstance(low, int | float) and number < low - slack
    above = isinstance(high, int | float) and number > high + slack
    if (below or above) and number not in _held(node):
        ends = " to ".join("any" if end is None else f"{end:g}" for end in (low, high))
        raise Refused(f"was sent {number:g}, which is outside {ends}")


def _slide(tree: Tree, node: Node, payload: Any) -> Any:
    number = _number(payload)
    _within(node, number, node.props.get("min", 0), node.props.get("max", 100))
    return number


def _amount(tree: Tree, node: Node, payload: Any) -> Any:
    if payload is None:
        return None
    number = _number(payload)
    _within(node, number, node.props.get("min"), node.props.get("max"))
    return number


def _day(node: Node, payload: Any) -> str:
    day = _text(payload)
    try:
        # The tab writes a day as ten characters, which is also how two
        # days compare as text.
        whole = len(day) == 10 and dt.date.fromisoformat(day) is not None
    except ValueError:
        whole = False
    if not whole:
        raise Refused(f"was sent {_short(day)}, which is not a day")
    # An end that was given with a time is its day, as the calendar reads it.
    low, high = node.props.get("min"), node.props.get("max")
    outside = (isinstance(low, str) and day < low[:10]) or (
        isinstance(high, str) and day > high[:10]
    )
    if outside and day not in _held(node):
        raise Refused(f"was sent {day}, which is outside the days it offers")
    return day


def _date(tree: Tree, node: Node, payload: Any) -> Any:
    if payload is None:
        return None
    if not node.props.get("range"):
        return _day(node, payload)
    if not isinstance(payload, list) or len(payload) != 2:
        raise Refused(f"was sent {_short(payload)}, which is not a first and a last day")
    return [None if day is None else _day(node, day) for day in payload]


# A color as a tab sends it.
_HEX_CODE = re.compile(r"#[0-9a-f]{6}")


def _color(tree: Tree, node: Node, payload: Any) -> Any:
    if payload is None:
        if not node.props.get("clearable"):
            raise Refused("was sent no color, and it is not one to clear")
        return None
    code = _text(payload)
    if not _HEX_CODE.fullmatch(code):
        raise Refused(f"was sent {_short(payload)}, which is not a color")
    return code


def _name(key: Any) -> tuple[str, Any] | None:
    """A row's key as a tab holds it. There every number is a float, so 1
    and 1.0 are one key, a whole number past 2**53 is the float nearest
    to it, and neither is ``true``."""
    if type(key) is bool:
        return ("flag", key)
    if type(key) in (int, float):
        try:
            return ("number", float(key))
        except OverflowError:
            return None
    if type(key) is str:
        return ("text", key)
    return None


def _rows(node: Node, *more: Any) -> dict[tuple[str, Any], Any]:
    """The keys of a table's rows by how a tab names them."""
    keys = [*(node.props.get("keys") or []), *more]
    return {name: key for key in keys if (name := _name(key)) is not None}


def _row(key: Any, rows: dict[tuple[str, Any], Any]) -> Any:
    """The key as the table has it, which is the one the page gave it."""
    name = _name(key)
    if name is None or name not in rows:
        raise Refused(f"was sent the row {_short(key)}, which it does not have")
    return rows[name]


def _select(tree: Tree, node: Node, payload: Any) -> Any:
    kind = node.props.get("selection")
    if kind not in ("row", "rows"):
        raise Refused("was sent a selection, and its rows cannot be selected")
    if not isinstance(payload, list):
        raise Refused(f"was sent {_short(payload)}, which is not a list of rows")
    # A row that was selected and is gone is in what the page holds, or in
    # what the tab holds when the page keeps no selection. The first is
    # sent on and the second is left out.
    held = node.props.get("selected") or []
    rows = _rows(node, *held)
    selected = []
    for key in payload:
        name = _name(key)
        if name is None:
            raise Refused(f"was sent the row {_short(key)}, which is no key of a row")
        if name in rows:
            selected.append(rows[name])
    if kind == "row" and len(selected) > max(1, len(held)):
        raise Refused(f"was sent {len(selected)} rows, and it has one selected at a time")
    return selected


def _row_click(tree: Tree, node: Node, payload: Any) -> Any:
    return _row(payload, _rows(node))


def _row_action(tree: Tree, node: Node, payload: Any) -> Any:
    if not isinstance(payload, list) or len(payload) != 2:
        raise Refused(f"was sent {_short(payload)}, which is not an action and a row")
    action, key = payload
    if _text(action) not in _on_offer(node, "row_actions", "id"):
        raise Refused(f"was sent {_short(action)}, which is not one of its actions")
    return [action, _row(key, _rows(node))]


def _row_move(tree: Tree, node: Node, payload: Any) -> Any:
    from millwork.ui.table import RowMove

    if not isinstance(payload, dict):
        raise Refused(f"was sent {_short(payload)}, which is not a row and a place")
    rows = _rows(node)
    key = _row(payload.get("key"), rows)
    to = payload.get("to")
    if type(to) is not int or not 0 <= to < len(rows):
        raise Refused(f"was sent the place {_short(to)}, and it has {len(rows)} rows")
    return RowMove(key=key, to=to)


def _columns(node: Node, able: str) -> set[Any]:
    return {c.get("key") for c in node.props.get("columns") or [] if c.get(able, True)}


def _sort(tree: Tree, node: Node, payload: Any) -> Any:
    if not isinstance(payload, list):
        raise Refused(f"was sent {_short(payload)}, which is not an order of columns")
    columns = _columns(node, "sortable") if node.props.get("sortable", True) else set()
    # The order the page starts from stays in the tab's, also by a column
    # that cannot be sorted by hand.
    columns |= {by[0] for by in node.props.get("default_sort") or []}
    order = []
    for by in payload:
        pair = isinstance(by, list) and len(by) == 2 and type(by[0]) is str
        if not pair or by[1] not in ("asc", "desc"):
            raise Refused(f"was sent {_short(by)}, which is not a column and a direction")
        if by[0] in columns:
            order.append(by)
    return order


def _filter(tree: Tree, node: Node, payload: Any) -> Any:
    shaped = (
        isinstance(payload, dict)
        and payload.keys() <= {"columns", "search"}
        and isinstance(payload.get("columns", {}), dict)
        and isinstance(payload.get("search", ""), str)
    )
    if not shaped:
        raise Refused(f"was sent {_short(payload)}, which is not a filter")
    columns = _columns(node, "filterable")
    kept = {}
    for column, value in payload.get("columns", {}).items():
        ends = isinstance(value, list) and len(value) == 2
        plain = all(v is None or type(v) in (int, float, str) for v in value) if ends else False
        if not (isinstance(value, str) or plain):
            raise Refused(f"was sent {_short(value)} to filter by, which is no filter")
        # A filter on a column the table had before filters nothing.
        if column in columns:
            kept[column] = value
    return {**payload, "columns": kept} if "columns" in payload else payload


def _mapping(what: str) -> Check:
    def check(tree: Tree, node: Node, payload: Any) -> Any:
        if not isinstance(payload, dict):
            raise Refused(f"was sent {_short(payload)}, which is not {what}")
        return payload

    return check


def _search(tree: Tree, node: Node, payload: Any) -> Any:
    return _text(payload)


def _move(tree: Tree, node: Node, payload: Any) -> Any:
    """A row dropped in this list, as a ``Move``. The row is one that is in
    the list it is said to come from, and that list is this one, or one of
    its group that the page shows and that is not disabled. The place is
    kept within the rows there are."""
    from millwork.ui.sortable import Move

    if node.props.get("disabled"):
        raise Refused("the list takes no rows")
    if not isinstance(payload, dict):
        raise Refused("a move names a row, a list and a place")
    row, source_id, to = payload.get("key"), payload.get("source"), payload.get("to")
    if type(row) is not str or type(source_id) is not str or type(to) is not int:
        raise Refused("a move names a row, a list and a place")
    source = tree.nodes.get(source_id)
    if source is None or source.type != "Sortable" or row not in source.children:
        raise Refused("the row is not in the list it is said to come from")
    if node.id.startswith(row + "/"):
        raise Refused("the list is in the row that is moved")
    here = source_id == node.id
    if here:
        if node.props.get("reorder") is False:
            raise Refused("the rows of the list keep their order")
    else:
        group = node.props.get("group")
        if group is None or source.props.get("group") != group:
            raise Refused("the lists are not of one group")
        if node.props.get("takes") is False:
            raise Refused("the list takes no rows of another")
        if source.props.get("disabled") or veiled(tree, source_id) is not None:
            raise Refused("the list the row comes from gives none")
    others = len(node.children) - (1 if here else 0)
    return Move(
        key=str(tree.components[row].key),
        source=tree.components[source_id].key,
        target=tree.components[node.id].key,
        to=max(0, min(to, others)),
    )


_PRESSED = (
    ("Button", "click"),
    ("Card", "click"),
    ("Image", "click"),
    ("FileCard", "click"),
    ("Alert", "dismiss"),
)
_FLAGGED = (
    ("Checkbox", "change"),
    ("Switch", "change"),
    ("Sidebar", "toggle"),
    ("SidebarGroup", "toggle"),
    ("Collapsible", "toggle"),
    ("Assistant", "toggle"),
)
_CHECKS: dict[tuple[str, str], Check] = {
    **dict.fromkeys(_PRESSED, _nothing),
    ("Dialog", "close"): _close,
    ("Sheet", "close"): _close,
    ("Form", "cancel"): _cancel,
    **dict.fromkeys(_FLAGGED, _flag),
    ("Select", "change"): _one(clears=True),
    ("RadioGroup", "change"): _one(clears=False),
    ("ToggleGroup", "change"): _toggles,
    ("CheckboxGroup", "change"): _many,
    ("MultiSelect", "change"): _many,
    ("Combobox", "change"): _combobox,
    ("Combobox", "search"): _search,
    ("DropdownMenu", "select"): _one(clears=False, field="items", name="id"),
    ("FileCard", "action"): _one(clears=False, field="actions", name="id"),
    ("Tabs", "change"): _tab,
    ("Accordion", "change"): _items,
    ("Input", "change"): _typed,
    ("Input", "submit"): _typed,
    ("Textarea", "change"): _typed,
    ("Textarea", "submit"): _typed,
    ("Slider", "change"): _slide,
    ("NumberInput", "change"): _amount,
    ("DatePicker", "change"): _date,
    ("ColorPicker", "change"): _color,
    ("Table", "select"): _select,
    ("Table", "row_click"): _row_click,
    ("Table", "action"): _row_action,
    ("Table", "sort"): _sort,
    ("Table", "filter"): _filter,
    ("Table", "move"): _row_move,
    ("BarChart", "click"): _mapping("a place in a chart"),
    ("LineChart", "click"): _mapping("a place in a chart"),
    ("AreaChart", "click"): _mapping("a place in a chart"),
    ("PieChart", "click"): _mapping("a place in a chart"),
    ("FileUpload", "reject"): _mapping("a file and a reason"),
    ("Sortable", "move"): _move,
}
