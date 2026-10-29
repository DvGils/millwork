<p align="center"><img src="bundle/public/favicon.svg" alt="" width="72"></p>

# millwork

[![CI](https://github.com/DvGils/millwork/actions/workflows/ci.yml/badge.svg)](https://github.com/DvGils/millwork/actions/workflows/ci.yml)

A Python framework for data tools and AI applications. The browser runs one
prebuilt React bundle; Python describes the page and handles its events.
There is no JavaScript to write, no build step in your project, and no state
in the browser that Python does not own.

```python
import millwork as mw
from millwork import ui

app = mw.App("hello")

@app.page("/")
def home(s: mw.Session) -> ui.Component:
    return ui.Page(
        ui.Text("Hello."),
        ui.Button("Say it", on_click=lambda s, _: s.toast("Hello from Python.")),
    )
```

```
millwork run app.py
```

millwork is early. The catalogue, the session model and the wire protocol
are in place and every component has a live example, but the first
production app has not been ported yet, and the API may still move.

## What you get

- **A catalogue of components** built on shadcn/ui: layout, text, inputs,
  feedback, tables, charts, forms from Pydantic models, files, tasks with
  progress, and a chat surface that streams replies from Python.
- **One way to think about state.** A page is a function of the session's
  state. A handler changes state; the page re-renders; the browser gets a
  patch. Controls are owned by Python or by the browser, never both.
- **Long work as tasks**, with progress, steps and cancellation drawn by the
  page, and chat replies that stream with reasoning and tool steps.
- **Files over the session's own socket.** Uploads, downloads and inline
  images never need a URL, so a deployment needs no sticky sessions and no
  shared storage.
- **Auth** with password and OAuth providers behind one `on_login` hook,
  and a theme file in the shadcn token vocabulary for colours, fonts and
  logos.
- **A test harness** that drives a page without a browser: open it, click,
  change, submit, and read what the tab would have received.

## Install

millwork needs Python 3.12 or newer. The package carries the built bundle,
so a machine without Node can install and run it.

```
uv add git+https://github.com/DvGils/millwork
```

## The manual

The manual is a millwork app: every example in it runs, with its Python
beside it, and a search box finds the section you need.

```
millwork docs
```

Then open http://127.0.0.1:8008. The manual is also the place to see what
an app looks like: each chapter is a page of a running millwork app.

## Developing millwork

Python is managed with uv, the bundle with pnpm; only `bundle/` needs
Node.

```
uv run pytest -q                       # the Python suite
uv run mypy src && uv run ruff check src tests
pnpm -C bundle exec tsc --noEmit       # the bundle's types
CI=1 pnpm -C bundle exec vitest run    # the bundle's unit tests
CI=1 pnpm -C bundle build              # rebuilds src/millwork/_bundle/dist
```

A change to the bundle is committed together with the rebuilt `dist`, so
every checkout runs without Node. The manual's pages under
`src/millwork/manual/pages` are the gallery a bundle upgrade is judged
against.

## License

Apache-2.0.
