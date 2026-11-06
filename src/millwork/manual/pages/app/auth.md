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
that page after signing in. The section on the login page below shows how
to lay it out differently.

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

A provider's button shows its `icon`. The two presets carry their brand's
mark, `microsoft` and `google`, and `auth.OAuth(icon=)` takes either of
those, the path of an image under `public/`, or the name of one of
millwork's icons.

## The login page

Left alone, the login page lists every OAuth provider's button, then a
line with "or", then the username and password form. `Auth(login=)` lays
it out your way instead. It takes components like any page does, and
`ui.SignIn(provider_id)` is one way in, put where you want it. It draws an
OAuth provider as its button and `"password"` as the form.

```python
auth.Auth(
    [
        auth.AzureAD(tenant=TENANT, client_id=CLIENT_ID, client_secret=CLIENT_SECRET),
        auth.Password(verify),
    ],
    on_login=admit,
    login=ui.Stack(
        ui.Text("Staff", variant="label"),
        ui.SignIn("azure-ad"),
        ui.Separator(label="or"),
        ui.Text("Partners", variant="label"),
        ui.SignIn("password", label="Sign in as a partner"),
        ui.Markdown("Trouble signing in? Mail [support](mailto:it@example.com)."),
        gap=4,
    ),
)
```

The app's name, the logo and the reason a login was refused stay above
the layout. `label` replaces the words on a button, and
`ui.SignIn("azure-ad", intent="demo")` is the button for one of the
intents described below. Nobody is signed in on this page, so no session
exists and nothing on it can call Python. A component with a handler is
refused when the app starts, and so is one that only works with a session
behind it, a form, a chat, an upload or a download. The id of a provider
the app does not have is refused too. A provider left off the page is not
shown there, and the log says so in case it was a slip. Its sign-in still
answers, since only leaving it out of the list of providers turns it off.

`ui.SignIn` also works on a public page of the app, a landing page with
its own button for one. After signing in, the visitor comes back to that
page.

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
and the hook decides what it means. A login page of your own places it
with `ui.SignIn(provider_id, intent="demo")`.

## Who may open what

Three questions decide what a person can reach, and each has one place.

| Question | Where it is answered |
|---|---|
| Who gets in at all | `on_login` |
| Who may open this page or route | `allow=` |
| Is that still true | `recheck` |

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

`s.can(path)` asks the rule of the page at that path, for a link that
should only be there for the people who can follow it.

```python
ui.Link(label="Review", href="/review") if s.can("/review") else None
```

What a page draws is what its user can do. A handler exists only on the
page of the session that drew it, so a button left out for someone is a
handler they cannot reach.

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

## Keeping the user current

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

When the hook raises or takes longer than ten seconds, nothing is known.
A request that needed the answer fails. A session that is already open
goes on for up to twice the interval since the last answer and then ends
with a note to try again, so a database that is away for a moment costs
nobody their page and one that stays away does not leave the door open.
Signing out works throughout. The answer is kept on each process for
itself, which means several replicas need nothing shared.

Behind an authenticating proxy the person goes through `on_login` and
then through `recheck` on every request. A session that is open hears
nothing from the proxy, so it goes by what `on_login` made of them when
the tab connected, put to `recheck` each interval. When a later request
of the same person shows the proxy now says something else, their open
sessions end at their next step and load again.

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

## Signing out

The user menu's sign-out and `s.logout()` from a handler do the same
thing. The cookie is cleared, the person's other sessions on this process
end with a note in their tabs, and the tab goes to the login page.

`Auth(on_logout=)` sends the tab somewhere else. The hook gets the `User`
who is leaving and returns a path on the app or a full URL, or `None` for
the login page. It may be async.

```python
def leave(user: auth.User) -> str | None:
    return "/welcome" if user.claims.get("demo") else None


auth.Auth([auth.Password(verify)], on_login=admit, on_logout=leave)
```

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
`session`, seven days by default, after which the person signs in again.
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

Identity is what the provider says, the record is what `on_login`
returns, and `claims` is a dictionary the app reads. An access token the
app needs for its own API calls is obtained in `on_login` and kept by the
app.
