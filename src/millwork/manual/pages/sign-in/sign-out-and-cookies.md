---
title: Sign-out and cookies
order: 6
description: Sign-out from the menu or s.logout, where the tab goes, and what the session cookie holds.
related: /sign-in/rechecking-users, /running/hosting-checklist
---

# Sign-out and cookies

The sign-out in the header's user menu and `s.logout()` from a handler do
the same thing. The cookie is cleared, the person's other sessions on this
process end with a note in their tabs, where the page stays readable and
offers a reload as [Sessions](/pages/sessions) describes, and the tab goes
to the login page.

`Auth(on_logout=)` sends the tab somewhere else. The hook gets the `User`
who is leaving and returns a path on the app or a full URL, or `None` for
the login page. It may be async.

```python
def leave(user: auth.User) -> str | None:
    return "/welcome" if user.claims.get("demo") else None


auth.Auth([auth.Password(verify)], on_login=admit, on_logout=leave)
```

## When a sign-in runs out

A sign-in also ends when its time is up, and a tab that is open at that
moment leaves the same way. It goes where the hook says. Without an
answer, a tab on a gated page goes to the login page and comes back to
its page after the person signs in again, and a tab on a public page
reloads where it is, for a visitor. The hook is asked once for all the
tabs that sign-in has on a process.

The hook hears that one sign-in ended, which says little about the
person. They may still be signed in from another browser, and a sign-in
that runs out with no session left on it ends without the hook. What the
app keeps for a person is better dropped on an expiry of its own than
here.

A hook that raises, or takes longer than ten seconds, is logged, and the
person leaves for the login page. Behind an authenticating proxy that has
a `sign_out` URL the tab goes there, and the hook's answer is not used.

## The session cookie

The cookie is a signed token holding the `User`. It is `HttpOnly`,
`SameSite=Lax`, `Secure` over HTTPS, and it lives for a fixed time set by
`Auth(session=)`, seven days by default, after which the person signs in again.
A tab still open at that time ends its session and leaves the page.
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
