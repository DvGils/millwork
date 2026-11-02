"""The typed signatures in the catalogue are what the generator writes."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "typed_inits.py"


def test_the_typed_signatures_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
