"""Everything that waits on a session's behalf.

A session's state changes only in the steps of ``millwork.session``, none of
which waits. What waits is here: the session's life, which alone opens and
closes its pages, the children that run handlers, hooks and requests in the
session's scope, and the awaited half of the session's API. None of it
writes the session's fields. It calls steps.

After a wait, code here need not ask whether the session is still there. A
child of a session that ended was cancelled, and the cancellation is what
the wait raises. Nothing here turns its own cancellation into anything else.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from millwork import context
from millwork.auth import Forbidden, NotFound
from millwork.files import Reject
from millwork.forms import FormIssues
from millwork.protocol import Event, Head, Reply, Request, Stream, pack_frame
from millwork.tasks import Cancelled
from millwork.ui import as_options

if TYPE_CHECKING:
    from millwork.app import PageDef
    from millwork.chat import ChatTurn
    from millwork.connection import Connection, Pipe
    from millwork.nodes import Component
    from millwork.session import Plan, Session, Want
    from millwork.tasks import Task

log = logging.getLogger("millwork.session")

# How long a session waits for its children to stop once it is over, before
# it names the ones that have not and goes on without them.
STOP_PATIENCE_SECONDS = 5.0
# How long a page's close hook may take. One that takes longer is cancelled,
# so that it cannot keep its session, or the app's shutdown, waiting for good.
CLOSE_LIMIT_SECONDS = 30.0
# How long a stream waits for a tab that has fallen behind before it goes on.
ROOM_PATIENCE_SECONDS = 5.0
STREAM_CHUNK = 256 * 1024

Outcome = tuple[str, BaseException | None]


async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


# ------------------------------------------------------------------ the life


async def live(s: Session[Any]) -> None:
    """A session's life: its pages, one after another, and then its end.

    Only this opens and closes a page. So a page is closed exactly once, its
    close hook runs to its end whatever becomes of the handler or the
    navigation that was leaving it, and two connects never run side by side.
    While a page is being switched this holds the session's turn.
    """
    me = asyncio.current_task()
    want: Want | None = None
    connecting: asyncio.Future[Outcome] | None = None
    try:
        while True:
            await s.idle()
            if s.over:
                break
            await _or_over(s, s.turn.ask(me))
            if s.over:
                break
            want = s.take_wanted()
            if not want.first:
                if not await stay_current(s):
                    break
                target = s.aim(want)
                if target is not None:
                    # Leaving comes first. The page's close hook sees the
                    # state as the page left it, before the next page's
                    # connect writes to it, which matters most when the next
                    # page is this one with other parameters.
                    if s.owed is not None:
                        await close_page(s)
                    if s.over:
                        break
                    page, params, path, _ = target
                    s.enter(page, params, path)
            if want.first or target is not None:
                connecting = _connect(s)
                await _or_over(s, connecting)
                if not connecting.done():
                    break
                s.settle_page(want, *connecting.result())
                connecting = None
            s.turn.give_back(me)
            _arrived(want)
            want = None
    finally:
        s.dismiss()
        s.turn.give_back(me)
        await s.scope.wait(STOP_PATIENCE_SECONDS)
        if want is not None and connecting is not None and connecting.done():
            # A connect that returned all the same is owed its close.
            s.settle_page(want, *connecting.result())
        if s.owed is not None:
            await close_page(s)
        if want is not None:
            _arrived(want)


def _arrived(want: Want) -> None:
    if want.done is not None and not want.done.done():
        want.done.set_result(None)


async def _or_over(s: Session[Any], future: asyncio.Future[Any]) -> None:
    """Wait for ``future``, or for the session to be over, whichever is first."""
    if not future.done() and not s.ended.done():
        await asyncio.wait([future, s.ended], return_when=asyncio.FIRST_COMPLETED)


def _connect(s: Session[Any]) -> asyncio.Future[Outcome]:
    """Open the session's page as a child, so that the end can stop it. The
    future always gets an answer: ok, failed or cancelled."""
    outcome: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()

    def done(child: asyncio.Task[Any] | None) -> None:
        if child is None or child.cancelled():
            outcome.set_result(("cancelled", None))
        elif child.exception() is not None:
            outcome.set_result(("failed", child.exception()))
        else:
            outcome.set_result(child.result())

    s.scope.start(open_page(s), f"connect {s.path}", done=done)
    return outcome


async def open_page(s: Session[Any]) -> Outcome:
    """Connect the page the session is on. When its rule refuses, or its hook
    does with NotFound or Forbidden, land on the app's page for that instead,
    under the path that was asked for. A page that refuses by its rule never
    runs its connect hook."""
    try:
        # A page whose connect is skipped (the test harness, handing the
        # session its state) is not owed a close for it.
        opened = "ok" if s.runs_connect else "unhooked"
        verdict = s.app.may(s.user, s.page, s.params)
        if not verdict.ok:
            s.fall_back("forbidden", verdict.message)
            await _run_connect(s)
            return opened, None
        try:
            await _run_connect(s)
        except (Forbidden, NotFound) as exc:
            if not s.falls_back:
                return "failed", exc
            s.fall_back("forbidden" if isinstance(exc, Forbidden) else "not_found", exc.message)
            await _run_connect(s)
        return opened, None
    except Exception as exc:
        log.exception("connect failed for %s", s.path)
        s._failed(f"the connect hook of {s.path}", exc)
        return "failed", exc


async def _run_connect(s: Session[Any]) -> None:
    """The page's connect hook, in the session's context. The page is open
    once it returns, and owed a close."""
    if s.page.on_connect is None or not s.runs_connect:
        return
    token = context.bind(s)
    try:
        await _call(s.page.on_connect, s, **s.params)
    finally:
        context.unbind(token)


async def close_page(s: Session[Any]) -> None:
    """The page's close hook, once per visit: the session is done with the
    page, by moving to another or by ending. The state is still as the page
    left it."""
    page: PageDef | None = s.take_owed()
    if page is None or page.on_close is None:
        return
    try:
        async with asyncio.timeout(CLOSE_LIMIT_SECONDS):
            await _call(page.on_close, s)
    except TimeoutError:
        log.error(
            "close hook of %s took over %g s for session %s and was stopped",
            page.path,
            CLOSE_LIMIT_SECONDS,
            s.id,
        )
    except asyncio.CancelledError:
        # The hook waited on work of the session's that the end had just
        # cancelled. That is the hook's failure, not a reason to stop
        # ending. Only a cancellation of this task itself passes on.
        me = asyncio.current_task()
        if me is not None and me.cancelling():
            raise
        log.warning("close hook of %s was cancelled for session %s", page.path, s.id)
    except Exception as exc:
        log.exception("close hook of %s failed for session %s", page.path, s.id)
        s._failed(f"the close hook of {page.path}", exc)


# ------------------------------------------------------------------ children


async def event(s: Session[Any], event: Event, visit: int) -> None:
    """Something happened on a node of the page. What needs no turn is done
    in a step. A handler is run in a turn. ``visit`` is the visit of a page
    the session was on when the event came in.

    Events are dealt with in the order they came in. Each waits at the
    session's door for the one before it to have been looked at and to
    stand in line for the turn, so one that has to wait on the way, for
    the user to be checked again or for a part of the page to be built,
    is not passed by one that does not.
    """
    async with s.door:
        if not await stay_current(s):
            return
        if event.name == "show":
            s.shown(event)
            return
        if s.kept_part(event.node) is not None:
            # A lazy part that does not show stays in the tab as it was last
            # drawn, and something in it can still speak: an upload that was
            # on its way, a change a field was holding. What may be called
            # is what the page offers now, so the part is built again first.
            # That takes the turn, which is kept for the handler.
            await s.turn.take(asyncio.current_task())
            if visit != s.visit or not s.bring_up(event.node):
                log.debug("event %s for %s dropped: its part is gone", event.name, event.node)
                return
        if visit != s.visit:
            # It was sent from a page the session has left since. The page
            # it is on now can have a node by the same id.
            return
        plan = s.sort(event)
        if plan is None:
            return
    # Out of the door and into the line for the turn in one step, so the
    # next event cannot get there first.
    await turn(s, plan)


async def turn(s: Session[Any], plan: Plan) -> None:
    """One turn: a handler, from the moment it gets the turn. The turn is
    given back by the session's scope when this is done, however it ends."""
    await s.turn.take(asyncio.current_task())
    if plan.visit is not None and plan.visit != s.visit:
        # The page it was meant for has been left.
        return
    token = context.bind(s)
    rejected = False
    try:
        if plan.question is not None:
            title, destructive = plan.question
            if not await confirm(s, title, destructive=destructive):
                return
            if plan.visit is not None and plan.visit != s.visit:
                # The page it was meant for was left while the question stood.
                return
        before = s._handler_begins()
        await _call(plan.handler, *plan.args)
        if plan.event is not None:
            s._handler_ended(plan.where, before)
    except FormIssues as exc:
        if plan.event is None:
            _report(s, plan, exc)
        else:
            rejected = True
            issues = [i.model_dump() for i in exc.issues]
            s.command("form_issues", node=plan.event.node, issues=issues)
    except Exception as exc:
        _report(s, plan, exc)
    finally:
        context.unbind(token)
    if plan.form is not None and not rejected:
        # The empty issue list is the form's acknowledgement: the draft was accepted.
        s.command("form_issues", node=plan.form, issues=[])
    s.refresh()


