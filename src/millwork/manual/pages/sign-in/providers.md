---
title: Providers
order: 1
description: Microsoft Entra ID, Google and any OpenID Connect issuer, passwords, a dev provider, and a proxy that signs in for the app.
related: /sign-in/login-page, /running/deployment
---

# Providers

A provider establishes who the visitor is: an OAuth issuer such as
Microsoft Entra ID or Google, a username and password the app checks, a
stand-in while developing, or a proxy that signed the person in before
the request reached the app. Several can be listed together, and the
login page offers each of them. Whoever a provider identifies then goes
through the app's `on_login` hook, which [Admitting users](/sign-in/admitting-users)
describes.

## OAuth

`auth.AzureAD(tenant=, client_id=, client_secret=)` is Microsoft Entra ID,
single tenant unless you pass `single_tenant=False`. `auth.Google(client_id=,
client_secret=)` is Google. Both are presets over `auth.OAuth(id, label=,
authorize_url=, token_url=, userinfo_url=, client_id=, client_secret=,
scopes=)`, which fits any OpenID Connect issuer. The provider's callback
URL is `/_mw/auth/oauth/<id>/callback` on the app's origin.

A provider's button shows its `icon`. The two presets carry their brand's
mark, `microsoft` and `google`, and `auth.OAuth(icon=)` takes either of
those, the path of an image under `public/`, or the name of one of
millwork's icons.

## Passwords

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

## While developing

`auth.Dev(user)` signs every visitor in as that user. It is allowed with
`--debug` and refused otherwise.

## Behind an authenticating proxy

Sometimes a proxy in front of the app does the signing in, whether that is
oauth2-proxy, a platform's built-in authentication or an access gateway.
It names who it saw in request headers, and `auth.Headers` reads them.
Give it the header names the proxy uses. `user` or `email` is required,
while `name`, `groups` and `picture` are optional, and `groups` is split
on commas into `identity.raw["groups"]`. The person goes through
`on_login` on every page load and socket connect, since the proxy signs
them in anew each time, so keep that hook cheap.
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
`App(proxied=True)`, as [Deployment](/running/deployment) describes. A request
that arrives without an identity lands on the login page, which explains
that sign-in happens before the app. The proxy's or platform's
documentation lists the header names it sets and its sign-out URL.
