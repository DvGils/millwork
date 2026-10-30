---
title: Hosting
order: 6
---

# Hosting

The Running chapter has each piece: the process, the proxy, the socket,
the prefix, the health route. This chapter puts them together in the two
shapes a millwork app is usually hosted in: several apps on one machine,
and one app in a container on a platform. Both are complete; neither is
the only way.

Whatever the shape, the same things have to be true. TLS ends at a proxy
or the platform's edge, and the proxy passes the websocket upgrade
through. The app's `secret` and its provider credentials come from the
environment or the platform's secret store, never from the image or the
repository. Uploads and generated files live on a disk the process may
write, named with `Files(...)`, or in the temporary directory when losing
them with the process is fine. The process logs to standard output and
is restarted when it dies. `/_mw/health` is what the host watches.

## Several apps on one machine

One machine runs each app as its own process under systemd, on a unix
socket, and nginx in front serves them under paths of one hostname with
TLS. A single sign-in for all of them comes from an authenticating proxy
next to nginx, or each app brings its own, as the Signing in chapter
shows.

Each app is a directory with its own environment, and one system user
runs them all. uv lives where every user finds it, `/usr/local/bin`, and
the environments are made as that user, so the interpreter uv may
download belongs to it too:

```
/srv/apps/sales/        app.py, pyproject.toml, uv.lock, .venv/, public/
/srv/apps/reports/
/etc/millwork/sales.env     APP_SECRET=... and provider credentials; root-owned, mode 600
/run/millwork/sales.sock    created by the process, owner apps, group apps, mode 660
/var/lib/millwork/sales/    uploads and generated files
```

```
useradd --system --home /srv/apps --shell /usr/sbin/nologin apps
mkdir -p /srv/apps /etc/millwork && chown apps /srv/apps
usermod -aG apps www-data        # or http, nginx: whatever user nginx runs as
systemctl restart nginx          # its workers pick up the group when they start
```

When the group is wrong, nginx answers 502 and its error log says
`(13: Permission denied) while connecting to upstream`; the app sees
nothing, since the connection never reaches it.

One template unit serves every app; the instance name is the directory,
the socket and the path prefix at once:

```ini
# /etc/systemd/system/millwork@.service
[Unit]
Description=millwork app %i
After=network.target

[Service]
User=apps
Group=apps
WorkingDirectory=/srv/apps/%i
EnvironmentFile=/etc/millwork/%i.env
RuntimeDirectory=millwork
RuntimeDirectoryPreserve=yes
StateDirectory=millwork/%i
ExecStart=/srv/apps/%i/.venv/bin/millwork run app.py --uds /run/millwork/%i.sock --root-path /%i
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
ProtectSystem=strict
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

`RuntimeDirectory` makes `/run/millwork` for the sockets and
`RuntimeDirectoryPreserve` keeps it when one app stops while others run,
which would otherwise take their sockets away;
`StateDirectory` makes `/var/lib/millwork/sales` the one place the
process may write under `ProtectSystem=strict`, so the app names it. The
env file is `KEY=value` lines, one of them the output of `millwork
secret`:

```python
import os

