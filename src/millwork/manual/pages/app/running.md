---
title: Running
order: 5
---

# Running

One process serves an app: Python with the built bundle inside the
package. What the app needs is said on the `App`, in Python, with values
from wherever the app keeps its secrets. `millwork run` starts the
process, and a handful of flags cover a reverse proxy, a unix socket and
a path prefix.

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
    proxied=False,                    # True behind a reverse proxy; see Serving
)
```

- `origins` is the allow-list for the socket and the login route; the
  default is the app's own origin.
- `files` is where uploads and generated files live while a session
  lives, with a quota per session and one for the process. The folder is
  private to the process's user, and directories left by old sessions are
  swept. The default is the system's temporary directory, which on some
  hosts is memory, so a deployment names a disk.
- `session_grace` is how long a session waits for its tab to come back
  after the socket drops, with its state intact.
- `max_sessions_per_client` and `max_sessions` count live sessions,
  those in grace included. Over the client's cap, that client's session
  longest without a tab makes room; over the process cap, anyone's. A
  new session is refused when every one still has a tab. A session ended
  that way, or by a sign-out in another tab, tells its tab so: the page
  stays readable, takes no more input, and offers a reload.
- `threads` sizes the pool that runs sync tasks; the default is Python's.
- `keep_alive=True` makes every open tab fetch the health route every
  thirty seconds, for a host that stops an idle process; by default a tab
  does so while a task or a reply runs.
- `proxied=True` says a reverse proxy is in front; the Serving section
  below.

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
            {"option": "proxied", "value": app.proxied},
            {"option": "debug", "value": app.debug},
            {"option": "auth", "value": "on" if app.auth else "off"},
        ],
        row_key="option",
        height=400,
    )
```

## Development

`millwork run app.py --reload --debug` is the loop. `--reload` restarts
the process when a Python file changes; the tab shows "Reconnecting" and
remounts when the server is back. `--debug` shows page errors in the
tab, turns the framework's warnings into toasts, pushes a changed theme
file or custom component to every open tab, and allows the `Dev` auth
provider. Tests drive a session without a browser, so for most changes
the loop is edit, run pytest, and the browser is for looking.

## Serving

In production one process serves one app behind a reverse proxy that
ends TLS and passes the websocket upgrade through:

```
uv run millwork run app.py --host 127.0.0.1 --port 8000 --proxied
```

`--proxied`, or `App(proxied=True)`, says a reverse proxy is in front.
The app then takes the visitor's address and scheme from the proxy's
`X-Forwarded-For` and `X-Forwarded-Proto`, and the visitor's identity from
the headers an `auth.Headers` provider names. Anyone who can reach the
process can send those headers too, so a proxied app listens where only
its proxy connects: a unix socket, a loopback port, or a container
network.

`/_mw/health` answers 200 once the startup hooks have run and 503 before
that and during shutdown, for a host that waits for readiness. The
process exits cleanly on SIGTERM: sessions get their `close` hook, tasks
are cancelled, uploads in flight are cut. Logs go to standard error.

`app.asgi` is the ASGI application itself, for a server of your own
choosing; under uvicorn directly, pass `--no-proxy-headers`, since
millwork applies the forwarded headers, and `--ws-max-size 1048576`, the
bound `millwork run` puts on a message from the tab (uploads travel in
smaller frames).

## A unix socket

On one machine with the proxy, `--uds` listens on a unix socket. The
socket is created with mode 0660, whatever the umask, so the proxy
connects when it runs in the app's group. A socket is reached through a
proxy, so `--uds` implies `--proxied`.

```
uv run millwork run app.py --uds /run/sales/app.sock
```

```nginx
location / {
    proxy_pass http://unix:/run/sales/app.sock:/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Like a port, the path is refused while another process answers on it. A
socket file nobody answers on is replaced at the next start, and anything
else at the path stops the start. The health route is reached the same
way: `curl --unix-socket /run/sales/app.sock http://app/_mw/health`.

## Under a path prefix

An app can live under a path on a shared host, `https://apps.example/sales/`,
next to other apps. The proxy strips the prefix and the server is told it:

```
uv run millwork run app.py --port 8000 --root-path /sales --proxied
```

```nginx
location /sales/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Every URL the server writes into the page is under the prefix, and the
cookies carry it in name and path, so apps side by side on one host each
have their own. Inside the app everything is an app path: page paths,
`ui.Link` targets, `s.navigate`, an image's `src`, a path in Markdown;
the tab puts each one under the prefix as it renders it. A custom
component that builds a URL itself reads the prefix from
`window.__mw.base`, which is empty at the root. The manual takes the flag
too: `millwork docs --root-path /manual`.

## What a host needs

Any host that runs one process and routes HTTPS to it serves a millwork
app. It provides:

- TLS at the proxy or the platform's edge, with the websocket upgrade
  passed through.
- `--proxied`, and a listener only the proxy can reach: a unix socket, a
  loopback port, or the container's network.
- `/_mw/health` as the readiness probe: 200 once the startup hooks have
  run, 503 before that and during shutdown. As a liveness probe it would
  restart a slow start, so that one gets a generous threshold.
- A files directory with room, named with `Files(...)`, when uploads are
  larger than the temporary directory should hold.
- The `secret` and the provider's credentials from the environment or the
  platform's secret store.
- `keep_alive=True` when the host stops an idle container, since
  platforms differ on whether an open websocket counts as activity and
  the health pings count everywhere.
- A path prefix per app, or a hostname per app, when several share a
  host.

The millwork parts of a service definition are the command line. Under
systemd, with the socket in the unit's runtime directory and the files in
its state directory:

```ini
RuntimeDirectory=millwork
StateDirectory=millwork/sales
ExecStart=/srv/apps/sales/.venv/bin/millwork run app.py --uds /run/millwork/sales.sock --root-path /sales
```

In a container, behind the platform's router:

```dockerfile
CMD ["/app/.venv/bin/millwork", "run", "app.py", "--host", "0.0.0.0", "--port", "8000", "--proxied"]
```

## More than one replica

HTTP is stateless and the socket is the session: identity comes from the
cookie, and everything a session owns, its state, its files, its tasks,
travels over the socket to the process that holds it. Replicas need no
sticky routing and no shared storage. When a replica goes away, its
sessions go with it, and their tabs start fresh sessions elsewhere, as
they would on a reload. The cookie is valid on every replica that has the
same `secret`.

## The page's security headers

Every page carries a Content Security Policy: scripts from the app's
origin with a nonce, connections to the app's origin, images and media
from anywhere over HTTPS, and no framing by other sites. An app with a
`components/` folder also allows `eval`, since custom components are
compiled in the tab. A custom component that needs a library loads it
from `public/`, as the Charts chapter shows. `App(csp=None)` drops the
header, and a string of your own replaces it; `{scripts}` in it is where
millwork puts the script sources.

## Hooks around the process

`app.on_startup` and `app.on_shutdown` register functions, sync or async,
that run once around the process: warm a cache, open and close a pool.
`app.route`, `app.mount` and `app.middleware` add to the Starlette
application, as the Pages chapter shows.
