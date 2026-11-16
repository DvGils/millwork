"""Each example is an app in a directory of its own, run with
``millwork run examples/<name>/app.py``. Its tests get it the same way."""

import sys
from pathlib import Path
from types import ModuleType

import pytest

from millwork.cli import load_object


@pytest.fixture
def example(request: pytest.FixtureRequest) -> ModuleType:
    """The ``app.py`` beside the test, loaded anew for every test with the
    modules beside it, so that what one test put in the app's shared data
    is gone for the next, and one example never gets a module of another
    that has the same name."""
    home = Path(request.path).parent
    for name, module in list(sys.modules.items()):
        if (
            Path(getattr(module, "__file__", None) or "").parent == home
            and name != request.module.__name__
        ):
            del sys.modules[name]
    load_object(str(home / "app.py"))
    return sys.modules["app"]
