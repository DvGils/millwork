"""The rules a session's design rests on, read off the source.

A session's state changes only in steps that do not wait. Everything that
waits is started through a scope. Only a connection writes to a socket.
Nothing swallows its own cancellation. These are what make the session's
promises hold by construction, so they are checked where a change that
breaks one would otherwise look harmless.
"""

import ast
from pathlib import Path

import millwork

SRC = Path(millwork.__file__).parent
FILES = {p.name: ast.parse(p.read_text()) for p in sorted(SRC.glob("*.py"))}


def calls(tree: ast.AST) -> set[str]:
    """The names of everything called, as the last part of a dotted name."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            out.add(fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", ""))
    return out


def test_nothing_in_the_session_waits() -> None:
    waits = (ast.AsyncFunctionDef, ast.Await, ast.AsyncWith, ast.AsyncFor)
    found = [n.lineno for n in ast.walk(FILES["session.py"]) if isinstance(n, waits)]
    assert found == [], f"session.py waits at lines {found}: a step runs from start to end"


def test_tasks_and_timers_are_started_through_a_scope() -> None:
    starters = {"create_task", "ensure_future", "call_later", "call_at", "gather", "TaskGroup"}
    found = {name: sorted(calls(tree) & starters) for name, tree in FILES.items()}
    assert {name: used for name, used in found.items() if used} == {
        "scope.py": ["call_later", "create_task"]
    }


def test_only_a_connection_writes_to_a_socket() -> None:
    writers = {"send_text", "send_bytes", "send_json"}
    found = {name for name, tree in FILES.items() if calls(tree) & writers}
    # The endpoint refuses a tab before there is a session to speak for.
    assert found == {"connection.py", "ws.py"}


def test_what_waits_does_not_write_a_sessions_fields() -> None:
    # Everything in work.py takes the session as ``s``. It calls steps, and
    # assigns nothing.
    written = [
        (target.attr, node.lineno)
        for node in ast.walk(FILES["work.py"])
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "s"
    ]
    assert written == []


def test_a_session_is_only_set_up_from_outside_never_changed() -> None:
    # Who it is for and how it is to behave, said before its life begins.
    set_up = {
        "user",
        "visitor",
        "base",
        "client",
        "falls_back",
        "runs_connect",
        "state",
        "on_failure",
        "on_unheard",
    }
    names = {"session", "candidate", "newcomer", "oldest"}
    written = set()
    for name, tree in FILES.items():
        if name == "session.py":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id in names
                    ):
                        written.add((name, target.attr))
    assert {attr for _, attr in written} <= set_up, written


def test_nothing_swallows_its_own_cancellation() -> None:
    # Whoever catches a cancellation raises it again, or first looks at
    # whether it is the one being cancelled.
    swallowed = []
    for name, tree in FILES.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            caught = ast.unparse(node.type)
            if "CancelledError" not in caught and "BaseException" not in caught:
                continue
            body = ast.Module(body=node.body, type_ignores=[])
            raises = any(isinstance(n, ast.Raise) for n in ast.walk(body))
            if not raises and "cancelling" not in calls(body):
                swallowed.append(f"{name}:{node.lineno}")
    assert swallowed == []
