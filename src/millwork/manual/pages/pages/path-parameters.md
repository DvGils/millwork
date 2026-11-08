---
title: Parameters in the path
order: 1
description: Paths that carry values, their converters, and which page wins when several fit.
related: /pages/sessions, /sign-in/who-may-open-what
---

# Parameters in the path

A path can carry parameters in Starlette's syntax. `{name}` takes one
segment as a string. `{name:int}`, `{name:float}` and `{name:uuid}` convert
the segment, and a path that does not convert simply does not match.
`{name:path}` takes the rest of the path. The values arrive in `s.params`,
and `s.path` holds the path as it was opened.

```python
@app.page("/projects/{project_id:int}")
def project(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text(f"Project {s.params['project_id']}"))
```

A page's `connect` hook gets the parameters as keyword arguments, which is
where a page loads what the path names. [Sessions](/pages/sessions) shows
that, and a rule on who may open the page gets them the same way, as [Who
may open what](/sign-in/who-may-open-what) describes.

## Which page wins

Where a path fits more than one page, the one that is exact soonest
wins, read from the left. `/orders/new` is its own page next to
`/orders/{order_id}` in whichever order the two are written. A parameter
with a converter comes before a bare one, so `/items/{id:int}` takes the
numbers and `/items/{slug}` the rest, and `{name:path}` comes last at its
place in the path. Two pages that are equally exact go by the order they
were added in.
