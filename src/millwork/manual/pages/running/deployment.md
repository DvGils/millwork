---
title: Deployment
order: 1
description: One process behind a reverse proxy, on a port or a unix socket, at the root or under a path prefix.
related: /running/hosting-checklist, /sign-in/providers
---

# Deployment

In production one process serves one app behind a reverse proxy that
ends TLS and passes the websocket upgrade through.

```
uv run millwork run app.py --host 127.0.0.1 --port 8000 --proxied
```

`--proxied`, or `App(proxied=True)`, says a reverse proxy is in front.
The app then takes the visitor's address and scheme from the proxy's
`X-Forwarded-For` and `X-Forwarded-Proto`, and the visitor's identity from
the headers an `auth.Headers` provider names. Anyone who can reach the
process can send those headers too, so a proxied app listens where only
its proxy connects, whether that is a unix socket, a loopback port or a
container network.

`/_mw/health` answers 200 once the startup hooks have run, and 503 before
that and during shutdown, for a host that waits for readiness. The
process exits cleanly on SIGTERM. Sessions get their `close` hook, tasks
are canceled, and uploads in flight are cut. Logs go to standard error.

`app.asgi` is the ASGI application itself, for a server of your own
choosing. Under uvicorn directly, pass `--no-proxy-headers`, since
millwork applies the forwarded headers, and `--ws-max-size 1048576`, the
bound `millwork run` puts on a message from the tab. Uploads travel in
smaller frames, so the bound costs nothing.

## A new version

A restart ends every session. The tabs that were open connect again on
their own and draw the page anew. Such a tab still runs the bundle it
loaded, which the new version may have replaced, and so does a tab that
a browser restored with a page from its cache. A tab says which bundle
it runs when it connects, and one that is not the bundle the server has
loads the page again, so it never draws a page with components it does
not know.

It loads the page once. If the page that comes back still names another
bundle, something between the browser and the app keeps handing out an
old page, a cache in front of the app for one. The tab then stops and
says the page is out of date, with a button to try again.

## A unix socket

On one machine with the proxy, `--uds` listens on a unix socket. The
socket is created with mode 0660 whatever the umask, so the proxy
connects when it runs in the app's group. A socket is only ever reached
through a proxy, so `--uds` implies `--proxied`.

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
way, with `curl --unix-socket /run/sales/app.sock http://app/_mw/health`.

## Under a path prefix

An app can live under a path on a shared host, say
`https://apps.example/sales/`, next to other apps. The proxy strips the
prefix and the server is told about it.

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
have their own. Inside the app everything is an app path, whether a page
path, a `ui.Link` target, `s.navigate`, an image's `src` or a path in
Markdown. The tab puts each one under the prefix as it renders it. A
custom component that builds a URL itself reads the prefix from
`window.__mw.base`, which is empty at the root. The manual takes the flag
too, as `millwork docs --root-path /manual`.
