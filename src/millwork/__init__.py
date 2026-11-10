"""millwork: a Python framework for data tools and AI applications."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("millwork")
except PackageNotFoundError:  # a checkout that is not installed
    __version__ = "0.0.0"

from millwork import auth, context, theme
from millwork.app import App, PageDef
from millwork.auth import Forbidden, NotFound, User
from millwork.chat import ChatTurn, Reply, UIMessage
from millwork.files import FileRef, Files
from millwork.icons import ICONS
from millwork.nodes import Component
from millwork.session import Session
from millwork.tasks import Cancelled, Step, Task, progress
from millwork.visitors import Visitor

# Importing the ``millwork.session`` submodule bound its name here; ``mw.session()``
# is the function that returns the current session.
session = context.session

__all__ = [
    "App",
    "Cancelled",
    "ChatTurn",
    "Component",
    "FileRef",
    "Forbidden",
    "Files",
    "ICONS",
    "NotFound",
    "PageDef",
    "Reply",
    "Session",
    "Step",
    "Task",
    "UIMessage",
    "User",
    "Visitor",
    "__version__",
    "auth",
    "theme",
    "progress",
    "session",
]
