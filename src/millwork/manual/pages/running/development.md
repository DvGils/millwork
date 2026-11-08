---
title: Development
order: 0
description: The loop while building, millwork run with its flags, and what the tools see before the page runs.
related: /testing, /state/notices, /running/options
---

# Development

`millwork run app.py` serves the file's `app`, and `millwork run
package.module:app` names the object instead. `--port` picks the port.

`millwork run app.py --reload --debug` is the loop. `--reload` restarts
the process when a Python file changes. The tab shows "Reconnecting" and
remounts when the server is back. `--debug` shows page errors in the tab,
pushes a changed theme file or custom component to every open tab, allows
the `Dev` auth provider, and turns the framework's warnings into toasts: a
slow page function, a list without keys, a handler that changed nothing, a
sync task that changed state from its thread. [What the framework
notices](/state/notices) says what each means.

Tests drive a session without a browser, so for most changes the loop is
edit, run pytest, and open the browser only to look. [Testing](/testing)
shows how. The catalog is typed for mypy and pyright, so a misspelled
prop, a value outside a `Literal` or a missing required prop shows in the
editor before the page runs.

## Reading the app

`millwork routes app.py` prints every page, route and mount of an app
with who may reach it. `millwork reference` prints every component's
props with their types and defaults, the same text this manual serves at
[/llms.txt](/llms.txt). `millwork secret` prints a secret for the session
cookie, and `millwork hash-password --user ada` a line for a credentials
file.