app = mw.App(
    "sales",
    secret=os.environ["APP_SECRET"],
    files=mw.Files("/var/lib/millwork/sales", max_session_mb=200, max_total_mb=2000),
    auth=auth.Auth([auth.Headers(user="X-User", email="X-Email", sign_out="/oauth2/sign_out")]),
)
```

nginx gets one file per app, included from the server block. The block
strips the prefix, passes the upgrade, the host and the visitor's
address, and asks the authenticating proxy who the visitor is before
every request; the three `oauth2` locations in the server block are the
standard oauth2-proxy wiring for nginx's `auth_request`:

```nginx
# /etc/nginx/sites-available/apps.example
server {
    listen 443 ssl;
    server_name apps.example;
    # ssl_certificate and ssl_certificate_key as certbot wrote them

    location /oauth2/ {
        proxy_pass       http://127.0.0.1:4180;
        proxy_set_header Host                    $host;
        proxy_set_header X-Real-IP               $remote_addr;
        proxy_set_header X-Auth-Request-Redirect $request_uri;
    }
    location = /oauth2/auth {
        proxy_pass       http://127.0.0.1:4180;
        proxy_set_header Host             $host;
        proxy_set_header X-Real-IP        $remote_addr;
        proxy_set_header X-Forwarded-Uri  $request_uri;
        proxy_set_header Content-Length   "";
        proxy_pass_request_body           off;
    }
    location @oauth2_signin {
        return 302 /oauth2/sign_in?rd=$scheme://$host$request_uri;
    }

    include /etc/nginx/millwork/*.conf;
}
```

```nginx
# /etc/nginx/millwork/sales.conf
location /sales/ {
    auth_request /oauth2/auth;
    error_page 401 = @oauth2_signin;
    auth_request_set $user  $upstream_http_x_auth_request_user;
    auth_request_set $email $upstream_http_x_auth_request_email;
    proxy_set_header X-User  $user;
    proxy_set_header X-Email $email;

    proxy_pass http://unix:/run/millwork/sales.sock:/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 1h;
}
```

`proxy_set_header X-User $user` replaces anything the browser sent under
that name, which is what `auth.Headers` relies on. The app believes the
headers because the connection comes over its socket, which only the
`apps` group can open; nothing else on the machine can reach it.
`X-Forwarded-For` is what the app counts visitors by before they sign
in; without it every anonymous visitor shares one session cap. The
`proxy_read_timeout` keeps nginx from closing a quiet websocket after
its default minute. Without an authenticating proxy, the three `oauth2`
locations and the six auth lines go, and the app signs people in itself.

oauth2-proxy itself is one more unit, with its settings in a root-owned
config file rather than on its command line, where `ps` would show the
secrets. The minimum, for any OpenID Connect provider:

```toml
# /etc/oauth2-proxy.cfg
provider = "oidc"
oidc_issuer_url = "https://login.example/"
client_id = "..."
client_secret = "..."
cookie_secret = "..."                 # 32 random bytes, base64
cookie_secure = true
redirect_url = "https://apps.example/oauth2/callback"
email_domains = ["example.com"]
whitelist_domains = ["apps.example", "login.example"]
http_address = "127.0.0.1:4180"
reverse_proxy = true
trusted_proxy_ips = ["127.0.0.1/32"]
set_xauthrequest = true
upstreams = ["static://202"]
```

`whitelist_domains` names where oauth2-proxy may send people after a
sign-in or a sign-out: the apps' host, and the provider's host when the
sign-out should end the provider's session too (`/oauth2/sign_out?rd=`
the provider's own sign-out URL). `upstreams` is a placeholder, since
nginx does the routing. Its own `--config-test` says whether the file
is complete.

Adding an app is the directory, the env file, the unit and the nginx
file:

```
sudo -u apps uv sync --frozen --no-dev --compile-bytecode --project /srv/apps/sales
systemctl enable --now millwork@sales
nginx -t && nginx -s reload
journalctl -u millwork@sales -f
```

`--compile-bytecode` because the unit's read-only file system keeps
Python from writing its caches later. A start that fails, with something
else at the socket path for instance, is retried every two seconds and
the journal says why. An update is `uv sync` again and
`systemctl restart millwork@sales`; sessions on that app end, their tabs
say so, and nothing else is touched. The manual itself can sit there too:
`millwork docs --uds /run/millwork/manual.sock --root-path /manual` in a
unit of its own, behind the same six auth lines or open, as you prefer.

## One app in a container

A platform that runs containers, routes HTTPS to them and holds secrets
needs one image and a few settings. The image is Python, the app and its
dependencies, built with uv in two steps so the dependency layer is
cached:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
RUN useradd --system app && chown -R app /app
USER app
EXPOSE 8000
CMD ["/app/.venv/bin/millwork", "run", "app.py", "--host", "0.0.0.0", "--port", "8000", "--proxied"]
```

A `.dockerignore` with `.venv` in it keeps a local environment from
being copied over the one the image builds, and `uv.lock` has to be in
the repository for `--frozen`. `--proxied` because the platform's router
is in front. The port must be reachable by that router alone: on a
cluster without a network policy or a shared private network, another
workload could send the same headers.
The app reads its secret and credentials from the environment, as above,
and names no files directory unless the platform mounts a volume: the
default is the container's temporary directory, which is lost with the
container, as sessions are.

On the platform, the settings that matter:

- **Port** 8000, **HTTPS** at the edge, and **websockets** passed through,
  which most platforms do by default and some switch on per app.
- **Readiness** on `/_mw/health`: 200 once the startup hooks have run,
  503 before that and during shutdown, so traffic waits for a replica
  that is ready. As a liveness probe it would restart a slow start, so
  give that one a generous threshold or leave it out.
- **Files** on a mounted volume when uploads are large: a named disk
  buys size and the quota, not persistence, since a session's files go
  with the session. A folder the process cannot write shows at the first
  upload, not at start.
- **One replica** is the simple case. More than one works without sticky
  routing, as the Running chapter explains, as long as every replica has
  the same `secret`.
- **Scale to zero** stops the container after a quiet spell, and
  platforms differ on what counts as quiet: some count an open websocket
  as activity, some only the messages on it, some only HTTP requests.
  `App(keep_alive=True)` makes every open tab ping the health route, which
  counts everywhere, so the app stays up while someone is looking at it
  and stops once nobody is; the cost is that an open tab on a desk keeps
  a replica running.
- **Sign-in** from the platform's own authentication, which puts the
  visitor in request headers the Signing in chapter lists, or the app's
  own OAuth provider with `https://<host>/_mw/auth/oauth/<id>/callback`
  registered at the identity provider.
- **Several apps** are several containers, each on its own hostname from
  the platform, or under paths of one hostname with `--root-path` added
  to the command and the platform's router stripping the prefix.

## Before it goes live

- The page is served over HTTPS and `/_mw/ws` connects; a websocket that
  is blocked shows as "Reconnecting" in the tab and nothing else.
- `secret` is 32 characters or more, the same on every replica, and not
  in the repository.
- The process runs with `--proxied` and listens where only the proxy
  connects.
- `Files(...)` points at a disk with room, and one upload has been
  tried, since a missing or unwritable folder shows then.
- `origins` is set when the hostname in the browser differs from the
  one the proxy passes as `Host`, or the websocket is refused.
- The clock is synchronised, since sign-in tokens carry expiry times.
- Certificate renewal reloads nginx, which certbot's own nginx plugin
  does and a webroot setup does with a deploy hook.
- The manual, if it is hosted, is behind the same sign-in or meant to be
  public.
- `/_mw/health` is the probe, and `keep_alive` is set when the host
  scales to zero.
- Signing out works: the user menu lands on the proxy's sign-out page or
  millwork's login page. A proxy's sign-out clears its own cookie and not
  the identity provider's session, so the next visit may sign the same
  person in again without asking; oauth2-proxy takes an `rd=` to the
  provider's own sign-out URL for that.
