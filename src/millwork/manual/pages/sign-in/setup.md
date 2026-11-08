---
title: Setting up auth
order: 0
description: Auth on the App, public pages, s.user and the sign-in a visitor meets.
related: /sign-in/providers, /sign-in/admitting-users, /running/app-options
---

# Setting up auth

Without auth, every page is open to anyone who reaches the server. With
auth, every page asks for a login first, except a page marked
`public=True`, and `s.user` says who is there. A provider establishes who
the visitor is. Who gets in, and what the app keeps about them, is one
function of the app's own.

```python
import datetime as dt

import millwork as mw
from millwork import auth, ui

app = mw.App(
    "projects",
    secret=SECRET,
    auth=auth.Auth(
        [auth.AzureAD(tenant=TENANT, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)],
        on_login=admit,
        session=dt.timedelta(hours=8),
    ),
)


@app.page("/")
def home(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Text(f"Hello, {s.user.name}."))


@app.page("/privacy", public=True)
def privacy(s: mw.Session) -> ui.Component:
    return ui.Page(ui.Markdown(PRIVACY))
```

`secret` signs the session cookie and must be at least 32 characters.
`millwork secret` prints a good one. The secret and the provider's
credentials come from wherever the app keeps its secrets. `admit` is the
app's `on_login` hook. It turns who the provider saw into a `User`, or
refuses them, and [Admitting users](/sign-in/admitting-users) writes it. `session`
is how long a sign-in lasts, seven days unless set.

The login page is part of millwork. It shows the app's name, the theme's
`login_image`, one button per OAuth provider, a username and password form
when there is a password provider, and the reason when a login was
refused. A visitor who opens a gated page lands there and comes back to
that page after signing in. [The login page](/sign-in/login-page) shows
how to lay it out differently.

## In a page

`s.user` is the `User`, or `None` on a public page when nobody is signed
in.

```python live
def example(s):
    who = f"{s.user.name} ({s.user.id})" if s.user else "nobody; the manual runs without auth"
    return ui.Text(f"Signed in as {who}.", variant="muted")
```

The `ui.Header` shows the signed-in person's picture or initials with a
menu that holds the theme choice and sign-out. `user_menu=False` hides it.

## The pieces

| Question | Where it is answered |
|---|---|
| Who is this | a provider, on [Providers](/sign-in/providers) |
| Who gets in at all | `on_login`, on [Admitting users](/sign-in/admitting-users) |
| Who may open this page or route | `allow=`, on [Access rules](/sign-in/access-rules) |
| Is that still true | `recheck`, on [Rechecking users](/sign-in/rechecking-users) |
