"""The Form component: a Pydantic model becomes fields, a submit becomes an instance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Type  # noqa: UP035

from pydantic import BaseModel, field_validator

from millwork.colors import as_colors
from millwork.forms import Issue, choice, field_spec
from millwork.nodes import Component


class Form(Component):
    type: ClassVar[str] = "Form"
    needs_session: ClassVar[bool] = True
    payloads: ClassVar[dict[str, str]] = {
        "on_submit": "the validated model instance",
        "on_cancel": "None",
    }
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"model", "initial"})
    theme_words: ClassVar[dict[str, str]] = {"submit": "save"}

    # ``Type`` rather than ``type``: the class body's ``type`` is the component's wire name.
    model: Type[BaseModel]  # noqa: UP006
    # Any: a ``BaseModel`` annotation would make pydantic try to build one from a dict.
    initial: Any = None
    submit: str | None = "Save"
    cancel: str | None = None
    layout: Literal["vertical", "horizontal"] | int = "vertical"
    """Where a field's label stands, above it or beside it, or a number of
    columns from 1 to 12 that the fields are laid out in, labels above. On
    a narrow screen the columns are one. Beside their fields the labels
    share a column, and a field's help stands under the field."""
    fields: list[str] | None = None
    labels: Mapping[str, Mapping[str, Any]] | None = None
    # pointer (or field name) to spec keys: widget, choices, placeholder, min, max, step, rows...
    overrides: Mapping[str, Mapping[str, Any]] | None = None
    issues: list[Issue] = []
    disabled: bool = False
    read_only: bool = False
    dense: bool = False
    on_submit: Any = None
    on_cancel: Any = None

    @field_validator("layout")
    @classmethod
    def _columns(cls, layout: str | int) -> str | int:
        if isinstance(layout, int) and not 1 <= layout <= 12:
            raise ValueError(f"a form has 1 to 12 columns, not {layout}")
        return layout

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            model: Type[BaseModel] | None = None,  # noqa: UP006
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            initial: Any = None,
            submit: str | None = "Save",
            cancel: str | None = None,
            layout: Literal["vertical", "horizontal"] | int = "vertical",
            fields: list[str] | None = None,
            labels: Mapping[str, Mapping[str, Any]] | None = None,
            overrides: Mapping[str, Mapping[str, Any]] | None = None,
            issues: list[Issue] = ...,
            disabled: bool = False,
            read_only: bool = False,
            dense: bool = False,
            on_submit: Any = None,
            on_cancel: Any = None,
        ) -> None: ...
    else:

        def __init__(self, model: Type[BaseModel] | None = None, **props: Any) -> None:  # noqa: UP006
            if model is not None:
                props["model"] = model
            super().__init__(**props)

    def wire_extra(self) -> dict[str, Any]:
        spec = field_spec(self.model)
        if self.fields is not None:
            order = {name: i for i, name in enumerate(self.fields)}
            spec["fields"] = sorted(
                (f for f in spec["fields"] if f["name"] in order), key=lambda f: order[f["name"]]
            )
        if self.labels:
            _apply_labels(spec["fields"], self.labels)
        if self.overrides:
            _apply_overrides(spec["fields"], self.overrides)
        initial: Any = None
        if isinstance(self.initial, BaseModel):
            initial = self.initial.model_dump(mode="json")
        elif isinstance(self.initial, Mapping):
            initial = dict(self.initial)
        elif self.initial is not None:
            raise TypeError("Form.initial is a model instance or a mapping")
        # The key doubles as the form element's id, so a Button(type="submit", form=key)
        # anywhere on the page submits it.
        return {"schema": spec, "initial": initial, "form_id": self.key}


def _apply_labels(fields: list[dict[str, Any]], labels: Mapping[str, Mapping[str, Any]]) -> None:
    _apply(fields, labels, keys=("label", "help", "placeholder", "tooltip"))


def _apply_overrides(
    fields: list[dict[str, Any]], overrides: Mapping[str, Mapping[str, Any]]
) -> None:
    _apply(fields, overrides, keys=None)


def _apply(
    fields: list[dict[str, Any]],
    table: Mapping[str, Mapping[str, Any]],
    keys: tuple[str, ...] | None,
) -> None:
    """Merge ``table[pointer]`` (or ``table[name]``) into each field spec, recursively.

    ``keys`` limits what is taken; ``None`` takes everything. ``choices`` becomes
    ``options`` either way, and ``swatches`` are checked for being colors.
    """
    for f in fields:
        override = table.get(f["pointer"]) or table.get(f["name"])
        if override:
            for k, v in override.items():
                if k == "choices":
                    f["options"] = [choice(c) for c in v]
                    if f["widget"] == "input":
                        f["widget"] = "select"
                elif k == "swatches" and keys is None:
                    f["swatches"] = as_colors(v)
                elif keys is None or k in keys:
                    f[k] = v
        if "fields" in f:
            _apply(f["fields"], table, keys)
        # A row of a list is a model, with fields, or a union, with variants.
        item = f.get("item") or {}
        _apply(item.get("fields", []), table, keys)
        for v in [*f.get("variants", []), *item.get("variants", [])]:
            _apply(v["fields"], table, keys)
