---
title: Pages and routing
order: 0
---

# Pages and routing

An app is a `mw.App` with pages on it. A page is a path and a function of
the session that returns the component tree for that path. When the
browser opens the path, the tab connects a socket, and from then on Python
renders the page and handles its events over that socket. Each tab is one
session.

## An app and its pages

```python
import millwork as mw
from millwork import ui

app = mw.App("projects")


@app.page("/", title="Projects")
def home(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text("All projects"), title="Projects")


@app.page("/about")
def about(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text("About this app"))
```

`title` sets the browser tab's title, and the app's name is used when a
page has none. Paths match in the order the pages were registered. A path
no page matches is a 404.

`millwork run app.py` serves the file's `app`, and `millwork run
package.module:app` names the object instead. `--port` picks the port.
`--reload` restarts the process when a Python file changes, and `--debug`
shows page errors in the tab and watches the theme file and the custom
components for changes. Under uvicorn or another ASGI server, `app.asgi`
is the application.

## Parameters in the path

A path can carry parameters in Starlette's syntax. `{name}` takes one
segment as a string. `{name:int}`, `{name:float}` and `{name:uuid}` convert
the segment, and a path that does not convert simply does not match.
`{name:path}` takes the rest of the path. The values arrive in `s.params`,
and `s.path` holds the path as it was opened.

Where a path fits more than one page, the one that is exact soonest
wins, read from the left. `/orders/new` is its own page next to
`/orders/{order_id}` in whichever order the two are written. A parameter
with a converter comes before a bare one, so `/items/{id:int}` takes the
numbers and `/items/{slug}` the rest, and `{name:path}` comes last at its
place in the path. Two pages that are equally exact go by the order they
were added in.

```python
@app.page("/projects/{project_id:int}")
def project(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text(f"Project {s.params['project_id']}"))
```

## Moving between pages

A `ui.Link` whose `href` is a path inside the app navigates over the
session. Nothing reloads, the tab's history gets an entry, and the back
button works. From a handler, `s.navigate(path)` does the same. A
`#heading` on the path scrolls to that heading once the page is up, which
is how this manual's search opens a section. Without one, the page opens
at the top, and the back button returns to where the reader was.

```python live
def example(s):
    return ui.Row(
        ui.Button("Open the Charts chapter", on_click=lambda s, _: s.navigate("/components/charts")),
        ui.Link(label="or follow a link", href="/components/charts#stat"),
        ui.Text(f"You are at {s.path}", variant="muted"),
        gap=4,
        wrap=True,
    )
```

A link to another site is an ordinary link. Give it `target="_blank"` to
open a new tab.

## When a page is missing

A path no page matches lands on the app's not-found page. Over HTTP that
is a 404 that still serves the shell. Over the session, when a link or
`s.navigate` asks for it, the tab keeps its session and can go on from
there. A `connect` hook reaches the same pages by raising. `mw.NotFound(message)`
says that what the path names does not exist, and `mw.Forbidden(message)`
that this person may not open it. The HTTP response for such a path is
still a 200, since the shell is served before the session connects and
the hook runs, so a crawler sees the status and a reader sees the page.
The session lands on the error page
under the path that was asked for, with the message if one was given.

Without any app code the framework's own pages are shown, in the same
frame as the login page, with the theme's logo, a title, a line from the
string table and a way home. An app replaces them with pages of its own,
written like any other page. `s.params["path"]` is the path that was asked
for, and `s.params["message"]` is what `connect` raised with, or empty.

```python
@app.not_found
def missing(s):
    return ui.Page(
        ui.Stack(
            ui.Logo(cls="h-9 self-start"),
            ui.Text("Nothing here", variant="title"),
            ui.Text(s.params["message"] or f"There is no page at {s.params['path']}.", variant="muted"),
            ui.Input(kind="search", placeholder="Search instead", on_submit=search),
            gap=3,
            cls="max-w-sm",
        ),
    )


@app.forbidden(title="Private")
def private(s):
    return ui.Page(ui.Text(s.params["message"] or "Ask the owner for access."))
```

`ui.Logo` is the theme's logo, light or dark with the scheme, for a page
outside the app bar. The link below goes to a page this manual does not
have, so it shows the framework's own not-found page in this manual's
theme.

