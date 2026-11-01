"""Tasks: long-running work owned by the session, reported through ``progress()``.

A ``Task`` is an asyncio task wrapped in an object that
is also state: a page renders it like any other value. Sync callables run
in a thread with the session context copied in, so ``progress()`` works
there too; reports marshal onto the loop and schedule a coalesced render.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import inspect
import logging
import secrets
import threading
from collections.abc import Callable, Iterator
from contextvars import ContextVar, copy_context
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from millwork.session import Session

log = logging.getLogger("millwork.tasks")

Status = Literal["pending", "running", "done", "failed", "cancelled"]
StepStatus = Literal["pending", "running", "done", "failed", "cancelled", "skipped"]
MAX_STEP_LINES = 200


class Cancelled(Exception):
    """Raised inside sync work by ``progress().check()`` after ``task.cancel()``."""


class TaskError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    message: str


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    status: StepStatus = "pending"
    note: str | None = None
    lines: list[str] = Field(default_factory=list)
    children: list[Step] = Field(default_factory=list)
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Task[T]:
    """What ``s.task()`` returns. Serialises to a snapshot the page can render."""

    def __init__(self, session: Session[Any], label: str, key: str | None, quiet: bool) -> None:
        self.id = secrets.token_urlsafe(8)
        self.key = key
        self.label = label
        self.status: Status = "pending"
        self.progress: float | None = None
        self.message: str | None = None
        self.steps: list[Step] = []
        self.started_at: dt.datetime | None = None
        self.finished_at: dt.datetime | None = None
        self.error: TaskError | None = None
        self.quiet = quiet

        self._session = session
        self._result: T | None = None
        self._future: asyncio.Future[T] = session._loop.create_future()
        self._observed = False
        self._cancel_flag = threading.Event()
        self._asyncio_task: asyncio.Task[Any] | None = None
        self._delay_handle: asyncio.TimerHandle | None = None
        self._on_done: Callable[..., Any] | None = None

    # ------------------------------------------------------------- reading

    @property
    def done(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    @property
    def ok(self) -> bool:
        return self.status == "done"

    @property
    def result(self) -> T:
        if not self.ok:
            raise RuntimeError(f"task {self.label!r} is {self.status}")
        return self._result  # type: ignore[return-value]

    @property
    def cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    @property
    def future(self) -> asyncio.Future[T]:
        self._observed = True
        return self._future

    def __await__(self) -> Any:
        """Awaiting from a handler lets renders through (the session releases its lock)."""
        self._observed = True
        return self._session.wait_for_task(self).__await__()

    async def _in_thread(self, fn: Callable[[], Any]) -> Any:
        """Run the work in a thread. In debug mode, state that changed while no
        handler ran on the loop was changed by the thread, which is the one thing
        a sync task may not do."""
        session = self._session
        watch = session.app.debug
        before = _snapshot(session.state) if watch else None
        runs = session._handler_runs
        result = await asyncio.to_thread(fn)
        reporter = _reporter.get()
        if reporter is not None:
            await reporter.drain()
        if watch and before is not None and runs == session._handler_runs:
            if _snapshot(session.state) != before:
                session.warn(
                    f"thread-state:{self.label}",
                    f"task {self.label} changed session state from its thread; report "
                    "through progress() and return a result instead",
                )
        return result

    def __millwork_wire__(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "steps": [s.model_dump(mode="json") for s in self.steps],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error.model_dump() if self.error else None,
        }

    # ------------------------------------------------------------- control

    def cancel(self) -> None:
        """Stop the work; what it already wrote stays."""
        if self.done:
            return
        self._cancel_flag.set()
        if self._delay_handle is not None:
            self._delay_handle.cancel()
            self._delay_handle = None
            self._finish("cancelled")
            return
        if self._asyncio_task is not None:
            self._asyncio_task.cancel()

    # ------------------------------------------------------------- internals

    def _start(
        self, work: Any, args: tuple[Any, ...], kwargs: dict[str, Any], timeout: float | None
    ) -> None:
        self.status = "running"
        self.started_at = _now()
        self._asyncio_task = self._session._loop.create_task(self._run(work, args, kwargs, timeout))
        self._session.refresh()

    async def _run(  # noqa: ASYNC109
        self, work: Any, args: tuple[Any, ...], kwargs: dict[str, Any], timeout: float | None
    ) -> None:
        from millwork import context

        token = context.bind(self._session)
        reporter_token = _reporter.set(Reporter(self))
        try:
            coro: Any
            if inspect.iscoroutine(work):
                coro = work
            elif inspect.iscoroutinefunction(work):
                coro = work(*args, **kwargs)
            elif callable(work):
                coro = self._in_thread(_in_context(copy_context(), work, *args, **kwargs))
            else:
                raise TypeError(
                    f"task work is a coroutine or a callable, not {type(work).__name__}"
                )
            result = await asyncio.wait_for(coro, timeout) if timeout else await coro
        except asyncio.CancelledError:
            self._finish("cancelled")
            return
        except Cancelled:
            self._finish("cancelled")
            return
        except TimeoutError:
            # A worker thread cannot be interrupted: the flag makes its next check() stop it.
            self._cancel_flag.set()
            self._fail(TimeoutError(f"task {self.label!r} exceeded {timeout} s"))
            return
        except Exception as exc:
            self._fail(exc)
            return
        finally:
            _reporter.reset(reporter_token)
            context.unbind(token)
        self._result = result
        self._finish("done")

    def _fail(self, exc: BaseException) -> None:
        log.exception("task %s (%s) failed", self.label, self.id, exc_info=exc)
        self.error = TaskError(type=type(exc).__name__, message=str(exc) or type(exc).__name__)
        self._finish("failed", exc)

    def _finish(self, status: Status, exc: BaseException | None = None) -> None:
        if self.done:
            return
        self.status = status
        self.finished_at = _now()
        for step in _walk_steps(self.steps):
            if step.status == "running":
                step.status = (
                    "cancelled"
                    if status == "cancelled"
                    else "failed"
                    if status == "failed"
                    else "done"
                )
                step.finished_at = self.finished_at
        if not self._future.done():
            if status == "done":
                self._future.set_result(self._result)  # type: ignore[arg-type]
            elif status == "cancelled":
                self._future.cancel()
            else:
                self._future.set_exception(
                    exc or RuntimeError(self.error.message if self.error else "failed")
                )
                # The toast is the report for a failure nobody awaits; mark the
                # exception seen so the loop does not log it again at collection.
                self._future.exception()
        if status == "failed" and not self._observed and not self.quiet:
            # An unobserved failure is never silent.
            self._session.toast(
                f"{self.label} failed: {self.error.message if self.error else ''}",
                tone="destructive",
            )
        self._session._task_finished(self)


def _in_context(ctx: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Callable[[], Any]:
    return lambda: ctx.run(fn, *args, **kwargs)


def _walk_steps(steps: list[Step]) -> Iterator[Step]:
    for s in steps:
        yield s
        yield from _walk_steps(s.children)


# ------------------------------------------------------------------ the reporter


class Reporter:
    """What ``progress()`` returns inside a task. Every report schedules a render."""

    def __init__(self, task: Task[Any]) -> None:
        self._task = task
        self._loop = task._session._loop
        # Reports handed over from a worker thread and not yet applied on the
        # loop. The loop may resume the task before it runs them, so the task
        # drains them before it finishes.
        self._queued = 0
        self._lock = threading.Lock()

    def _touch(self, fn: Callable[[], None]) -> None:
        """Run a mutation on the loop thread, then render. Safe from a worker thread.

        A report that arrives after the task ended (a thread running on past a
        timeout or a cancel) changes nothing.
        """
        try:
            on_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            if self._task.done:
                return
            fn()
            self._task._session.refresh()
        else:
            with self._lock:
                self._queued += 1
            self._loop.call_soon_threadsafe(self._handed_over, fn)

    def _handed_over(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._queued -= 1
        self._touch(fn)

    async def drain(self) -> None:
        """Wait until every report a thread handed over has been applied."""
        while True:
            with self._lock:
                pending = self._queued
            if not pending:
                return
            await asyncio.sleep(0)

    def set(self, value: float | None = None, message: str | None = None) -> None:
        def apply() -> None:
            if value is not None:
                self._task.progress = max(0.0, min(1.0, float(value)))
            if message is not None:
                self._task.message = message

        self._touch(apply)

    def log(self, line: str) -> None:
        stack = _steps.get()
        current = stack[-1] if stack else None

        def apply() -> None:
            if current is not None:
                current.lines.append(line)
                del current.lines[:-MAX_STEP_LINES]
            else:
                self._task.message = line

        self._touch(apply)

    def check(self) -> None:
        """Raise ``Cancelled`` after ``task.cancel()``; sync work calls this at sensible points."""
        if self._task.cancelled:
            raise Cancelled(self._task.label)

    def plan(self, labels: list[str]) -> None:
        """Declare steps ahead; ``step(label)`` then opens the one with that label."""
        stack = _steps.get()
        parent = stack[-1].children if stack else self._task.steps

        def apply() -> None:
            for label in labels:
                if not any(s.label == label for s in parent):
                    parent.append(Step(id=secrets.token_urlsafe(6), label=label))

        self._touch(apply)

    @contextlib.contextmanager
    def step(self, label: str) -> Iterator[StepHandle]:
        # The open steps live in a context variable, not on the reporter: work run
        # in parallel under one step (asyncio.gather, a thread) each sees its own
        # branch, so sibling steps never nest into each other.
        stack = _steps.get()
        parent = stack[-1].children if stack else self._task.steps
        step = Step(id=secrets.token_urlsafe(6), label=label)

        def open_() -> None:
            # Mutations are applied in order on the loop, so a planned placeholder
            # with this label (if any) is visible here and is taken over.
            planned = next((s for s in parent if s.label == label and s.status == "pending"), None)
            if planned is not None:
                parent[parent.index(planned)] = step
            else:
                parent.append(step)
            step.status = "running"
            step.started_at = _now()

        self._touch(open_)
        token = _steps.set((*stack, step))
        try:
            yield StepHandle(self, step)
        except BaseException as exc:
            cancelled = isinstance(exc, Cancelled | asyncio.CancelledError)
            self._close(step, "cancelled" if cancelled else "failed")
            raise
        else:
            self._close(step, "done")
        finally:
            _steps.reset(token)

    def _close(self, step: Step, status: StepStatus) -> None:
        def apply() -> None:
            step.status = status
            step.finished_at = _now()

        self._touch(apply)

    def callback(self) -> Callable[..., None]:
        """A ``(value, message)`` callable for code that already takes a progress callback."""

        def report(value: float | None = None, message: str | None = None) -> None:
            self.set(value, message)

        return report


class StepHandle:
    def __init__(self, reporter: Reporter, step: Step) -> None:
        self._reporter = reporter
        self._step = step

    def note(self, text: str) -> None:
        step = self._step

        def apply() -> None:
            step.note = text

        self._reporter._touch(apply)

    def log(self, line: str) -> None:
        self._reporter.log(line)


class _NoReporter:
    """Outside a task every call does nothing, so library code reports unconditionally."""

    def set(self, value: float | None = None, message: str | None = None) -> None:
        pass

    def log(self, line: str) -> None:
        pass

    def check(self) -> None:
        pass

    def plan(self, labels: list[str]) -> None:
        pass

    @contextlib.contextmanager
    def step(self, label: str) -> Iterator[Any]:
        yield _NoStep()

    def callback(self) -> Callable[..., None]:
        def report(value: float | None = None, message: str | None = None) -> None:
            return None

        return report


class _NoStep:
    def note(self, text: str) -> None:
        pass

    def log(self, line: str) -> None:
        pass


_reporter: ContextVar[Reporter | None] = ContextVar("millwork_progress", default=None)
_steps: ContextVar[tuple[Step, ...]] = ContextVar("millwork_steps", default=())
_none = _NoReporter()


def progress() -> Reporter | _NoReporter:
    """The current task's reporter, or a reporter that does nothing."""
    return _reporter.get() or _none


def _snapshot(state: Any) -> Any:
    """A comparable picture of the session state, or None when it cannot be taken."""
    try:
        if hasattr(state, "model_dump"):
            return repr(state.model_dump(mode="python"))
        return repr(state)
    except Exception:
        return None
