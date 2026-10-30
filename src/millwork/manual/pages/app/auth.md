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

`auth.Dev(user)` signs every visitor in as that user and is refused
outside `--debug`, so it cannot ship.

Several providers can be listed together; the login page offers each.

## Behind an authenticating proxy

When a proxy in front of the app does the signing in (oauth2-proxy, a
platform's built-in authentication, an access gateway), it names who it saw
in request headers, and `auth.Headers` reads them. Give it the header names
the proxy uses: `user` or `email` is required, `name`, `groups` and
`picture` are optional, and `groups` is split on commas into
`identity.raw["groups"]`. The person goes through `on_login` on every page
load and socket connect, so keep that hook cheap; a sync hook runs off
the event loop, so a slow one delays its own visitor and nobody else, and
one that raises shows the error page and ends the tab's attempts rather
than looping. A visitor the hook refuses sees the login page say so. `sign_out` is the proxy's
own sign-out URL, which the user menu and `s.logout()` go to; without one
the menu offers no sign-out, since the app holds nothing to clear, and
`s.logout()` only ends the person's sessions, after which the proxy signs
them in again on the next page. The proxy must replace these headers, not
add to what the browser sent; a header that arrives twice is ignored.

```python
# oauth2-proxy in front of the app (its default --pass-user-headers)
auth.Headers(
    user="X-Forwarded-User",
    email="X-Forwarded-Email",
    name="X-Forwarded-Preferred-Username",
    groups="X-Forwarded-Groups",
    sign_out="/oauth2/sign_out",
)

# Azure App Service or Container Apps built-in authentication
auth.Headers(
    user="X-MS-CLIENT-PRINCIPAL-ID",
    email="X-MS-CLIENT-PRINCIPAL-NAME",
    sign_out="/.auth/logout",
)

# Cloudflare Access
auth.Headers(email="Cf-Access-Authenticated-User-Email", sign_out="/cdn-cgi/access/logout")

# Authelia and other proxies that speak the Remote-* convention
auth.Headers(user="Remote-User", email="Remote-Email", name="Remote-Name", groups="Remote-Groups")
```

The headers are read when the app runs with `--proxied` or
`App(proxied=True)`, as the Running chapter describes; without the switch
they are ignored, with one line in the log. Whoever can reach the process
can send these headers, so a proxied app listens where only its proxy
connects. A request that arrives without an identity lands on the login
page, which says that sign-in happens before the app.

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
`s.logout()` signs out from a handler: the cookie is cleared, the person's
other sessions on this process end with a note in their tabs, and the tab
goes to the login page.

## The session cookie

The cookie is a signed token holding the `User`, `HttpOnly`, `SameSite=Lax`,
`Secure` over HTTPS, with a fixed lifetime set by `session` (seven days by
default). It is bound to the path it was set for, the app's prefix, so
apps side by side on one host never accept each other's cookie, even with
one secret between them. There is no sliding renewal: after that long a person signs in
again. It is stateless, so any replica of the app validates it with the
shared secret, and nothing about a person leaves the server beyond the
`User` itself. Stateless also means signing out cannot revoke a copy of
the cookie: a copy stays valid until it expires, so the lifetime is the
bound, and an app with sensitive data sets `session` to a working day.
Chainlit's cookie works the same way; Shiny leaves sign-in to the host. The socket is bound to the cookie: a session cannot be
resumed by someone else. Logins and refusals are logged with the
identifier; `log_identity="hashed"` logs a hash instead.

## What is not here

No user database, no registration, no password reset: identity comes from
the provider and the record is what `on_login` returns. No roles model:
`claims` is a dictionary and the app reads it. No token refresh and no
calls to the provider after login: an app that needs an access token for
its own API calls obtains and keeps it in `on_login`, outside the cookie.
