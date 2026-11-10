---
title: App options
order: 3
description: Every setting on App(...), with its default, and the values this manual runs with.
related: /pages/sessions, /components/files, /running/hosting-checklist
---

# App options

Everything the app needs is said on the `App`, in Python, with values
from wherever the app keeps its secrets. Every option has a default, so
`mw.App("projects")` alone runs. The rest is here for when the default
does not fit.

```python
app = mw.App(
    "projects",
    state=State,                      # the session's state model
    public="public",                  # served at /public/; None for no static folder
    components="components",          # custom components, .jsx files; None for none
    theme="themes/dark.json",         # a path or a Theme; public/theme.json is found on its own
    secret=SECRET,                    # signs cookies; 32 characters or more, required with auth
    auth=...,                         # see Sign-in
    origins=["https://projects.example.com"],
    session_grace=300,                # seconds a session waits for its tab to come back
    max_sessions_per_client=20,       # live sessions per user, or per address without auth
    max_sessions=1000,                # live sessions in the process
    files=mw.Files("/var/lib/projects/files", max_session_mb=200, max_total_mb=2000),
    threads=8,                        # the pool s.thread, uploads and file reads run on
    keep_alive=False,
    proxied=False,                    # True behind a reverse proxy; see Deployment
    identify_visitors=False,          # True gives every browser an id; see Visitors
)
```

- `public`, `components` and a `theme` given by path are found next to
  the file that calls `App(...)`, so `millwork run pond/app.py` works from
  any folder. A helper module that makes apps for others therefore passes
  absolute paths, and code with no file, a notebook cell say, works from
  the working directory. A folder the app names that is not there is said
  in the log at startup.
- `origins` is the allow-list for the socket and the login route. The
  default is the app's own origin.
- `files` is where uploads and generated files live while a session
  lives, with a quota per session and one for the process. The folder is
  private to the process's user, and directories left by old sessions are
  swept. The default is the system's temporary directory, which on some
  hosts is memory, so a deployment names a disk.
- `session_grace` is how long a session waits for its tab to come back
  after the socket drops, with its state intact. [Sessions](/pages/sessions)
  says what happens in that time.
- `max_sessions_per_client` and `max_sessions` count live sessions,
  those in grace included. Over the client's cap, that client's session
  longest without a tab makes room. Over the process cap, anyone's does. A
  new session is refused only when every one still has a tab. A tab that
  comes back to a session that made room starts a new one.
- `threads` sizes the pool that runs sync tasks. The default is Python's.
- `keep_alive=True` makes every open tab fetch the health route every
  thirty seconds, for a host that stops an idle process. By default a tab
  only does so while a task or a reply runs.
- `proxied=True` says a reverse proxy is in front. [Deployment](/running/deployment)
  has the rest.
- `identify_visitors=True` sets a cookie that names the browser, and
  `s.visitor.id` is then the same in every tab of it.
  [Visitors](/pages/visitors) says what the id is good for.

## This manual's settings

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
            {"option": "identify_visitors", "value": app.visitors is not None},
            {"option": "debug", "value": app.debug},
            {"option": "auth", "value": "on" if app.auth else "off"},
        ],
        row_key="option",
        height=400,
    )
```
