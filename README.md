<p align="center"><img src="bundle/public/favicon.svg" alt="" width="72"></p>

<h1 align="center">millwork</h1>

<p align="center">A modern UI framework for Python</p>

<p align="center">
  <a href="https://github.com/DvGils/millwork/actions/workflows/ci.yml"><img src="https://github.com/DvGils/millwork/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB" alt="Python 3.12 or newer">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0">
</p>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".github/readme/app-dark.png">
  <img src=".github/readme/app-light.png" alt="A millwork page: three stat tiles with trends, a bar chart and a sortable table, in the default theme.">
</picture>

A page is a Python function of the session's state. A handler changes the
state, the page renders again, and the browser receives a patch. The React bundle
ships inside the package, so a project is Python only.

```python
import millwork as mw
from millwork import ui
from pydantic import BaseModel


class State(BaseModel):
    clicks: int = 0


app = mw.App("hello", state=State)


@app.page("/")
def home(s: mw.Session[State]) -> ui.Component:
    return ui.Page(
        ui.Text(f"Clicked {s.state.clicks} times."),
        ui.Button("Add one", on_click=lambda s, _: setattr(s.state, "clicks", s.state.clicks + 1)),
    )
```

```bash
uv add millwork  # or `pip install millwork`
uv run millwork run app.py
```

## What is in the box

- **A catalogue of components** on shadcn/ui: layout, text, inputs,
  feedback, tables, charts, forms from Pydantic models, files, tasks with
  progress, and a chat surface that streams replies from Python.
- **One model of state.** Python owns the state; a control is owned by
  Python or by the browser, and the page says which.
- **Long work as tasks**, with progress, steps and cancellation drawn by
  the page, and chat replies that stream text, reasoning and tool steps.
- **Files over the session's socket.** Uploads, downloads and inline
  images travel on the same connection as everything else, so replicas
  need no sticky routing and no shared storage.
- **Sign-in** with password, OAuth and proxy-header providers behind one
  `on_login` hook, and a theme file in the shadcn token vocabulary for
  colors, fonts and logos.
- **A test harness** that drives a page without a browser: open it,
  click, change, submit, and read what the tab would have received.
- **One process to run.** `millwork run` serves an app on a port or a
  unix socket, behind a proxy and under a path prefix, with a health
  route for the host.

## The manual

The manual is at [millwork-ui.com](https://millwork-ui.com). It is a
millwork app: every example in it runs, with the Python code beside it.
The chapters cover pages and routing, state and handlers, signing in,
theming, testing and running, and every component has a live example. It
also runs locally:

```
uv run millwork docs
```

Then open http://127.0.0.1:8008.

## Status

millwork is still in beta.

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
every checkout runs without Node. That includes a Dependabot bump of the
bundle's packages: apply it, rebuild, look at the manual, and commit the
`dist` with it, or CI refuses the branch. The manual's pages under
`src/millwork/manual/pages` are the gallery a bundle upgrade is judged
against.

## Releasing

A release is a tag. Write the version's section in `CHANGELOG.md`, set the
version with `uv version`, commit, tag it `v` plus the version and push the
tag. The release workflow waits for approval, checks the tagged commit,
builds the wheel, publishes it to PyPI and makes the GitHub release from
the changelog section. The published release then deploys the hosted
manual from that version on PyPI; `deploy/` holds its image and Fly
configuration. To deploy one by hand, put the release's wheel next to the
image with `gh release download v<version> --pattern "millwork-*.whl" --dir
deploy`, then `flyctl deploy ./deploy`.

## License

Apache-2.0.
