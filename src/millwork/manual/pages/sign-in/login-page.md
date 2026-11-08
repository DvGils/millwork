---
title: The login page
order: 2
description: Laying out the login page with ui.SignIn, and a sign-in button on a public page.
related: /sign-in/providers, /theming
---

# The login page

millwork has a login page of its own. A visitor who opens a gated page
lands on it and comes back to that page after signing in. Left alone, it
lists every OAuth provider's button, then a line with "or", then the
username and password form. `Auth(login=)` lays
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
intents that [Who gets in](/sign-in/who-gets-in) describes.

## What the page cannot hold

Nobody is signed in on this page, so no session exists and nothing on it
can call Python. A component with a handler is refused when the app
starts, and so is one that only works with a session behind it, a form, a
chat, an upload or a download. The id of a provider the app does not have
is refused too. A provider left off the page is not shown there, and the
log says so in case it was a slip. Its sign-in still answers, since only
leaving it out of the list of providers turns it off.

## On a public page

`ui.SignIn` also works on a public page of the app, a landing page with
its own button for one. After signing in, the visitor comes back to that
page.

The page's look comes from the theme: its logo, its `login_image` and its
colors, as [Theming](/theming) describes.
