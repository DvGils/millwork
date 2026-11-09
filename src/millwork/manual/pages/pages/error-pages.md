---
title: Error pages
order: 3
description: What a visitor sees for a path no page matches, a page they may not open or a page that fails, and how an app replaces the first two.
related: /pages/sessions, /sign-in/access-rules, /theming
---

# Error pages

A path no page matches lands on the app's not-found page. Over HTTP that
is a 404 that still serves the shell. Over the session, when a link or
`s.navigate` asks for it, the tab keeps its session and can go on from
there.

A page's `connect` hook, the function that runs before a page is first
drawn, reaches the same pages by raising. `mw.NotFound(message)` says that
what the path names does not exist, and `mw.Forbidden(message)` that this
person may not open it. The session lands on the error page under the
path that was asked for, with the message if one was given. The HTTP
response for such a path is still a 200, since the shell is served before
the session connects and the hook runs, so a crawler sees the status and a
reader sees the page. [Sessions](/pages/sessions) describes the hook
itself.

## The app's own pages

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

## A page that fails

A page function that raises has nothing to show. When the tab already
shows the page, it keeps what it had and a toast says the page failed to
render. When there is nothing yet, on the first page of a session or
after a navigation, the framework's failure page takes the page's place.
It has the same frame as the pages above, a button that draws the page
again, and a way home from any other page. A reload draws the page again
as well. Once the page function works, its page replaces the failure
page, whether that button, a reload or a change in the state drew it.
While it still fails, the button answers with the toast.

The exception goes to the log. In debug mode it is on the failure page as
well.

## Before the bundle runs

A failure before the bundle can run, say a crash in an app's own route or
a missing bundle, produces a plain HTML page with the same title and text
in the theme's colors and font. The traceback goes to the log. In debug
mode a crash shows Starlette's own traceback page instead.
