"""The typed signatures in the catalogue are what the generator writes."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "typed_inits.py"


def test_the_stub_keeps_the_positional_parameter_and_what_a_validator_accepts() -> None:
    """The documented idioms type-check: ``ui.Form(Model)``, ``ui.BarChart(rows)``
    and ``ui.Select(options=["a"])``, whose field holds Options but takes strings."""
    import ast

    sys.path.insert(0, str(SCRIPT.parent))
    import typed_inits

    classes = typed_inits.collect()
    form = typed_inits.signature(classes["Form"], classes)
    model = "            model: Type[BaseModel] | None = None,  # noqa: UP006"
    assert form.index(model) < form.index("            *children: Any,")
    bar = typed_inits.signature(classes["BarChart"], classes)
    assert "            rows: Sequence[Any] = (),\n" in "\n".join(bar) + "\n"
    select = "\n".join(typed_inits.signature(classes["Select"], classes))
    assert "options: Sequence[Option | str | tuple[str, str] | Mapping[str, Any]]" in select
    ast.parse("class X:\n" + "\n".join(select.split("\n")[1:]))  # well-formed


def test_the_typed_signatures_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
