---
title: Sessions
order: 4
description: A page's connect and close hooks, and when a session begins, waits and ends.
related: /pages/visitors, /state/state-and-handlers, /components/tasks, /running/app-options
---

# Sessions

A session is one tab. It starts when the tab connects, holds the state,
the files, the identity and the tasks, and it outlives the page, since
the tab moves from page to page on the same session. Two tabs of one visitor are
two sessions with two states, and nothing is shared by being in the same
browser or signed in as the same person.

## Connect

A page can have a `connect` hook. It runs once each time the page is
opened, before the first render, with the path parameters as keyword
arguments, and it may be async. This is where a page loads what it needs,
starts a task, or decides that the visitor may not be here. Raising
`mw.NotFound()` or `mw.Forbidden(message)` from it lands the session on
the app's error page, as [Error pages](/pages/error-pages) describes.

```python
@project.connect
async def load(s: mw.Session[State], project_id: int) -> None:
    project = await db.project(project_id)
    if project is None:
        raise mw.NotFound()
    if s.user and s.user.id not in project.members:
        raise mw.Forbidden("Not your project.")
    s.state.project = project
    s.task(refresh_documents(s))


@project.close
async def leave(s: mw.Session[State]) -> None:
    await db.release(s.state.project.id)
```

Nothing of a page is drawn until its connect has returned, also when the
hook waits on a task. A page whose connect raises is reported with a
toast, and the tab keeps the page it came from, already closed, with
whatever the failed connect wrote to the state.

## Close

The `close` hook runs once per visit, when the session is done with the
page, with the state still as the page left it. That is when the tab
moves to another page, before that page's connect runs, which holds when
the next page is this one with other parameters, and when the session
ends. The session's tasks are canceled before the hook runs.

A session can end while a connect is still running, when the person signs
out or their sign-in runs out. The hook is stopped where it stands then.
A connect that did not return is not followed by a close, so a hook that
takes something it has to give back does that itself in a `finally`.

A close hook has thirty seconds. After that it is stopped and the log
says so, which keeps a hook that never returns from holding up a server
that is stopping.

## One tab, one session

A session belongs to one tab. A link opened in another tab starts a new
session with a fresh state, and so does the same address opened after the
first session has ended. Nothing in `s.state` or `s.files` can be read
from another session, and both end with the session. A restart of the
server ends every session.

What has to be found again later, or from another tab, lives outside the
session, in storage the app brings. There it needs an owner, which is the
user in an app with sign-in, and the browser that [Visitors](/pages/visitors)
describes in an app without.

## When a tab goes away

A session does not end when its tab closes. The server cannot tell a
closed tab from a reload or a dropped network, so the session waits for
the tab to come back, and ends when it has been gone longer than the
grace period. `App(session_grace=300)` sets that in seconds. A tab that
reconnects within it, after a reload, a sleep or a dropped network, gets
its session back with everything in it, and no hook runs.

Everything includes what the page had open. A sheet or a dialog whose
`open` is a field of the state is open again after a reload, because the
state still says so.

The `close` hook of a closed tab therefore runs minutes after the person
left, which suits releasing what the page held and does not suit anything
they are waiting to see.

`s.connected` says whether a tab is on the session right now. It is
`False` from the moment the tab goes away until it comes back or the
session ends. An app that shows other people who is around, the members
of a room, reads it for each session it knows when it draws the list. No
hook runs when it changes, so such a list is as fresh as the last render.

## Ending a session

A session also ends when the app calls `s.end(message)`, when a sign-out
ends it, and when the server stops. A session is over the moment `s.end`
is called, and nothing after that line runs in a handler or a task of that
session. A session that has ended runs nothing more, so a task started on
it afterwards is canceled at once.

At a stop every page closes before the `on_shutdown` hooks run, so a close
hook still has the database those hooks close.

A session that ends while its tab is open tells the tab so. The page stays
readable, takes no more input, and offers a reload, which starts a fresh
session on the same page.
