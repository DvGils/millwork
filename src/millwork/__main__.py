"""``python -m millwork``: the ``millwork`` command by the interpreter it runs
under, for a script that starts a server with ``sys.executable``."""

import sys

from millwork.cli import main

if __name__ == "__main__":
    sys.exit(main())
