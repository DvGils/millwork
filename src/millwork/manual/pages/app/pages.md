---
title: Pages and routing
order: 0
---

# Pages and routing

An app is a `mw.App` with pages on it. A page is a path and a function of
the session that returns the component tree for that path. The browser
opens the path, the tab connects a socket, and from then on Python renders
and handles events over that socket. There is one session per tab.

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

`title` is the browser tab's title; without one the app's name is used.
Paths match in the order the pages are registered, and a path no page
matches is a 404.

`millwork run app.py` serves the file's `app`; `millwork run package.module:app`
names the object. `--port` picks the port, `--reload` restarts the process
when a Python file changes, `--debug` shows page errors in the tab and
watches the theme file and the custom components for changes. Under
uvicorn or another ASGI server, `app.asgi` is the application.

## Parameters in the path

A path can carry parameters in Starlette's syntax. `{name}` takes one
segment as a string; `{name:int}`, `{name:float}` and `{name:uuid}` convert
it, and a path that does not convert does not match. `{name:path}` takes
the rest of the path. The values arrive in `s.params`, and `s.path` is the
path as opened.

```python
@app.page("/projects/{project_id:int}")
def project(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text(f"Project {s.params['project_id']}"))
```

## Moving between pages

A `ui.Link` whose `href` is a path inside the app navigates over the
session: no reload, the tab's history gets an entry, the back button
works. From a handler, `s.navigate(path)` does the same. A `#heading` on
the path scrolls to that heading once the page is up, which is how this
manual's search opens a section.

```python live
def example(s):
    return ui.Row(
        ui.Button("Open the Charts chapter", on_click=lambda s, _: s.navigate("/components/charts")),
        ui.Link(label="or follow a link", href="/components/charts#stat"),
        ui.Text(f"You are at {s.path}", variant="muted"),
        gap=4,
    )
```

A link to another site is an ordinary link; give it `target="_blank"` to
open a new tab.

## When a page is missing

A path no page matches lands on the app's not-found page: over HTTP as a
404 that serves the shell, and over the session when a link or
`s.navigate` asks for it, so the tab keeps its session and can go on from
there. `connect` reaches the same pages by raising: `mw.NotFound(message)`
when what the path names does not exist, `mw.Forbidden(message)` when this
person may not open it. The session lands on the error page under the path
that was asked for, with the message if one was given.

Without any app code the framework's own pages are shown: the theme's
logo, a title and a line from the string table, and a way home, in the
same frame as the login page. An app replaces them with pages of its own,
written like any other page: `s.params["path"]` is the path asked for and
`s.params["message"]` what `connect` raised with, or empty.

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
have, which is the framework's own not-found page in this manual's theme.

```python live
ui.Row(
    ui.Logo(cls="h-6"),
    ui.Link(label="Open a page that does not exist", href="/components/nothing-here"),
    gap=4,
)
```

A failure before the bundle can run, a crash in an app's own route or the
bundle missing, is a plain HTML page with the same title and text, in the
theme's colours and font; the traceback goes to the log. In debug mode a
crash shows Starlette's own traceback page.

## State and the session

A page's state is a Pydantic model named on the page, or on the app as the
default for every page. `s.state` is an instance of it, made new when the
page is opened and again on every navigation to a page. The session itself
outlives the page: its files, its identity and its tasks stay while the tab
moves around the app.

```python
class State(BaseModel):
    selected: list[int] = []


@app.page("/projects/{project_id:int}", state=State)
def project(s: mw.Session[State]) -> ui.Component:
    ...
```

Everything a page shows comes from `s.state` and from what its handlers put
there, so a page is a plain function and handlers are where things
change.

## Connect and close

A page can have a `connect` hook, run once each time the page is opened,
before the first render, with the path parameters as keyword arguments. It
may be async, and it is where a page loads what it needs, starts a task,
or decides that the visitor may not be here. `mw.NotFound()` and
`mw.Forbidden(message)` raised from it keep the tab on the page it came
from and show the message; a page opened directly shows the message and
stops there.

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

The `close` hook runs once, with the state still intact, when the session
ends: the tab said goodbye, or it has been gone longer than the grace
period. `App(session_grace=300)` sets that period in seconds; a tab that
reconnects within it, after a sleep or a dropped network, gets its session
back with everything in it.

## Navigation in the frame

`ui.Header(links=[...])` puts links in the app bar and `ui.Sidebar` holds
a longer list. This manual's sidebar is a `Sidebar` of `Link`s with the
current page drawn as text instead; the Layout chapter shows both.

## Beyond pages

`App` is a Starlette application, and an app adds to it through Starlette:
`app.route(path, endpoint, methods=[...])` for an API endpoint,
`app.mount(path, asgi_app)` for anything ASGI, FastAPI included,
`app.middleware(cls)` for pure ASGI middleware, and `app.on_startup` and
`app.on_shutdown` for hooks around the process. The `public/` folder next
to the app is served at `/public/`. Everything millwork owns lives under
`/_mw/`, leaving every other path to the app; `/_mw/health` answers 200
once the startup hooks are done.