def _report(s: Session[Any], plan: Plan, exc: Exception) -> None:
    log.error(plan.said, exc_info=exc)
    s._failed(plan.where, exc)
    s.toast(s.text("something_went_wrong"), tone="destructive")


async def chat_turn(s: Session[Any], handler: Callable[..., Any], turn: ChatTurn) -> None:
    """A chat's ``on_message``, outside the turn: tool steps, tasks and
    inline components render while it streams. The chat is free again when
    the scope sees this done."""
    token = context.bind(s)
    try:
        await _call(handler, s, turn)
    except Exception as exc:
        log.exception("chat handler failed")
        s._failed("the chat handler", exc)
        s.toast(s.text("reply_failed"), tone="destructive")
    finally:
        context.unbind(token)


async def recheck(s: Session[Any]) -> None:
    if await stay_current(s):
        s.watch_user(s._identified)


async def request(
    s: Session[Any], conn: Connection, msg: Request, pipe: Pipe | None, visit: int
) -> None:
    """Answer a ``request`` with a ``reply``, over the connection it came in
    on, without a render.

    ``file`` streams one of the session's files to the tab; ``upload`` stores
    the bytes that follow the message; any other name is a handler on the
    node, run outside the turn (a search never waits on a click), whose
    return value is the payload.

    A handler on a node in a lazy part that does not show is the one
    exception to not waiting: the part is built again first, which takes a
    turn. An upload for such a node does not wait, since its bytes are on
    their way. It goes by what the part allowed when it was last drawn, and
    the event that hands the file to the app is checked like any event.
    """
    if not await stay_current(s):
        conn.say(Reply(request=msg.request, error=s.text("sign_in_hint")))
        return
    if msg.name == "file":
        await _serve_file(s, conn, msg)
    elif msg.name == "upload":
        await _receive_upload(s, conn, msg, pipe)
    elif s.kept_part(msg.node) is not None and not await _brought_up(s, msg.node, visit):
        conn.say(Reply(request=msg.request, error="unknown request"))
    else:
        await _ask_handler(s, conn, msg)


