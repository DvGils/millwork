---
title: Access rules
order: 4
description: A rule per page or route with allow=, s.can for links, and millwork routes to read it all in one place.
related: /pages/path-parameters, /pages/routes-and-middleware, /pages/error-pages
---

# Access rules

Being signed in gets a person into every page that is not public. A page
for fewer people says so with `allow=`, a rule about the user.

```python
def is_reviewer(user: auth.User) -> bool:
    return user.claims.get("role") == "reviewer"


def on_the_project(user: auth.User, project_id: int) -> bool:
    return project_id in user.claims.get("projects", [])


@app.page("/review", allow=is_reviewer)
def review(s: mw.Session) -> ui.Component: ...


@app.page("/projects/{project_id:int}", allow=on_the_project)
def project(s: mw.Session) -> ui.Component: ...
```

A rule is a plain function. It gets the user, and the parameters of the
page's path that it names, and returns `True` or `False`. It reads
nothing else, which is what lets millwork ask it everywhere a page can be
reached. That is on a page load, when the tab connects, when a session
comes back after a dropped connection, on navigation, and again whenever
the user changes. A person the rule refuses gets the app's forbidden
page, and the page's `connect` hook does not run. Only `True` lets
someone in. A rule that raises, or returns something else, refuses and
says so in the log. Raising `mw.Forbidden("Reviewers only.")` gives the
forbidden page its words.

A rule that is async, or asks for something its path does not have, is
refused when the app starts. What takes a lookup belongs in `connect`,
which can still raise `mw.Forbidden`.

## Links for those who can follow them

`s.can(path)` asks the rule of the page at that path, for a link that
should only be there for the people who can follow it.

```python
ui.Link(label="Review", href="/review") if s.can("/review") else None
```

What a page draws is what its user can do. A handler exists only on the
page of the session that drew it, so a button left out for someone is a
handler they cannot reach.

## Routes and mounts

`app.route` and `app.mount` are behind the sign-in too. A route takes
`allow=` like a page, and its endpoint finds the user in
`request.state.user`. Signed out, it answers 401, or sends a browser that
followed a link to the login page and back. A request that changes
something has to come from the app's own pages. A webhook or a health
check that anyone may call is marked `public=True`.

```python
app.route("/api/export.csv", export, allow=is_reviewer)
app.route("/hooks/mail", mail_hook, methods=["POST"], public=True)
```

`millwork routes app.py` lists every page, route and mount with who may
reach it, so an app's access can be read in one place. The files under
`public/` and the source of the app's custom components are on the list
as open to anyone, which they are.
