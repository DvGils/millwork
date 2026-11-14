---
title: Routes and middleware
order: 6
description: Routes, mounts and middleware on the Starlette application, and hooks around the process.
related: /sign-in/access-rules, /running/deployment
---

# Routes and middleware

An `App` holds a Starlette application and adds to it the Starlette way.
The `App` itself is not what a server runs. That is `app.asgi`, the ASGI
application around it.
`app.route(path, endpoint, methods=[...])` adds an API endpoint,
`app.mount(path, asgi_app)` mounts anything ASGI, FastAPI included, and
`app.middleware(cls)` adds pure ASGI middleware.

```python
from starlette.responses import JSONResponse


async def export(request):
    return JSONResponse(await db.export())


app.route("/api/export", export)
app.mount("/api", fastapi_app)
```

In an app with auth a route and a mount need a sign-in like a page does,
unless they are marked `public=True`, and a route takes `allow=` like a
page. [Access rules](/sign-in/access-rules) has the rules. The endpoint
finds the signed-in user in `request.state.user`, and in an app that
[identifies its visitors](/pages/visitors) the browser that asks in
`request.state.visitor`.

Everything millwork owns lives under `/_mw/`, which leaves every other
path to the app. The `public/` folder next to the app is served at
`/public/`, and `/_mw/health` is the health route that
[Deployment](/running/deployment) describes.

## Hooks around the process

`app.on_startup` and `app.on_shutdown` register functions, sync or async,
that run once around the process, to warm a cache or open and close a
pool.

```python
@app.on_startup
async def open_pool() -> None:
    global pool
    pool = await db.connect(DSN)


@app.on_shutdown
async def close_pool() -> None:
    await pool.close()
```

At a stop every session closes before the shutdown hooks run, so a page's
`close` hook still has the pool these hooks close.

`app.spawn(coroutine)` runs work for as long as the app does, a listener
on a database for one. It is called from a startup hook, it is stopped
before the shutdown hooks run, and a failure it lets out is logged.
[Accessing the session](/state/accessing-the-session) uses it for data
that sessions share.
