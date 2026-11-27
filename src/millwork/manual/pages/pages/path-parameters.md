---
title: Path parameters
order: 1
description: Paths that carry values, their converters, and which page wins when several fit.
related: /pages/sessions, /sign-in/access-rules
---

# Path parameters
<!-- keywords: url params, dynamic route, slug, id in the url, query string -->

A path can carry parameters in Starlette's syntax. `{name}` takes one
segment as a string. `{name:int}`, `{name:float}` and `{name:uuid}` convert
the segment, and a path that does not convert simply does not match.
`{name:path}` takes the rest of the path. The values arrive in `s.params`,
each as what its converter makes of it, so `{project_id:int}` is a
number there. `s.path` holds the path as it was opened, with its query.

```python
@app.page("/projects/{project_id:int}")
def project(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text(f"Project {s.params['project_id']}"))
```

A page's `connect` hook gets the parameters as keyword arguments, which is
where a page loads what the path names. [Sessions](/pages/sessions) shows
that, and a rule on who may open the page gets them the same way, as
[Access rules](/sign-in/access-rules) describes.

## The query
<!-- keywords: query string, search params, url parameters, filter in the address, shareable link -->

What follows the `?` of an address is the query, and `s.query` holds it.
It suits what a person may want to keep or to send to someone, such as
the view of a list or the words that were searched for. A reload brings
the page back as it was, and so does the link in someone else's browser.

```python
@app.page("/tickets")
def tickets(s: mw.Session) -> ui.Component:
    view = s.query.get("view", "open")
    return ui.Page(
        ui.Row(
            ui.Link(label="Open", href="/tickets?view=open"),
            ui.Link(label="Solved", href="/tickets?view=solved"),
        ),
        ui.Text(f"Showing the {view} tickets"),
    )
```

`s.query.get(name, default)` gives one value, and `s.query.getlist(name)`
gives every value of a name that comes more than once. Each is text. It
is whatever someone typed into the address bar, so a page checks it as it
checks any input. The query takes no part in which page a path names.

A handler changes the query with `s.navigate("/tickets?view=solved")`.
That is a visit like any other. The page's close hook runs and its
connect runs again, and the browser keeps what it holds of the page, as
[Lists and keys](/state/lists-and-keys) describes.

## Which page wins

Where a path fits more than one page, the one that is exact soonest
wins, read from the left. `/orders/new` is its own page next to
`/orders/{order_id}` in whichever order the two are written. A parameter
with a converter comes before a bare one, so `/items/{id:int}` takes the
numbers and `/items/{slug}` the rest, and `{name:path}` comes last at its
place in the path. Two pages that are equally exact go by the order they
were added in.
