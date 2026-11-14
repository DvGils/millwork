"""Write a typed ``__init__`` into every catalogue component, for type checkers.

Pydantic gives a model an ``__init__`` of keyword fields in the type checker's
eyes, which refuses the positional children every component takes. Each
component class gets a signature under ``TYPE_CHECKING`` that a checker sees
and the runtime never runs: the explicit init's positional parameters, then
``*children``, then every field as a typed keyword argument. The annotations
and defaults are copied from the field declarations as written, so the block
reads like the class.

Run ``python scripts/typed_inits.py`` after changing a component's fields;
``--check`` exits 1 when a file would change, which the tests do.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "millwork"
MODULES = [
    ROOT / "nodes.py",
    ROOT / "ui" / "__init__.py",
    ROOT / "ui" / "table.py",
    ROOT / "ui" / "files.py",
    ROOT / "ui" / "form.py",
    ROOT / "ui" / "charts.py",
    ROOT / "ui" / "chat.py",
]
BASE = "Component"
# A field with a before-validator takes more than the field holds; the stub
# says what a call accepts. A key names the field, or ``Class.field``.
ACCEPTS = {
    "options": "Sequence[Option | str | tuple[str, str] | Mapping[str, Any]]",
    "Table.columns": "Sequence[Column | str | Mapping[str, Any]] | None",
    "Stat.trend": "Iterable[float] | None",
    "DatePicker.value": "str | dt.date | list[str | dt.date | None] | None",
    "DatePicker.default": "str | dt.date | list[str | dt.date | None] | None",
    "DatePicker.min": "str | dt.date | None",
    "DatePicker.max": "str | dt.date | None",
}
MARK = (
    "    if TYPE_CHECKING:  # the signature a type checker sees; written by scripts/typed_inits.py"
)


class Klass:
    def __init__(self, node: ast.ClassDef, module: Path) -> None:
        self.node = node
        self.module = module
        self.name = node.name
        self.bases = [ast.unparse(b) for b in node.bases]
        self.fields: dict[str, tuple[str, str | None]] = {}
        # Old names of keywords, each with the name that took its place.
        self.old_names: dict[str, str] = {}
        self.positional: list[str] = []
        self.explicit_init: ast.FunctionDef | None = None
        for stmt in node.body:
            if _assigns_old_names(stmt):
                self.old_names = dict(_renames(stmt.value, node.name))
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                annotation = ast.unparse(stmt.annotation)
                if name.startswith("_") or annotation.startswith("ClassVar"):
                    continue
                self.fields[name] = (annotation, _default(stmt.value))
            elif isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                self.explicit_init = stmt
            elif _is_type_checking(stmt):
                # After a first run the runtime's own __init__ lives in the
                # ``else`` of the block this script wrote.
                for inner in stmt.orelse:
                    if isinstance(inner, ast.FunctionDef) and inner.name == "__init__":
                        self.explicit_init = inner
        if self.explicit_init is not None:
            args = self.explicit_init.args
            params = args.posonlyargs + args.args
            self.positional = [
                f"{a.arg}: {ast.unparse(a.annotation) if a.annotation else 'Any'}"
                + (f" = {ast.unparse(d)}" if d is not None else "")
                for a, d in zip(params[1:], _defaults(params[1:], args.defaults), strict=True)
            ]


def _is_type_checking(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.If)
        and isinstance(stmt.test, ast.Name)
        and stmt.test.id == "TYPE_CHECKING"
    )


def _assigns_old_names(stmt: ast.stmt) -> bool:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [getattr(stmt, "target", None)]
    return any(isinstance(t, ast.Name) and t.id == "old_names" for t in targets)


def _renames(written: ast.expr | None, where: str) -> list[tuple[str, str]]:
    """``{"old": Renamed("new", ...)}`` as pairs of old and new. Anything
    else is refused: the signature has to be read off the source."""
    wrong = SystemExit(
        f'{where}.old_names has to be written out as {{"old": Renamed("new", ...)}}:'
        f" {ast.unparse(written) if written else 'no value'}"
    )
    if not isinstance(written, ast.Dict):
        raise wrong
    pairs = []
    for key, value in zip(written.keys, written.values, strict=True):
        new = value.args[0] if isinstance(value, ast.Call) and value.args else None
        if not (isinstance(key, ast.Constant) and isinstance(new, ast.Constant)):
            raise wrong
        pairs.append((key.value, new.value))
    return pairs


def _default(value: ast.expr | None) -> str | None:
    """The default as written, when a stub may carry it; ``...`` for the rest."""
    if value is None:
        return None
    if isinstance(value, ast.Constant | ast.Name | ast.Attribute | ast.UnaryOp):
        return ast.unparse(value)
    return "..."


def _defaults(params: list[ast.arg], defaults: list[ast.expr]) -> list[ast.expr | None]:
    padding: list[ast.expr | None] = [None] * (len(params) - len(defaults))
    return padding + list(defaults)


def collect() -> dict[str, Klass]:
    classes: dict[str, Klass] = {}
    for module in MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = Klass(node, module)
    return classes


def is_component(klass: Klass, classes: dict[str, Klass]) -> bool:
    if klass.name == BASE:
        return False
    return any(
        base == BASE or (base in classes and is_component(classes[base], classes))
        for base in klass.bases
    )


def all_fields(klass: Klass, classes: dict[str, Klass]) -> dict[str, tuple[str, str | None]]:
    """Base fields first, a subclass's own redefinitions in their base position."""
    fields: dict[str, tuple[str, str | None]] = {}
    for base in klass.bases:
        if base in classes:
            fields.update(all_fields(classes[base], classes))
    fields.update(klass.fields)
    return fields


