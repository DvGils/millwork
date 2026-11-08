---
title: Hosting checklist
order: 2
description: The checklist for any host, systemd and container examples, replicas, and the page's security headers.
related: /running/deployment, /running/app-options, /components/custom
---

# Hosting checklist

Any host that runs one process and routes HTTPS to it can serve a
millwork app. It provides:

- TLS at the proxy or the platform's edge, with the websocket upgrade
  passed through.
- `--proxied`, and a listener only the proxy can reach, whether a unix
  socket, a loopback port or the container's network.
- `/_mw/health` as the readiness probe. As a liveness probe it would
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

HTTP is stateless and the socket is the session. Identity comes from the
cookie, and everything a session owns, its state, its files and its tasks,
travels over the socket to the process that holds it. Replicas need no
sticky routing and no shared storage. When a replica goes away, its
sessions go with it, and their tabs start fresh sessions elsewhere, as
they would on a reload. The cookie is valid on every replica that has the
same `secret`.

## The page's security headers

Every page carries a Content Security Policy. Scripts come from the app's
origin with a nonce, connections go to the app's origin, images and media
may come from anywhere over HTTPS, and no other site may frame the page.
An app with a `components/` folder also allows `eval`, since custom
components are compiled in the tab. A custom component that needs a
library loads it from `public/`, as the [Custom](/components/custom) page
shows. `App(csp=None)` drops the header, and a string of your own
replaces it, with `{scripts}` marking where millwork puts the script
sources.