```python live
ui.Row(
    ui.Logo(cls="h-6"),
    ui.Link(label="Open a page that does not exist", href="/components/nothing-here"),
    gap=4,
)
```

A failure before the bundle can run, say a crash in an app's own route or
a missing bundle, produces a plain HTML page with the same title and text
in the theme's colors and font. The traceback goes to the log. In debug
mode a crash shows Starlette's own traceback page instead.

## State and the session

The app declares one state model, and `s.state` is the session's instance
of it. It is made when the session starts and kept while the tab moves
around the app, so a value one page set is there for the next. The
session's files, its identity and its tasks stay in the same way. The
State chapter shows how a bigger app splits the model into one slice per
feature.

```python
class State(BaseModel):
    project: Project | None = None
    selected: list[int] = []


app = mw.App("projects", state=State)


@app.page("/projects/{project_id:int}")
def project(s: mw.Session[State]) -> ui.Component:
    ...
```

Everything a page shows comes from `s.state` and from what its handlers
put there. That keeps a page a plain function, and handlers the place
where things change.

## Connect and close

A page can have a `connect` hook. It runs once each time the page is
opened, before the first render, with the path parameters as keyword
arguments, and it may be async. This is where a page loads what it needs,
starts a task, or decides that the visitor may not be here. Raising
`mw.NotFound()` or `mw.Forbidden(message)` from it lands the session on
the app's page for that, under the path that was asked for, with the
message.

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

The `close` hook runs once per visit, when the session is done with the
page, with the state still as the page left it. That is when the tab
moves to another page, before that page's connect runs, which holds when
the next page is this one with other parameters, and when the session
ends. A page whose connect raises is reported with a toast, and the tab
keeps the page it came from, already closed, with whatever the failed
connect wrote to the state.

Nothing of a page is drawn until its connect has returned, also when the
hook waits on a task. A session can end while a connect is still running,
when the person signs out or their sign-in runs out. The hook is stopped
where it stands then. A connect that did not return is not followed by a
close, so a hook that takes something it has to give back does that itself
in a `finally`.

A session does not end when its tab closes. The server cannot tell a
closed tab from a reload or a dropped network, so the session waits for
the tab to come back, and ends when it has been gone longer than the
grace period. `App(session_grace=300)` sets that in seconds. A tab that
reconnects within it, after a reload, a sleep or a dropped network, gets
its session back with everything in it, and no hook runs. The `close`
hook of a closed tab therefore runs minutes after the person left, which
suits releasing what the page held and does not suit anything they are
waiting to see. A session also ends when the app calls `s.end(message)`,
when a sign-out ends it, and when the server stops. At a stop every page
closes before the `on_shutdown` hooks run, so a close hook still has the
database those hooks close. The session's tasks are canceled before the
hook runs. A session is over the moment `s.end` is called, and nothing
after that line runs in a handler or a task of that session. A session
that has ended runs nothing more, so a task started on it afterwards is
canceled at once. A close hook has thirty seconds. After that it is
stopped and the log says so, which keeps a hook that never returns from
holding up a server that is stopping.

## Navigation in the frame

`ui.Header(links=[...])` puts links in the app bar, and `ui.Sidebar` holds
a longer list. A `ui.Link` in a sidebar is drawn as a row to press, with
its `icon` in front and the one marked `active=True` set apart, so the
list needs no classes of its own. This manual's sidebar is a `Sidebar` of
such links. The Layout chapter shows both.

## Beyond pages

`App` is a Starlette application, and an app adds to it the Starlette way.
`app.route(path, endpoint, methods=[...])` adds an API endpoint,
`app.mount(path, asgi_app)` mounts anything ASGI, FastAPI included, and
`app.middleware(cls)` adds pure ASGI middleware. `app.on_startup` and
`app.on_shutdown` register hooks around the process. In an app with auth
a route and a mount need a sign-in like a page does, unless they are
marked `public=True`, as the Signing in chapter describes. The `public/` folder
next to the app is served at `/public/`. Everything millwork owns lives
under `/_mw/`, which leaves every other path to the app. `/_mw/health`
answers 200 once the startup hooks are done.
