---
title: Signing in
order: 2
---

# Signing in

Without auth every page is open to anyone who reaches the server. With
auth every page asks for a login first, a page is opened to anonymous
visitors with `public=True`, and `s.user` says who is there. Identity comes
from a provider; who gets in, and what the app keeps on them, is one
function of the app's own.

## Turning it on

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

`secret` signs the session cookie and must be at least 32 characters;
`millwork secret` prints one. Values such as the secret and the provider's
credentials come from wherever the app keeps its secrets; millwork reads
no environment variables of its own.

The login page is part of millwork: the app's name, the theme's
`login_image`, one button per OAuth provider, a username and password form
when there is a password provider, and the message when a login was
refused. A visitor who opens a gated page lands there and comes back to
that page after signing in.

## Providers

`auth.AzureAD(tenant=, client_id=, client_secret=)` is Microsoft Entra ID,
single tenant unless `single_tenant=False`. `auth.Google(client_id=,
client_secret=)` is Google. Both are presets over `auth.OAuth(id, label=,
authorize_url=, token_url=, userinfo_url=, client_id=, client_secret=,
scopes=)`, which fits any OpenID Connect issuer. The provider's callback
URL is `/_mw/auth/oauth/<id>/callback` on the app's origin.

`auth.Password(verify)` takes a callable `(username, password) -> bool`,
sync or async, and millwork runs it off the event loop. Hashes are
scrypt from the standard library: `millwork hash-password --user ada`
prints a line for a credentials file, and `auth.check_password(password,
stored)` checks one against it.

```python
USERS = {"ada": "scrypt$..."}


def verify(username: str, password: str) -> bool:
    stored = USERS.get(username)
    return stored is not None and auth.check_password(password, stored)
```

`auth.Header(name, trusted_proxies=[...])` trusts an identity header set by
a reverse proxy in front of the app, such as a platform's built-in login,
and refuses the header from any other peer. `auth.Dev(user)` signs every
visitor in as that user and is refused outside `--debug`, so it cannot
ship.

Several providers can be listed together; the login page offers each.

## Deciding who gets in

After a provider has identified the visitor, `on_login(identity)` decides.
`identity` carries `provider`, `subject`, `email` (lower-cased), `name`,
`picture_url`, the provider's `raw` document and an `intent`. The hook
returns a `User` to let the visitor in, or `None` to refuse with a message
on the login page and a line in the log. It may be async and may look the
person up somewhere.

```python
async def admit(identity: auth.Identity) -> auth.User | None:
    if not identity.email or not identity.email.endswith("@example.com"):
        return None
    projects = await db.projects_of(identity.email)
    if not projects:
        return None
    return auth.User(
        id=identity.email,
        name=identity.name or identity.email,
        claims={"projects": [p.id for p in projects], "admin": identity.email in ADMINS},
        picture_url=identity.picture_url,
    )
```

A `User` is `id`, `name`, `claims` and `picture_url`. `claims` is the
app's own dictionary, capped at 2 KB: roles, the projects a person may
see, flags. A picture is a URL, never bytes. Without `on_login` every
identified visitor becomes a `User` with the e-mail as `id`, and a provider
that gives no e-mail is refused.

`Auth(intents={"demo": "Try the demo"})` adds a secondary button to the
login page for each intent; the one pressed arrives as `identity.intent`,
and the hook decides what it means.

## In a page

`s.user` is the `User`, or `None` on a public page when nobody is signed
in. Authorisation is the app's: read `s.user.claims` in `connect` and raise
`mw.Forbidden(message)` when this page or this project is not for this
person. The Pages chapter shows the hook.

```python live
def example(s):
    who = f"{s.user.name} ({s.user.id})" if s.user else "nobody; the manual runs without auth"
    return ui.Text(f"Signed in as {who}.", variant="muted")
```

The `ui.Header` shows the signed-in person's picture or initials with a
menu that holds the theme choice and sign-out; `user_menu=False` hides it.
`s.logout()` signs out from a handler: the cookie is cleared and the tab
goes to the login page.

## The session cookie

The cookie is a signed token holding the `User`, `HttpOnly`, `SameSite=Lax`,
`Secure` over HTTPS, with a fixed lifetime set by `session` (seven days by
default). There is no sliding renewal: after that long a person signs in
again. It is stateless, so any replica of the app validates it with the
shared secret, and nothing about a person leaves the server beyond the
`User` itself. The socket is bound to the cookie: a session cannot be
resumed by someone else. Logins and refusals are logged with the
identifier; `log_identity="hashed"` logs a hash instead.

## What is not here

No user database, no registration, no password reset: identity comes from
the provider and the record is what `on_login` returns. No roles model:
`claims` is a dictionary and the app reads it. No token refresh and no
calls to the provider after login: an app that needs an access token for
its own API calls obtains and keeps it in `on_login`, outside the cookie.