async def _brought_up(s: Session[Any], node: str, visit: int) -> bool:
    """Build the kept part a node is in, in a turn taken for it and given
    back. False when the node cannot be answered for."""
    me = asyncio.current_task()
    try:
        await s.turn.take(me)
        return visit == s.visit and s.bring_up(node)
    finally:
        # Also for one that was cancelled as the turn came to it.
        s.turn.give_back(me)


async def _ask_handler(s: Session[Any], conn: Connection, msg: Request) -> None:
    tree = s.tree
    component = tree.components.get(msg.node) if tree is not None else None
    handler = tree.handler(msg.node, msg.name) if tree is not None and component else None
    if handler is None or getattr(component, "disabled", False) or msg.size is not None:
        conn.say(Reply(request=msg.request, error="unknown request"))
        return
    token = context.bind(s)
    try:
        result = await _call(handler, s, msg.payload)
        if isinstance(result, list):
            result = [
                o.model_dump(exclude_none=True, exclude_defaults=True) for o in as_options(result)
            ]
        conn.say(Reply(request=msg.request, payload=result))
    except Exception as exc:
        log.exception("request %s on %s failed", msg.name, msg.node)
        s._failed(f"the {msg.name} handler on {msg.node}", exc)
        conn.say(Reply(request=msg.request, error="The request failed."))
    finally:
        context.unbind(token)


async def _serve_file(s: Session[Any], conn: Connection, msg: Request) -> None:
    """One of the session's files, as a ``head`` and binary frames, then the reply.

    A few at a time per session, so a tab cannot hold an open file per
    request. Each frame waits for the tab that asked, and for nobody else.
    """
    file_id = msg.payload.get("id") if isinstance(msg.payload, dict) else None
    ref = s.files.get(file_id) if isinstance(file_id, str) else None
    if ref is None or not ref.path.is_file():
        conn.say(Reply(request=msg.request, error="no such file"))
        return
    async with s._file_slots:
        conn.say(
            Head(
                request=msg.request, payload={"name": ref.name, "mime": ref.mime, "size": ref.size}
            )
        )
        sent = 0
        with ref.path.open("rb") as fh:
            while True:
                chunk = await asyncio.to_thread(fh.read, STREAM_CHUNK)
                if not chunk:
                    break
                if not await conn.frame(pack_frame(msg.request, chunk)):
                    return
                sent += len(chunk)
    conn.say(Reply(request=msg.request, payload={"size": sent}))


