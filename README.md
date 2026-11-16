<p align="center"><img src="https://raw.githubusercontent.com/DvGils/millwork/main/bundle/public/favicon.svg" alt="" width="72"></p>

<h1 align="center">millwork</h1>

<p align="center">A modern UI framework for Python</p>

<p align="center">
  <a href="https://github.com/DvGils/millwork/actions/workflows/ci.yml"><img src="https://github.com/DvGils/millwork/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB" alt="Python 3.12 or newer">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0">
</p>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/DvGils/millwork/main/.github/readme/demo-dark.gif">
  <img src="https://raw.githubusercontent.com/DvGils/millwork/main/.github/readme/demo.gif" alt="A millwork page in use: a form submits with a validation message and then succeeds, an import runs with a progress bar and steps while rows appear in the table and the bars of a chart move with them, and a question in a floating assistant gets an answer that streams in and puts an orange highlight around the figure it is about." width="100%">
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

## Installation


```bash
uv add millwork  # or `pip install millwork`
uv run millwork run app.py
```

## Examples

Four whole apps are in [`examples/`](https://github.com/DvGils/millwork/tree/main/examples). Each has a
look of its own, tests, and a page that shows it in use and says how it
is made.

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="https://github.com/DvGils/millwork/tree/main/examples/chat"><img src="https://raw.githubusercontent.com/DvGils/millwork/main/examples/chat/chat.png" alt="A team chat on a desk screen and on a phone, with channels in a sidebar, messages, a reaction and a count of unread messages." width="100%"></a>
      <br>
      <b><a href="https://github.com/DvGils/millwork/tree/main/examples/chat">Team chat</a></b>
      <br>
      Channels with messages that arrive as they are sent, who is typing, unread counts and reactions, on a desk and on a phone.
    </td>
    <td width="50%" valign="top">
      <a href="https://github.com/DvGils/millwork/tree/main/examples/claims"><img src="https://raw.githubusercontent.com/DvGils/millwork/main/examples/claims/claims.png" alt="A manager's screen with an expense claim open beside the photo of its receipt, and the phone of the person who filed it." width="100%"></a>
      <br>
      <b><a href="https://github.com/DvGils/millwork/tree/main/examples/claims">Expense claims</a></b>
      <br>
      Sign-in for three kinds of people, a claim filed with its receipt, reviewed beside it and paid, and a report that prints.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="https://github.com/DvGils/millwork/tree/main/examples/analyst"><img src="https://raw.githubusercontent.com/DvGils/millwork/main/examples/analyst/analyst.png" alt="A dark page with charts pinned to a board at the left and a chat at the right, where an answer about a month is marked on the line chart." width="100%"></a>
      <br>
      <b><a href="https://github.com/DvGils/millwork/tree/main/examples/analyst">Analyst</a></b>
      <br>
      A chat that answers questions about data, pins charts to a board and marks what an answer is about. It runs on a script, or on Claude with a key.
    </td>
    <td width="50%" valign="top">
      <a href="https://github.com/DvGils/millwork/tree/main/examples/microscope"><img src="https://raw.githubusercontent.com/DvGils/millwork/main/examples/microscope/microscope.png" alt="A round view through a microscope with colored cells in a drop of water, beside charts of how the cells changed over the generations." width="100%"></a>
      <br>
      <b><a href="https://github.com/DvGils/millwork/tree/main/examples/microscope">Microscope</a></b>
      <br>
      A drop of water in which cells evolve over the generations, drawn on a canvas by a component of the app's own and moved on by a clock on the server.
    </td>
  </tr>
</table>

## What is included

- **A catalog of components** on shadcn/ui: layout, text, inputs,
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

The manual is at [millwork-ui.com](https://millwork-ui.com).  

The manual itself is a millwork app. Every example in it runs, with the Python code beside it.
The chapters cover pages and routing, state and handlers, signing in,
theming, testing and running, and every component has a live example. It
also runs locally:

```
uv run millwork docs
```

Then open http://127.0.0.1:8008.

`millwork reference` prints the catalog as one Markdown table of every
component, its props with their types and defaults, the session's and the
app's calls, the icon names, the form widgets and the formats. The hosted
manual serves the same text at
[millwork-ui.com/llms.txt](https://millwork-ui.com/llms.txt), for a model
that needs easy lookup.

With words behind it, the command looks one thing up in the reference
and in the manual, and prints the few parts that are about it:

```sh
millwork reference ui.Table        # an entry, and the manual's section on it
millwork reference shared data     # by what it is about
millwork reference modal           # by what it is called elsewhere
millwork reference testing.md      # a page of the manual
millwork reference --index         # every name, and nothing more
```

## Status

millwork is still in beta.

## Contributing

Bug reports and fixes are welcome.
[CONTRIBUTING.md](https://github.com/DvGils/millwork/blob/main/CONTRIBUTING.md)
has the setup, the checks a change has to pass, and how to propose a
larger one.

## License

Apache-2.0.
