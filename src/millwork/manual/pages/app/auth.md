---
title: Signing in
order: 2
---

# Signing in

Without auth, every page is open to anyone who reaches the server. With
auth, every page asks for a login first, except a page marked
`public=True`, and `s.user` says who is there. A provider establishes who
the visitor is. Who gets in, and what the app keeps about them, is one
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

`secret` signs the session cookie and must be at least 32 characters.
`millwork secret` prints a good one. The secret and the provider's
credentials come from wherever the app keeps its secrets.

The login page is part of millwork. It shows the app's name, the theme's
`login_image`, one button per OAuth provider, a username and password form
when there is a password provider, and the reason when a login was
refused. A visitor who opens a gated page lands there and comes back to
that page after signing in.

## Providers

`auth.AzureAD(tenant=, client_id=, client_secret=)` is Microsoft Entra ID,
single tenant unless you pass `single_tenant=False`. `auth.Google(client_id=,
client_secret=)` is Google. Both are presets over `auth.OAuth(id, label=,
authorize_url=, token_url=, userinfo_url=, client_id=, client_secret=,
scopes=)`, which fits any OpenID Connect issuer. The provider's callback
URL is `/_mw/auth/oauth/<id>/callback` on the app's origin.

`auth.Password(verify)` takes a callable `(username, password) -> bool`,
sync or async, and millwork runs it off the event loop. Hashes are scrypt
from the standard library. `millwork hash-password --user ada` prints a
line for a credentials file, and `auth.check_password(password, stored)`
checks a password against one.

```python
USERS = {"ada": "scrypt$..."}


def verify(username: str, password: str) -> bool:
    stored = USERS.get(username)
    return stored is not None and auth.check_password(password, stored)
```

`auth.Dev(user)` signs every visitor in as that user. It is allowed with
`--debug` and refused otherwise.

Several providers can be listed together, and the login page offers each
of them.

## Behind an authenticating proxy

Sometimes a proxy in front of the app does the signing in, whether that is
oauth2-proxy, a platform's built-in authentication or an access gateway.
It names who it saw in request headers, and `auth.Headers` reads them.
Give it the header names the proxy uses. `user` or `email` is required,
while `name`, `groups` and `picture` are optional, and `groups` is split
on commas into `identity.raw["groups"]`. The person goes through
`on_login` on every page load and socket connect, so keep that hook cheap.
A sync hook runs off the event loop. One that raises shows the error page,
and the tab stops retrying. A visitor the hook refuses sees the login page
say so.

`sign_out` is the proxy's own sign-out URL, which the user menu and
`s.logout()` go to. Without one the menu offers no sign-out, and
`s.logout()` only ends the person's sessions on this process, after which
the proxy signs them in again on the next page. The proxy replaces these
headers on the way through, and a header that arrives twice is ignored.

```python
# oauth2-proxy in front of the app, with its default headers
auth.Headers(
    user="X-Forwarded-User",
    email="X-Forwarded-Email",
    name="X-Forwarded-Preferred-Username",
    groups="X-Forwarded-Groups",
    sign_out="/oauth2/sign_out",
)
```

The headers are read when the app runs with `--proxied` or
`App(proxied=True)`, as the Running chapter describes. A request that
arrives without an identity lands on the login page, which explains that
sign-in happens before the app. The proxy's or platform's documentation
lists the header names it sets and its sign-out URL.

## Deciding who gets in

After a provider has identified the visitor, `on_login(identity)` decides.
`identity` carries `provider`, `subject`, `email` in lower case, `name`,
`picture_url`, the provider's `raw` document and an `intent`. The hook
returns a `User` to let the visitor in, or `None` to refuse them with a
message on the login page and a line in the log. It may be async, and it
may look the person up somewhere.

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
app's own dictionary, capped at 2 KB, for things like roles, the projects
a person may see, or flags. A picture is a URL. Without `on_login`, every
identified visitor becomes a `User` with the e-mail as `id`, and a provider
that gives no e-mail is refused.

`Auth(intents={"demo": "Try the demo"})` adds a secondary button to the
login page for each intent. The one pressed arrives as `identity.intent`,
and the hook decides what it means.

## In a page

`s.user` is the `User`, or `None` on a public page when nobody is signed
in. Authorisation is the app's job. Read `s.user.claims` in `connect` and
raise `mw.Forbidden(message)` when this page or this project is not for
this person. The Pages chapter shows the hook.

```python live
def example(s):
    who = f"{s.user.name} ({s.user.id})" if s.user else "nobody; the manual runs without auth"
    return ui.Text(f"Signed in as {who}.", variant="muted")
```

The `ui.Header` shows the signed-in person's picture or initials with a
menu that holds the theme choice and sign-out. `user_menu=False` hides it.
`s.logout()` signs out from a handler. The cookie is cleared, the person's
other sessions on this process end with a note in their tabs, and the tab
goes to the login page.

## The session cookie

The cookie is a signed token holding the `User`. It is `HttpOnly`,
`SameSite=Lax`, `Secure` over HTTPS, and it lives for a fixed time set by
`session`, seven days by default, after which the person signs in again.
Its name and path carry the app's prefix, `mw_auth_sales` under `/sales`,
so apps side by side on one host each read their own. It is also signed
for the app by name, so apps that share a secret still keep their
sign-ins apart. The cookie is valid on any replica with the same secret.

Signing out clears the browser's cookie and ends the person's sessions on
that process. A copy of the cookie stays valid until it expires, so the
lifetime is the real bound, and an app with sensitive data sets `session`
to a working day. The socket is bound to the cookie, which means a session
is only ever resumed by its own user. Logins and refusals are logged with
the identifier, or with a hash of it when `log_identity="hashed"`.

Identity is what the provider says, the record is what `on_login`
returns, and `claims` is a dictionary the app reads. An access token the
app needs for its own API calls is obtained in `on_login` and kept by the
app.