async def _receive_upload(
    s: Session[Any], conn: Connection, msg: Request, pipe: Pipe | None
) -> None:
    """Store the bytes that follow an ``upload`` request as a session file.

    Frames are taken off the pipe on the loop and each write goes to a
    thread, so an upload that stalls holds a queue, never a thread.
    """
    payload = msg.payload if isinstance(msg.payload, dict) else {}
    writer = None
    try:
        if pipe is None or msg.size is None:
            raise Reject("an upload needs a size")
        field = payload.get("field")
        accept, max_bytes = s.upload_spec(msg.node, field if isinstance(field, str) else None)
        if msg.size > max_bytes:
            mb = max_bytes // (1024 * 1024)
            raise Reject(f"the file is larger than {mb} MB", key="file_too_large", vars={"mb": mb})
        name = payload.get("name")
        mime = payload.get("mime")
        writer = s.app.files.begin(
            s,
            name if isinstance(name, str) and name else "file",
            mime=mime if isinstance(mime, str) else None,
            max_bytes=max_bytes,
            accept=accept,
            node=msg.node,
        )
        while True:
            chunk = await pipe.get()
            if chunk is None:
                break
            await asyncio.to_thread(writer.write, chunk)
        ref = await asyncio.to_thread(writer.finish)
    except Reject as exc:
        if writer is not None:
            writer.abort()
        # In the theme's words where the refusal is one of the framework's.
        said = s.text(exc.key, **(exc.vars or {})) if exc.key else exc.reason
        conn.say(Reply(request=msg.request, error=said))
        return
    except asyncio.CancelledError:
        if writer is not None:
            writer.abort()
            if writer.ref is not None:
                # It finished in its thread in the same moment. The tab is
                # told nothing of it, so it is not kept.
                s.files.remove(writer.ref.id)
        raise
    except Exception as exc:
        log.exception("upload on %s failed", msg.node)
        s._failed(f"the upload handler on {msg.node}", exc)
        if writer is not None:
            writer.abort()
        conn.say(Reply(request=msg.request, error=s.text("file_failed")))
        return
    conn.say(Reply(request=msg.request, payload=ref.__millwork_wire__()))


# ------------------------------------------------------------------ the awaited API


async def stay_current(s: Session[Any]) -> bool:
    """Confirm that this session's user is still who the session began
    with. False when the session is over because of the answer.

    A session belongs to the user it started with: its page was drawn
    for them, and its state, its tasks and its files were gathered for
    them. So when ``recheck`` says the user is someone else now, in role
    or in anything, the session ends and the tab loads the page anew,
    into a session of the user as they are. When it says they are no
    longer welcome, their sign-in ends. When it cannot say, the session
    goes on for as long as the last answer is no older than twice the
    interval, and then ends: an outage of a moment costs nobody their
    page, and a long one does not leave the door open."""
    auth = s.app.auth
    if s.over:
        return False
    if auth is None or s._identified is None:
        return True
    key, given = s._identified
    here = s.path.split("#", 1)[0]
    if auth.identified_as(key, given) != given:
        # The same person has since been identified as someone else, by a
        # proxy whose word changed: this session is of who they were.
        s.dismiss(s.text("sign_in_hint"), to=s.leaving_for(here))
        return False
    try:
        fresh = await auth.current(key, given)
    except Exception:
        age = auth.answer_age(key, given)
        if age is not None and age < 2 * auth.recheck_every:
            return not s.over
        log.error("session %s ended: recheck has not answered for its user", s.id)
        s.dismiss(s.text("try_again"))
        return False
    if s.over:
        return False
    if fresh is None:
        if s.sign_in is not None:
            s.app.end_sign_in(s.sign_in, s.user)
        else:
            s.dismiss(s.text("sign_in_hint"), to=s.leaving_for(None))
        return False
    if fresh != s.user:
        s.dismiss(s.text("sign_in_hint"), to=s.leaving_for(here))
        return False
    return True


