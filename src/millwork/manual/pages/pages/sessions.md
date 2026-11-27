---
title: Sessions
order: 4
description: A page's connect and close hooks, and when a session begins, waits and ends.
related: /pages/visitors, /state/state-and-handlers, /components/tasks, /running/app-options
---

# Sessions
<!-- keywords: websocket, connection, lifecycle, reconnect, disconnect -->

A session is one tab. It starts when the tab connects, holds the state,
the files, the identity and the tasks, and it outlives the page, since
the tab moves from page to page on the same session. Two tabs of one visitor are
two sessions with two states, and nothing is shared by being in the same
browser or signed in as the same person.

## Connect
<!-- keywords: on load, on mount, init, load data, fetch when the page opens, useEffect -->

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

A connect hook that calls `s.navigate(path)` sends the session on to
that page. The page it belongs to is not drawn, and the page the session
lands on takes its place in the browser's history, so the back button
does not come back to it. That is how an address leads to another one,
a section to its first part.

```python
@settings.connect
def to_the_first_part(s: mw.Session[State]) -> None:
    s.navigate("/settings/profile")
```

## Close
<!-- keywords: cleanup, on unmount, teardown -->

The `close` hook runs once per visit, when the session is done with the
page, with the state still as the page left it. That is when the tab
moves to another page, before that page's connect runs, which holds when
the next page is this one with other parameters, and when the session
ends. When the session ends, its tasks are canceled before the hook runs.
A move to another page leaves them running, since a task is the
session's. [Tasks](/components/tasks) shows how a page stops one of its
own.

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

## The viewer's time zone
<!-- keywords: timezone, tz, local time, today, date, clock, utc, zoneinfo -->

`s.timezone` is the time zone of the browser the tab runs in, as a
`zoneinfo.ZoneInfo`. The server's clock is the server's, so a time is
kept in UTC and shown in the viewer's zone, and today's date is read
there too. The time has to say that it is UTC, as
`datetime.now(UTC)` does. Python reads one without a zone as the
server's own clock.

```python
from datetime import date, datetime


def clock(s: mw.Session[State], at: datetime) -> str:
    return at.astimezone(s.timezone).strftime("%H:%M")


def today(s: mw.Session[State]) -> date:
    return datetime.now(s.timezone).date()
```

The tab names its zone when it connects, so `s.timezone` is there from
the `connect` hook on. A tab that comes back from another zone, after a
reload or a dropped network, has its page drawn again. Its `connect`
hook does not run again, so what depends on the zone is worked out in
the page function. `s.timezone` is `None` when the browser named no
zone or one the server has no data for, and in a test that gives none.
Both functions above then go by the server's zone. A test gives one
with `TestApp(app).open("/", timezone="Asia/Tokyo")`.

Python reads time zones from the system it runs on. Windows has none to
read, and neither has a container image that leaves them out. millwork
installs the `tzdata` package, which Python reads in their place.

A `ui.Table` column with the `datetime` format is formatted in the
browser, which shows a time that carries its offset in the viewer's
zone without any of this. A time without one is shown as it is written.

## When a tab goes away
<!-- keywords: offline, timeout, grace period, reload -->

A session does not end when its tab closes. The server cannot tell a
closed tab from a reload or a dropped network, so the session waits for
the tab to come back, and ends when it has been gone longer than the
grace period. `App(session_grace=300)` sets that in seconds. A tab that
reconnects within it, after a reload, a sleep or a dropped network, gets
its session back with everything in it, and no hook runs.

Everything includes what the page had open. A sheet or a dialog whose
`open` is a field of the state is open again after a reload, because the
state still says so.

While a session waits for its tab, what a signal or a task changes is
not drawn. It is drawn once, when the tab is back. Until then
`s.outline()` is the page as the tab last had it.

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
