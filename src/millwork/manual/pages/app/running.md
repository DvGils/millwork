---
title: Running and deploying
order: 5
---

# Running and deploying

One process serves an app: Python, the built bundle inside the package,
and nothing else. There is no Node on the machine, no build step, no
configuration file. What an app needs is said on the `App`, in Python,
with values from wherever the app keeps its secrets.

## The App's options

```python
app = mw.App(
    "projects",
    state=State,                      # the default state model for every page
    public="public",                  # served at /public/; None for no static folder
    components="components",          # custom components, .jsx files; None for none
    theme="themes/dark.json",         # a path or a Theme; public/theme.json is found on its own
    secret=SECRET,                    # signs cookies; 32 characters or more, required with auth
    auth=...,                         # see Signing in
    origins=["https://projects.example.com"],
    session_grace=300,                # seconds a session waits for its tab to come back
    files=mw.Files("/var/lib/projects/files", max_session_mb=2000, default_max_mb=50),
    threads=8,                        # the pool sync tasks and handlers run in
    keep_alive=False,
)
```

`origins` is the allow-list for the socket and the login route; without
one, same origin only. `files` is where uploads and generated files live
while a session lives, with a limit per session and the default limit per
upload; the folder is private to the process's user and swept at start.
`threads` sizes the pool that runs sync tasks; the default is Python's.
`keep_alive=True` makes every tab ping the server while open, for a host
that scales to zero and would otherwise stop the process under a page that
is merely being read; without it a tab pings only while a task or a reply
is running.

The settings this manual runs with:

```python live
def example(s):
    app = s.app
    return ui.Table(
        rows=[
            {"option": "name", "value": app.name},
            {"option": "session_grace", "value": f"{app.session_grace:.0f} s"},
            {"option": "origins", "value": ", ".join(app.origins) or "same origin"},
            {"option": "threads", "value": app.threads or "Python's default"},
            {"option": "keep_alive", "value": app.keep_alive},
            {"option": "debug", "value": app.debug},
            {"option": "auth", "value": "on" if app.auth else "off"},
        ],
        row_key="option",
        height=260,
    )
```

## Development

`millwork run app.py --reload --debug` is the loop. `--reload` restarts
the process when a Python file changes; session state goes with it, and
the tab shows "Reconnecting" and remounts when the server is back.
`--debug` shows page errors in the tab, turns the framework's warnings
into toasts, watches the theme file and the custom components and pushes a
change to every open tab, and allows the `Dev` auth provider. Tests drive
a session without a browser, so for most changes the loop is edit, run
pytest, and the browser is for looking.

## Serving

`app.asgi` is a Starlette application; `millwork run` wraps uvicorn
around it with `--host` and `--port`. In production that is one process
per app behind a reverse proxy that passes the websocket upgrade through:

```
uv run millwork run app.py --host 127.0.0.1 --port 8000
```

A container image is Python plus the app's dependencies with that line as
its command. The process exits cleanly on SIGTERM: sessions get their
`close` hook, tasks are cancelled, uploads in flight are cut.
`/_mw/health` answers 200 once the startup hooks have run and 503 before
that and during shutdown, for a platform that waits for readiness.

## More than one replica

HTTP is stateless and the socket is the session: identity comes from the
cookie, and everything a session owns, its state, its files, its tasks,
travels over the socket to the process that holds it. Replicas therefore
need no sticky routing and no shared storage. When a replica goes away,
its sessions go with it, and their tabs start fresh sessions elsewhere,
as they would on a reload. The cookie is validated by any replica that
has the same `secret`.

## The page's security headers

Every page carries a Content Security Policy: scripts only from the app's
origin with a nonce, connections only to the app's origin, images and
media from anywhere over HTTPS, no framing by other sites. An app with a
`components/` folder also allows `eval`, since custom components are
compiled in the tab. A custom component that needs a library loads it from
`public/`, as the Charts chapter shows. `App(csp=None)` drops the header, and a string of your own
replaces it; `{scripts}` in it is where millwork puts the script sources.

## Hooks around the process

`app.on_startup` and `app.on_shutdown` register functions, sync or async,
that run once around the process: warm a cache, open and close a pool.
`app.route`, `app.mount` and `app.middleware` add to the Starlette
application, as the Pages chapter shows.