async def end(s: Session[Any], message: str, *, to: str | None = None) -> None:
    """Close the session and tell its tab why, so the tab stops instead of
    reconnecting: signed out elsewhere, or made room for a newer session.
    With ``to`` the tab is sent there.

    The session is over as this is called. In a handler, a task or a hook
    of the session itself nothing after this line runs. From anywhere else
    it returns at once, and ``session.gone`` is there to wait on for the
    page to be closed."""
    s.dismiss(message, to=to)
    me = asyncio.current_task()
    if me is not None and s.scope.owns(me):
        # One of the session's own, which the end has cancelled. This is
        # where the cancellation reaches it, also one that had caught its
        # cancellation before and ends the session from a ``finally``.
        me.cancel()
        await asyncio.get_running_loop().create_future()


async def leave(s: Session[Any], to: str | None = None) -> None:
    """End the session and send its tab away: to ``to``, or to the login
    page for a page that needs a sign-in, or back onto a public page as a
    visitor."""
    await end(s, s.text("sign_in_hint"), to=s.leaving_for(to))


def _lender(s: Session[Any]) -> asyncio.Task[Any] | None:
    """Who may lend a turn: a child of the session that holds it. A hook
    runs in the session's life, whose turn is held for the page switch and
    is nobody's to lend."""
    me = asyncio.current_task()
    return me if s.scope.owns(me) else None


async def ask(s: Session[Any], component: Component, timeout: float | None = None) -> Any:  # noqa: ASYNC109
    """Render a component, wait for its submit or close, return the answer or None.

    The turn is lent while waiting, so other handlers run. A ``Form`` inside
    answers with its validated model; a ``Dialog``'s close, a cancel, or a
    timeout answers ``None``. So does a question with no page to show it on:
    from a connect or a close hook, or on a session that is over. The session
    ending cancels the handler itself, as it does any other work.
    """
    if not s.ready:
        return None
    asked = s.open_ask(component)
    try:
        async with s.turn.lent(_lender(s), lambda: s.over):
            if timeout:
                return await asyncio.wait_for(asked.future, timeout)
            return await asked.future
    except TimeoutError:
        return None
    finally:
        s.close_ask(asked)


async def confirm(
    s: Session[Any],
    title: str,
    description: str | None = None,
    ok: str | None = None,
    cancel: str | None = None,
    destructive: bool = False,
) -> bool:
    """Ask a yes-or-no question in a dialog and wait for the answer. The
    buttons say ``ok`` and ``cancel``, or the theme's words for them."""
    answer = await ask(s, s._confirm_dialog(title, description, ok, cancel, destructive))
    return answer is True


async def wait_for_task(s: Session[Any], task: Task[Any]) -> Any:
    """``await task`` from a handler: renders keep flowing while it runs.

    A cancelled task raises ``millwork.Cancelled`` (an ordinary exception the
    handler can catch). A handler that is itself being cancelled, by its
    session ending or by a timeout of its own, gets that cancellation.
    """
    async with s.turn.lent(_lender(s), lambda: s.over):
        try:
            return await asyncio.shield(task.future)
        except asyncio.CancelledError:
            me = asyncio.current_task()
            if me is not None and me.cancelling():
                raise
            if task.status == "cancelled":
                raise Cancelled(task.label) from None
            raise


async def stream(s: Session[Any], node: str, chunk: dict[str, Any]) -> None:
    """One chunk of the AI SDK UI message stream to a Chat node. Never touches the tree.

    A stream is the one thing that waits for its tab: when the tab has
    fallen far behind what the session has said, the reply holds on for it
    for a moment. That paces a reply to the tab that reads it, and holds up
    nobody else.
    """
    s.post(Stream(node=node, chunk=chunk))
    conn = s.conn
    if conn is None or s.outbox.seq - conn.cursor <= s.outbox.keep // 2:
        return
    me = asyncio.current_task()
    if me is not None and me.cancelling():
        # Finishing up after a stop: what is left to say is said without a wait.
        return
    await conn.room(s.outbox.keep // 4, ROOM_PATIENCE_SECONDS)


async def navigate_to(s: Session[Any], path: str) -> None:
    """Switch this session to another page and wait until it is there. The
    state stays; the page left is closed before the next one connects. A
    handler that awaits this lends its turn meanwhile.

    From a connect or a close hook the page is only asked for, and this
    returns at once: the session goes there once the hook has returned,
    which it cannot do while the hook waits for it.
    """
    arrived = s.want(path)
    if not s.ready:
        return
    async with s.turn.lent(_lender(s), lambda: s.over):
        await asyncio.shield(arrived)
