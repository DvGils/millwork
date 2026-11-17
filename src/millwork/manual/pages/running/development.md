---
title: Development
order: 0
description: The loop while building, millwork run with its flags, and what the tools see before the page runs.
related: /testing, /state/warnings, /running/app-options
---

# Development
<!-- keywords: hot reload, dev server, debug, cli, run, watch -->

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
[/llms.txt](/llms.txt).

With words behind it, the command looks one thing up. It prints the
entry of the reference and the sections of this manual that are about
it, examples included, up to a few thousand characters. A part that does
not fit is cut, and what else matched is named, each with the command
that gives it whole.

`millwork reference ui.Table` asks by name and
`millwork reference shared data` by what it is about. A thing is found
by what it is called elsewhere as well, so `modal` finds the dialog,
`notification` the toast and `st.button` the button. A word that is
mistyped is read as the one it is close to. When no part is called by
the word a question turns on, the answer says that nothing is named so,
above the parts that have the words.
`millwork reference components/feedback#toast` gives one section and
`millwork reference components/feedback.md` a page. `--chars` sets how
much is printed and `--index` lists every name without what is said of
it. An agent that writes an app reads a part this way, where the whole
reference and the whole manual are a lot to take in at once.

`millwork secret` prints a secret for the session
cookie, and `millwork hash-password --user ada` a line for a credentials
file.

## A picture of a page
<!-- keywords: screenshot, headless, browser, png, visual, look -->

`millwork shot app.py /orders` saves `shot.png`, a picture of the page as
a browser shows it. The command serves the app on a free port, opens the
page in a Chrome, Chromium, Edge or Brave that is already on the machine,
and waits until the page has stopped changing. Nothing is installed for
it.

```sh
millwork shot app.py /orders --out orders.png
millwork shot app.py /orders --full              # the whole page, as far as it scrolls
millwork shot app.py /orders --width 390 --dark  # a phone that is set to dark
millwork shot app.py /orders --user ada --claims '{"role": "admin"}'
```

`--user` signs in as a user with that id, in an app with sign-in. The
app's `on_login` is not asked about that user. The picture is of the
page as it opens. Nothing is pressed or typed first,
and what a press does is for a test with
[`TestApp`](/testing). A page that never rests, such as one with a
spinner that stays, is taken when `--timeout` runs out, and the command
says so.
