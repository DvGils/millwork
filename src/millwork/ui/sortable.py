"""The Sortable: rows a person drags into another order, or into another list."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator

from millwork.nodes import Component


class Move(BaseModel):
    """A row that was dragged, as ``on_move`` gets it.

    ``key`` is the row's key. ``source`` is the key of the list it was in and
    ``target`` the key of the list it was dropped in, the same list when the
    row only changed places. ``to`` is its place among the rows of the
    target, counted from 0 with the row itself left out, so that
    ``rows.insert(move.to, row)`` after taking the row out puts it there."""

    model_config = ConfigDict(frozen=True)

    key: str
    source: str | None
    target: str | None
    to: int


class Sortable(Component):
    """Rows that are dragged into another order. Each child is a row, and
    has a ``key``. ``on_move`` gets a ``Move`` and changes the state, and
    the page drawn from it is where the row ends up: a handler that leaves
    the state as it was sends the row back.

    Lists with the same ``group`` take rows from each other, and such a
    list has a ``key`` of its own, which the ``Move`` names it by.
    ``takes=False`` keeps rows of other lists out, and ``reorder=False``
    keeps the list's own rows in the order they are in. ``empty`` is what
    a list without rows says, where a row can still be dropped.

    A row is dragged by the grip down its left edge, or by all of it with
    ``handle=False``, which suits rows with little in them to press. A list
    without ``on_move`` has nobody to tell, so it takes no rows and keeps
    the order of its own."""

    type: ClassVar[str] = "Sortable"
    needs_session: ClassVar[bool] = True
    payloads: ClassVar[dict[str, str]] = {
        "on_move": "a Move: the row's key, the source and target lists, and its new place",
    }

    group: str | None = None
    label: str | None = None
    handle: bool = True
    takes: bool = True
    reorder: bool = True
    empty: str | None = None
    disabled: bool = False
    gap: int = 2
    on_move: Any = None

    @model_validator(mode="after")
    def _rows_and_lists_have_keys(self) -> Sortable:
        if self.group is not None and self.key is None:
            raise ValueError(
                f"a Sortable in the group {self.group!r} has a key, which its moves name it by"
            )
        seen: set[str] = set()
        for child in self.children:
            key = getattr(child, "key", None)
            if not isinstance(child, Component) or key is None:
                raise ValueError(
                    "each row of a Sortable is a component with a key, which says "
                    "which row was moved"
                )
            if key in seen:
                raise ValueError(f"two rows of a Sortable have the key {key!r}")
            seen.add(key)
        return self

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            group: str | None = None,
            label: str | None = None,
            handle: bool = True,
            takes: bool = True,
            reorder: bool = True,
            empty: str | None = None,
            disabled: bool = False,
            gap: int = 2,
            on_move: Any = None,
        ) -> None: ...