def all_old_names(klass: Klass, classes: dict[str, Klass]) -> dict[str, str]:
    names: dict[str, str] = {}
    for base in klass.bases:
        if base in classes:
            names.update(all_old_names(classes[base], classes))
    names.update(klass.old_names)
    return names


def positional(klass: Klass, classes: dict[str, Klass]) -> list[str]:
    """The nearest explicit init's positional parameters: the class's own, or
    the ones it inherits from a base in the catalogue."""
    if klass.explicit_init is not None:
        return klass.positional
    for base in klass.bases:
        if base in classes and base != BASE:
            found = positional(classes[base], classes)
            if found:
                return found
    return []


def signature(klass: Klass, classes: dict[str, Klass]) -> list[str]:
    fields = all_fields(klass, classes)
    params = positional(klass, classes)
    positional_names = {p.split(":")[0] for p in params}
    old_names = all_old_names(klass, classes)
    for old, new in old_names.items():
        # A keyword renamed twice goes by the name it has now.
        seen = {old}
        while new in old_names:
            if new in seen:
                raise SystemExit(f"{klass.name}.old_names goes in a circle at {new!r}")
            seen.add(new)
            new = old_names[new]
        if new not in fields:
            raise SystemExit(f"{klass.name}.old_names: {old!r} is now {new!r}, which is no field")
        old_names[old] = new

    def accepted(name: str, annotation: str) -> str:
        """What a call may pass for a field. A renamed field keeps what was
        written down for it under its old name."""
        for known in (name, *(old for old, new in old_names.items() if new == name)):
            for key in (f"{klass.name}.{known}", known):
                if key in ACCEPTS:
                    return ACCEPTS[key]
        return annotation

    # A keyword that may still come under its old name cannot be required
    # under the new one: the checker accepts every call the runtime does.
    renamed = set(old_names.values())
    lines = [MARK, "", "        def __init__(", "            self,"]
    optional = False
    for p in params:
        # A parameter after an optional one is optional too, or it is no signature.
        optional = optional or " = " in p or p.split(":")[0] in renamed
        if optional and " = " not in p:
            p += " = ..."
        lines.append(f"            {p}," + ("  # noqa: UP006" if "Type[" in p else ""))
    lines.append("            *children: Any,")
    for name, (annotation, default) in fields.items():
        if name in positional_names or name == "children":
            continue
        annotation = accepted(name, annotation)
        if name in renamed and not default:
            default = "..."
        line = f"            {name}: {annotation}" + (f" = {default}," if default else ",")
        if annotation.startswith("Type["):
            # ``type`` in a class body is the component's wire name.
            line += "  # noqa: UP006"
        lines.append(line)
    # A call that still uses an old name passes the checker as it passes at
    # runtime, where it warns.
    for old, new in old_names.items():
        annotation = accepted(new, fields[new][0])
        lines.append(f"            {old}: {annotation} = ...,  # the old name of {new}")
    lines.append("        ) -> None: ...")
    return lines


def rewrite(module: Path, classes: dict[str, Klass]) -> str:
    source = module.read_text(encoding="utf-8")
    lines = source.split("\n")
    mine = [k for k in classes.values() if k.module == module and is_component(k, classes)]
    # Bottom up, so earlier line numbers stay valid.
    for klass in sorted(mine, key=lambda k: k.node.lineno, reverse=True):
        block = signature(klass, classes)
        existing = next((s for s in klass.node.body if _is_type_checking(s)), None)
        if existing is not None:
            # Only the checker's branch is rewritten; an ``else`` with the
            # runtime's own __init__ stays as written.
            start, end = existing.lineno - 1, existing.body[-1].end_lineno
        elif klass.explicit_init is not None:
            # A class with its own __init__ keeps it, in the ``else`` the
            # checker never reads, so the two never disagree in its eyes.
            init = klass.explicit_init
            start, end = init.lineno - 1, init.end_lineno
            block = block + ["    else:"] + [("    " + ln if ln else ln) for ln in lines[start:end]]
        else:
            last = klass.node.body[-1]
            start = end = last.end_lineno
            block = [""] + block
        assert end is not None
        lines[start:end] = block
    text = "\n".join(lines)
    if "TYPE_CHECKING" not in source.split("\n\n\n")[0]:
        text = text.replace("from typing import ", "from typing import TYPE_CHECKING, ", 1)
    return text


def formatted(text: str) -> str:
    """The generated source as ruff formats it, so the committed file and the
    generator agree to the quote."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "-"],
        input=text,
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT.parent.parent,
    )
    return result.stdout


def main(argv: list[str]) -> int:
    check = "--check" in argv
    classes = collect()
    changed = []
    for module in MODULES:
        new = formatted(rewrite(module, classes))
        if new != module.read_text(encoding="utf-8"):
            changed.append(module)
            if not check:
                module.write_text(new, encoding="utf-8")
    if check and changed:
        names = ", ".join(str(m.relative_to(ROOT.parent.parent)) for m in changed)
        print(f"typed signatures are stale in {names}; run scripts/typed_inits.py", file=sys.stderr)
        return 1
    print(f"{len(changed)} file(s) {'would change' if check else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
