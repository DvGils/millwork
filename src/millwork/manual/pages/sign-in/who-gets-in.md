---
title: Who gets in
order: 3
description: on_login turns an identity into a User or refuses it, and intents give the login page a second button.
related: /sign-in/who-may-open-what, /sign-in/keeping-current
---

# Who gets in

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

## The User

A `User` is `id`, `name`, `claims` and `picture_url`. `claims` is the
app's own dictionary, capped at 2 KB, for things like roles, the projects
a person may see, or flags. A picture is a URL. Without `on_login`, every
identified visitor becomes a `User` with the e-mail as `id`, and a provider
that gives no e-mail is refused.

Identity is what the provider says, the record is what `on_login`
returns, and `claims` is a dictionary the app reads. An access token the
app needs for its own API calls is obtained in `on_login` and kept by the
app.

## Intents

`Auth(intents={"demo": "Try the demo"})` adds a secondary button to the
login page for each intent. The one pressed arrives as `identity.intent`,
and the hook decides what it means. A login page of your own places it
with `ui.SignIn(provider_id, intent="demo")`.
