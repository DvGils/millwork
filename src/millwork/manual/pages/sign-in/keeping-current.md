---
title: Keeping the user current
order: 5
description: recheck asks who a person is now, and ends a session drawn for who they were.
related: /sign-in/who-gets-in, /sign-in/signing-out, /pages/sessions
---

# Keeping the user current

A cookie holds the `User` as `on_login` made it, and holds it until it
expires. A person whose role changed, or who should no longer get in,
keeps what the cookie says. `Auth(recheck=)` closes that gap. The hook
gets the user the cookie holds and returns who that person is now, or
`None` when they are no longer welcome.

```python
async def current(user: auth.User) -> auth.User | None:
    record = await db.person(user.id)
    if record is None or not record.active:
        return None
    return user.model_copy(update={"claims": {"role": record.role}})


auth.Auth(providers, on_login=admit, recheck=current)
```

It is asked wherever a visitor is identified, and by every open session,
at most once per `recheck_every` for each sign-in. That is five minutes
unless you set it, so a change in your data reaches a person within that
time whether they are clicking or not.

## When the answer differs

A session belongs to the user it started with. Its page was drawn for
them, and what it holds was gathered for them. So when the hook returns a
user who differs in any way, the session ends and the tab loads its page
again, as the person they are now. A page whose rule no longer admits
them shows the forbidden page, and a page that still does is drawn
without what only their old role was given. Return the same user for the
same facts, since a field that changes on every call, such as a time,
would reload every tab each interval, and the log says so when it sees
that happen. `None` ends the sign-in, and the login page says access was
denied.

## When there is no answer

When the hook raises or takes longer than ten seconds, nothing is known.
A request that needed the answer fails. A session that is already open
goes on for up to twice the interval since the last answer and then ends
with a note to try again, so a database that is away for a moment costs
nobody their page and one that stays away does not leave the door open.
Signing out works throughout. The answer is kept on each process for
itself, which means several replicas need nothing shared.

## Behind a proxy

Behind an authenticating proxy the person goes through `on_login` and
then through `recheck` on every request. A session that is open hears
nothing from the proxy, so it goes by what `on_login` made of them when
the tab connected, put to `recheck` each interval. When a later request
of the same person shows the proxy now says something else, their open
sessions end at their next step and load again.
