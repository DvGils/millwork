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
    max_sessions_per_client=20,       # live sessions per user, or per address without auth
    max_sessions=1000,                # live sessions in the process
    files=mw.Files("/var/lib/projects/files", max_session_mb=200, max_total_mb=2000),
    threads=8,                        # the pool sync tasks and handlers run in
    keep_alive=False,
)
```

`origins` is the allow-list for the socket and the login route; without
one, same origin only. `files` is where uploads and generated files live
while a session lives, with a quota per session and one for the whole
process; the folder is private to the process's user and swept at start.
The default folder is the system's temporary directory, which on some
hosts is memory, so a deployment names a disk. The session caps count
sessions waiting out the grace period too: over a cap, the client's
session longest without a tab makes room, and only when every one still
has a tab is a new one refused. Without sign-in the client is the
connecting address, so behind a proxy on another machine pass the proxy's
address with `--proxy`, or every visitor counts as one client. A session ended that way, or by signing out in
another tab, tells its tab so: the page stays readable, takes no more
input, and offers a reload.
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
            {"option": "max_sessions_per_client", "value": app.max_sessions_per_client},
            {"option": "max_sessions", "value": app.max_sessions},
            {"option": "files", "value": f"{app.files.max_session_mb} MB per session, {app.files.max_total_mb} MB in all"},
            {"option": "origins", "value": ", ".join(app.origins) or "same origin"},
            {"option": "threads", "value": app.threads or "Python's default"},
            {"option": "keep_alive", "value": app.keep_alive},
            {"option": "debug", "value": app.debug},
            {"option": "auth", "value": "on" if app.auth else "off"},
        ],
        row_key="option",
        height=360,
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

A proxy on the same machine is believed for `X-Forwarded-For` and
`X-Forwarded-Proto` out of the box; one on another host is named with
`--proxy 10.0.0.5`, or `App(proxies=[...])`, with addresses, networks or
`'*'` when only the proxy can reach the process; a typo in the list stops
the app at startup. The app then sees the
visitor's address and scheme rather than the proxy's, and the same list
decides whose identity headers `auth.Headers` reads. millwork does this
itself, so `millwork run` turns uvicorn's own forwarded-headers handling
off. Under uvicorn directly, pass `--no-proxy-headers` yourself: with both
on, uvicorn replaces the connecting address with the forwarded one before
millwork looks, and a visitor who sends `X-Forwarded-For: 127.0.0.1` would
pass for the proxy.

A container image is Python plus the app's dependencies with that line as
its command. The process exits cleanly on SIGTERM: sessions get their
`close` hook, tasks are cancelled, uploads in flight are cut.
`/_mw/health` answers 200 once the startup hooks have run and 503 before
that and during shutdown, for a platform that waits for readiness.

## Under a path prefix

An app can live under a path on a shared host, `https://apps.example/sales/`,
next to other apps. The proxy strips the prefix and the server is told it:

```
uv run millwork run app.py --port 8000 --root-path /sales
```

```nginx
location /sales/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

That is the whole configuration. Every URL the server writes into the page,
the bundle, the theme's fonts, the socket, the login and logout routes, the
favicon, is under the prefix; the cookies' path is the prefix, so apps side
by side on one host never share one; the OAuth callback URL carries it.
Inside the app nothing changes: page paths, `ui.Link` targets, `s.navigate`,
`s.path`, the `next` of a login, an image's `src`, a file's URL and a path
in Markdown are the app's own paths, and the tab puts each one under the
prefix as it renders it. A custom component that builds a URL itself reads
the prefix from `window.__mw.base` (empty at the root). The prefix is taken
from the ASGI `root_path` and nothing else, so a request header such as
`X-Forwarded-Prefix` cannot move an app; `--root-path` is uvicorn's flag,
and any other ASGI server has the same setting. The manual takes the flag
too: `millwork docs --root-path /manual`.

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
