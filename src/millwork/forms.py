"""Forms from Pydantic models: the field spec the bundle renders, and validation.

The spec is derived from the model's JSON Schema, so nested models, lists,
literals, enums, optionals and discriminated unions all come out the same
way. ``json_schema_extra`` carries widget hints: ``widget``, ``choices``,
``group``, ``order``, ``hidden``, ``sortable``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import to_jsonable_python

Widget = str  # input, textarea, password, number, slider, switch, checkbox, select, radio,
# toggle, checkboxes, multiselect, date, datetime, fieldset, list, union, file, hidden


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pointer: str
    message: str
    code: str | None = None


class FormIssues(Exception):
    """Raised by a submit handler to reject a valid document on the app's grounds."""

    def __init__(self, issues: list[Issue] | list[tuple[str, str]]) -> None:
        self.issues = [
            i if isinstance(i, Issue) else Issue(pointer=i[0], message=i[1]) for i in issues
        ]
        super().__init__(f"{len(self.issues)} issue(s)")


def pointer_of(loc: tuple[Any, ...], tags: frozenset[str] = frozenset()) -> str:
    """A pydantic error ``loc`` as a JSON pointer: ``("a", 0, "b")`` is ``/a/0/b``.

    A discriminated union adds its tag to the loc (``("ops", 0, "bucket",
    "source")``); tags known from the model are dropped so the pointer lands
    on the field the user sees.
    """
    parts: list[str] = []
    for i, part in enumerate(loc):
        if isinstance(part, int):
            parts.append(str(part))
        elif isinstance(part, str):
            if part.startswith("function-after") or part.startswith("tagged-union"):
                continue
            if i > 0 and part in tags:
                continue
            parts.append(part.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(parts)


def union_tags(model: type[BaseModel]) -> frozenset[str]:
    """Every discriminator value in the model's forms, for ``pointer_of``."""
    tags: set[str] = set()

    def walk(fields: list[dict[str, Any]]) -> None:
        for f in fields:
            for v in f.get("variants", []):
                if v.get("tag") is not None:
                    tags.add(str(v["tag"]))
                walk(v["fields"])
            if "fields" in f:
                walk(f["fields"])
            item = f.get("item")
            if item:
                walk([item])

    walk(field_spec(model)["fields"])
    return frozenset(tags)


def validate(model: type[BaseModel], draft: Any) -> tuple[BaseModel | None, list[Issue]]:
    """Validate a draft. Returns the instance, or the issues by pointer."""
    try:
        return model.model_validate(draft), []
    except ValidationError as exc:
        issues: list[Issue] = []
        seen: set[str] = set()
        tags = union_tags(model)
        for err in exc.errors():
            pointer = pointer_of(tuple(err["loc"]), tags)
            if pointer in seen:
                continue
            seen.add(pointer)
            issues.append(Issue(pointer=pointer, message=err["msg"], code=err.get("type")))
        return None, issues


# ---------------------------------------------------------------- files in a draft

# What a file looks like on the wire, and in a schema (where the server-only
# fields are present too). The schema's title may be the field's own.
_FILE_KEYS = frozenset({"id", "name", "size", "mime"})
_FILE_SCHEMA_KEYS = _FILE_KEYS | {"path", "session"}


def _is_file_ref(prop: Mapping[str, Any]) -> bool:
    return _FILE_SCHEMA_KEYS <= set(prop.get("properties", {}))


def file_fields(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The file fields of a form spec by pointer, list items without their index."""
    out: dict[str, dict[str, Any]] = {}

    def walk(fields: list[dict[str, Any]]) -> None:
        for f in fields:
            if f["widget"] in ("file", "files"):
                out[f["pointer"]] = f
            walk(f.get("fields", []))
            item = f.get("item")
            if item:
                walk(item.get("fields", []))
            for v in f.get("variants", []):
                walk(v["fields"])

    walk(list(spec.get("fields", [])))
    return out


def resolve_files(draft: Any, lookup: Callable[[str], Any]) -> Any:
    """Replace the tab's file dicts in a draft by what ``lookup`` returns for their id.

    A dict that looks like a file on the wire (``id``, ``name``, ``size``,
    ``mime``) is only ever an upload echoed back; the session's own record
    replaces it, and an id the session does not know becomes ``None`` so
    validation reports the field.
    """
    if isinstance(draft, dict):
        if _FILE_KEYS <= set(draft) and isinstance(draft.get("id"), str):
            return lookup(draft["id"])
        return {k: resolve_files(v, lookup) for k, v in draft.items()}
    if isinstance(draft, list):
        return [resolve_files(v, lookup) for v in draft]
    return draft


# ---------------------------------------------------------------- schema -> fields


def humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def field_spec(model: type[BaseModel]) -> dict[str, Any]:
    """The whole form as a spec: ``{"fields": [...], "title": ...}``."""
    schema = model.model_json_schema()
    walker = _Walker(schema.get("$defs", {}), factory_defaults(model))
    return {"title": schema.get("title"), "fields": walker.fields(schema, "")}


def factory_defaults(model: type[BaseModel], base: str = "") -> dict[str, Any]:
    """The defaults the JSON schema leaves out, by pointer: a ``default_factory``
    is called once per spec, so a form opens with today's date filled in."""
    out: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        pointer = f"{base}/{name}"
        if field.default_factory is not None:
            try:
                out[pointer] = to_jsonable_python(field.get_default(call_default_factory=True))
            except Exception:  # noqa: BLE001  a factory that wants validated data, or fails
                pass
        inner = _model_of(field.annotation)
        if inner is not None:
            out.update(factory_defaults(inner, pointer))
    return out


def _model_of(annotation: Any) -> type[BaseModel] | None:
    """The model behind ``Model`` or ``Model | None``; nothing for anything else."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) in (Union, UnionType):
        models = [
            a for a in get_args(annotation) if isinstance(a, type) and issubclass(a, BaseModel)
        ]
        if len(models) == 1 and len(get_args(annotation)) == 2:
            return models[0]
    return None


class _Walker:
    def __init__(self, defs: Mapping[str, Any], defaults: Mapping[str, Any] = {}) -> None:
        self.defs = defs
        self.defaults = defaults

    def resolve(self, node: Mapping[str, Any]) -> dict[str, Any]:
        """Follow ``$ref`` and merge the referenced schema under the local keys."""
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            target = dict(self.defs[name])
            local = {k: v for k, v in node.items() if k != "$ref"}
            target.update(local)
            return target
        return dict(node)

    def fields(self, obj: Mapping[str, Any], base: str) -> list[dict[str, Any]]:
        obj = self.resolve(obj)
        required = set(obj.get("required", []))
        out: list[dict[str, Any]] = []
        for name, prop in obj.get("properties", {}).items():
            spec = self.field(name, prop, f"{base}/{name}", name in required)
            if spec is not None:
                out.append(spec)
        out.sort(key=lambda f: f.get("order", 0))
        return out

    def field(
        self, name: str, prop: Mapping[str, Any], pointer: str, required: bool
    ) -> dict[str, Any] | None:
        prop = self.resolve(prop)
        if prop.get("hidden"):
            return None
        spec: dict[str, Any] = {
            "name": name,
            "pointer": pointer,
            "label": prop.get("title") or humanize(name),
            "help": prop.get("description"),
            "placeholder": (prop.get("examples") or [None])[0],
            "required": required and "default" not in prop and pointer not in self.defaults,
            "group": prop.get("group"),
            "order": prop.get("order", 0),
            "widget": "input",
        }
        if "default" in prop:
            spec["default"] = prop["default"]
        elif pointer in self.defaults:
            spec["default"] = self.defaults[pointer]
        self.classify(prop, spec, name)
        if prop.get("widget"):
            spec["widget"] = prop["widget"]
        if prop.get("choices"):
            spec["options"] = [self.option(c) for c in prop["choices"]]
            if spec["widget"] == "input":
                spec["widget"] = "select"
        return spec

    def option(self, c: Any) -> dict[str, Any]:
        if isinstance(c, Mapping):
            return {"value": c["value"], "label": c.get("label", str(c["value"]))}
        if isinstance(c, tuple | list) and len(c) == 2:
            return {"value": c[0], "label": str(c[1])}
        return {"value": c, "label": str(c)}

    def classify(self, prop: Mapping[str, Any], spec: dict[str, Any], name: str) -> None:
        # Optional[X] is anyOf [X, null]; unwrap and mark clearable.
        if "anyOf" in prop and "discriminator" not in prop:
            branches = [self.resolve(b) for b in prop["anyOf"]]
            non_null = [b for b in branches if b.get("type") != "null"]
            if len(non_null) == 1 and len(branches) == 2:
                spec["clearable"] = True
                merged = dict(non_null[0])
                for k in (
                    "title",
                    "description",
                    "default",
                    "examples",
                    "widget",
                    "choices",
                    "accept",
                    "max_size_mb",
                    "max_files",
                ):
                    if k in prop:
                        merged[k] = prop[k]
                self.classify(merged, spec, name)
                return
        if "oneOf" in prop or ("anyOf" in prop and "discriminator" in prop):
            self.union(prop, spec)
            return
        if "enum" in prop:
            spec["widget"] = "select"
            spec["options"] = [self.option(v) for v in prop["enum"]]
            return
        if "const" in prop:
            spec["widget"] = "hidden"
            spec["default"] = prop["const"]
            return
        t = prop.get("type")
        fmt = prop.get("format")
        if t == "string":
            if fmt == "password" or prop.get("writeOnly"):
                spec["widget"] = "password"
            elif fmt == "date":
                spec["widget"] = "date"
                # Pydantic puts no bounds for dates in the schema; the hints do.
                for k in ("min_date", "max_date"):
                    if k in prop:
                        spec[k] = prop[k]
            elif fmt == "date-time":
                spec["widget"] = "datetime"
            elif (prop.get("maxLength") or 0) > 200:
                spec["widget"] = "textarea"
            else:
                spec["widget"] = "input"
            if "maxLength" in prop:
                spec["max_length"] = prop["maxLength"]
            if "pattern" in prop:
                spec["pattern"] = prop["pattern"]
        elif t in ("integer", "number"):
            spec["widget"] = "number"
            spec["integer"] = t == "integer"
            for src, dst in (
                ("minimum", "min"),
                ("maximum", "max"),
                ("exclusiveMinimum", "min"),
                ("exclusiveMaximum", "max"),
                ("multipleOf", "step"),
            ):
                if src in prop:
                    spec[dst] = prop[src]
        elif t == "boolean":
            spec["widget"] = "switch"
        elif t == "array":
            items = self.resolve(prop.get("items", {}))
            if "enum" in items:
                spec["widget"] = "checkboxes"
                spec["options"] = [self.option(v) for v in items["enum"]]
                if "maxItems" in prop:
                    spec["max_items"] = prop["maxItems"]
                if prop.get("sortable"):
                    spec["sortable"] = True
            elif _is_file_ref(items):
                spec["widget"] = "files"
                for k in ("accept", "max_size_mb", "max_files"):
                    if k in prop:
                        spec[k] = prop[k]
            elif (
                items.get("type") == "object"
                or "properties" in items
                or "oneOf" in items
                or "discriminator" in items
            ):
                spec["widget"] = "list"
                # Fields of an item carry the list's pointer without an index
                # (``/items/title``): labels, file fields and the tab's draft
                # pointers (which add the index) all find them there.
                item_spec: dict[str, Any] = {"widget": "fieldset", "pointer": spec["pointer"]}
                self.classify(items, item_spec, name)
                spec["item"] = item_spec
                spec["item_label"] = items.get("title") or humanize(name)
            else:
                spec["widget"] = "tags"
                item_spec = {"widget": "input"}
                self.classify(items, item_spec, name)
                spec["item"] = item_spec
        elif _is_file_ref(prop):
            spec["widget"] = "file"
            for k in ("accept", "max_size_mb"):
                if k in prop:
                    spec[k] = prop[k]
        elif t == "object" or "properties" in prop:
            spec["widget"] = "fieldset"
            spec["fields"] = self.fields(prop, spec.get("pointer", ""))
            spec["title"] = prop.get("title")
        else:
            spec["widget"] = "input"

    def union(self, prop: Mapping[str, Any], spec: dict[str, Any]) -> None:
        branches = [self.resolve(b) for b in prop.get("oneOf") or prop.get("anyOf") or []]
        disc = prop.get("discriminator", {})
        key = disc.get("propertyName") if isinstance(disc, Mapping) else None
        variants: list[dict[str, Any]] = []
        for b in branches:
            tag = None
            props = b.get("properties", {})
            if key and key in props:
                tag_schema = self.resolve(props[key])
                tag = tag_schema.get("const") or (tag_schema.get("enum") or [None])[0]
            pointer = spec.get("pointer", "")
            fields = [f for f in self.fields(b, pointer) if f["name"] != key]
            variants.append(
                {"tag": tag, "label": b.get("title") or humanize(str(tag)), "fields": fields}
            )
        spec["widget"] = "union"
        spec["discriminator"] = key
        spec["variants"] = variants
