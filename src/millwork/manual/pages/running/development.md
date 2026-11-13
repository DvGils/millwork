---
title: Development
order: 0
description: The loop while building, millwork run with its flags, and what the tools see before the page runs.
related: /testing, /state/warnings, /running/app-options
---

# Development

`millwork run app.py` serves the file's `app`, and `millwork run
package.module:app` names the object instead. `--port` picks the port.

`millwork run app.py --reload --debug` is the loop. `--reload` restarts
the process when a Python file changes. The tab shows "Reconnecting" and
remounts when the server is back. `--debug` shows page errors in the tab,
pushes a changed theme file or custom component to every open tab, allows
the `Dev` auth provider, and turns the framework's warnings into toasts, a
slow page function, a list without keys, a handler that changed nothing, a
sync task that changed state from its thread. [Framework
warnings](/state/warnings) says what each means.

Tests drive a session without a browser, so for most changes the loop is
edit, run pytest, and open the browser only to look. [Testing](/testing)
shows how. The catalog is typed for mypy and pyright, so a misspelled
prop, a value outside a `Literal` or a missing required prop shows in the
editor before the page runs.

## Deprecations

millwork retires a spelling in two steps. For at least one minor release
the old spelling still works and warns, and a later release drops it. The
warning says which release that is and what to write now.

`millwork run` logs each one, once for every line of the app that causes
it.

```text
WARNING millwork.deprecation: /srv/shop/shop.py:14: Shelf(deep=) is deprecated since millwork 1.1 and stops working in 1.2. Use depth= instead.
```

It is also a Python warning, a `MillworkDeprecationWarning`, which is what
tools read. pytest lists them at the end of a run. With this in the
project's `pyproject.toml` a test that reaches an old spelling fails, and
an upgrade that passes the tests is ready for the release after it.

```toml
[tool.pytest.ini_options]
filterwarnings = ["error::millwork.MillworkDeprecationWarning"]
```

An app that is served without `millwork run` gets no log line, and Python
hides a deprecation in code that is not the main script. Starting Python
with `-W default::DeprecationWarning` shows them.

An old keyword of a component still type-checks for as long as it works.
While it does, the type checker takes either name for that keyword and
does not notice a required one that is missing.
Before 1.0 a release may still move something without the warning step,
and the [changelog](https://github.com/DvGils/millwork/blob/main/CHANGELOG.md)
says so when it does.

## Reading the app

`millwork routes app.py` prints every page, route and mount of an app
with who may reach it. `millwork reference` prints every component's
props with their types and defaults, the same text this manual serves at
[/llms.txt](/llms.txt). `millwork secret` prints a secret for the session
cookie, and `millwork hash-password --user ada` a line for a credentials
file.
