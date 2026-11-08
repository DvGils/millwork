---
title: Beyond pages
order: 5
description: Routes, mounts and middleware on the Starlette application, and hooks around the process.
related: /sign-in/who-may-open-what, /running/serving
---

# Beyond pages

`App` is a Starlette application, and an app adds to it the Starlette way.
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
unless they are marked `public=True`. The route's endpoint finds the user
in `request.state.user`. [Who may open what](/sign-in/who-may-open-what)
has the rules.

Everything millwork owns lives under `/_mw/`, which leaves every other
path to the app. The `public/` folder next to the app is served at
`/public/`. `/_mw/health` answers 200 once the startup hooks are done.

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
