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
        self.positional: list[str] = []
        self.explicit_init: ast.FunctionDef | None = None
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                annotation = ast.unparse(stmt.annotation)
                if name.startswith("_") or annotation.startswith("ClassVar"):
                    continue
                self.fields[name] = (annotation, _default(stmt.value))
            elif isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                self.explicit_init = stmt
        if self.explicit_init is not None:
            args = self.explicit_init.args
            params = args.posonlyargs + args.args
            self.positional = [
                f"{a.arg}: {ast.unparse(a.annotation) if a.annotation else 'Any'}"
                + (f" = {ast.unparse(d)}" if d is not None else "")
                for a, d in zip(params[1:], _defaults(params[1:], args.defaults), strict=True)
            ]


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
        tree = ast.parse(module.read_text())
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


def signature(klass: Klass, classes: dict[str, Klass]) -> list[str]:
    fields = all_fields(klass, classes)
    positional_names = {p.split(":")[0] for p in klass.positional}
    lines = [MARK, "", "        def __init__(", "            self,"]
    for p in klass.positional:
        lines.append(f"            {p},")
    lines.append("            *children: Any,")
    for name, (annotation, default) in fields.items():
        if name in positional_names or name == "children":
            continue
        line = f"            {name}: {annotation}" + (f" = {default}," if default else ",")
        if annotation.startswith("Type["):
            # ``type`` in a class body is the component's wire name.
            line += "  # noqa: UP006"
        lines.append(line)
    lines.append("        ) -> None: ...")
    return lines


def rewrite(module: Path, classes: dict[str, Klass]) -> str:
    source = module.read_text()
    lines = source.split("\n")
    mine = [k for k in classes.values() if k.module == module and is_component(k, classes)]
    # Bottom up, so earlier line numbers stay valid.
    for klass in sorted(mine, key=lambda k: k.node.lineno, reverse=True):
        block = signature(klass, classes)
        existing = next(
            (
                s
                for s in klass.node.body
                if isinstance(s, ast.If)
                and isinstance(s.test, ast.Name)
                and s.test.id == "TYPE_CHECKING"
            ),
            None,
        )
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
        if new != module.read_text():
            changed.append(module)
            if not check:
                module.write_text(new)
    if check and changed:
        names = ", ".join(str(m.relative_to(ROOT.parent.parent)) for m in changed)
        print(f"typed signatures are stale in {names}; run scripts/typed_inits.py", file=sys.stderr)
        return 1
    print(f"{len(changed)} file(s) {'would change' if check else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
