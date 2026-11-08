---
title: Pages and routes
order: 0
description: An App, its pages, and how a path finds the page that draws it.
related: /quickstart, /state/state-and-handlers, /running/development
---

# Pages and routes

An app is a `mw.App` with pages on it. A page is a path and a function of
the session that returns the component tree for that path. When the
browser opens the path, the tab connects a socket, and from then on Python
renders the page and handles its events over that socket. Each tab is one
session.

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
no page matches is a 404, and [Error pages](/pages/error-pages) says
what is shown then.

## The page function

A page function builds the tree and nothing else. It reads `s.state`,
which is the session's one state model, and what a handler put there is
what the next render shows. It runs on every render, so it stays quick,
and anything that waits, a query or a file, happens in the page's
`connect` hook or in a task. [State and
handlers](/state/state-and-handlers) covers the state, and
[Sessions](/pages/sessions) the hooks.

`ui.Page` is the root of every page. It lays itself out around a
`ui.Sidebar` child when there is one and puts a `header` in the app bar,
as the [Layout](/components/layout) page shows.

## Serving the file

`millwork run app.py` serves the file's `app`. [Development](/running/development)
has the command's flags for building, and [Deployment](/running/deployment)
those for production.
