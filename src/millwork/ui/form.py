"""The Form component: a Pydantic model becomes fields, a submit becomes an instance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Type  # noqa: UP035

from pydantic import BaseModel

from millwork.forms import Issue, field_spec
from millwork.nodes import Component


class Form(Component):
    type: ClassVar[str] = "Form"
    wire_exclude: ClassVar[frozenset[str]] = frozenset({"model", "initial"})

    # ``Type`` rather than ``type``: the class body's ``type`` is the component's wire name.
    model: Type[BaseModel]  # noqa: UP006
    # Any: a ``BaseModel`` annotation would make pydantic try to build one from a dict.
    initial: Any = None
    submit: str | None = "Save"
    cancel: str | None = None
    layout: Literal["vertical", "horizontal"] | int = "vertical"
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

    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py

        def __init__(
            self,
            *children: Any,
            key: str | None = None,
            hidden: bool = False,
            cls: str | None = None,
            model: Type[BaseModel],  # noqa: UP006
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

        def __init__(self, model: Any = None, **props: Any) -> None:
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
    _apply(fields, labels, keys=("label", "help", "placeholder"))


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
    ``options`` either way.
    """
    for f in fields:
        override = table.get(f["pointer"]) or table.get(f["name"])
        if override:
            for k, v in override.items():
                if k == "choices":
                    f["options"] = [
                        {"value": c[0], "label": c[1]} if isinstance(c, tuple | list) else c
                        for c in v
                    ]
                    if f["widget"] == "input":
                        f["widget"] = "select"
                elif keys is None or k in keys:
                    f[k] = v
        if "fields" in f:
            _apply(f["fields"], table, keys)
        if "item" in f and "fields" in f["item"]:
            _apply(f["item"]["fields"], table, keys)
        for v in f.get("variants", []):
            _apply(v["fields"], table, keys)
