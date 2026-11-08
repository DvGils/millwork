---
title: State and handlers
order: 0
description: One Pydantic model per session, handlers that change it, and who owns a control's value.
related: /quickstart, /pages/sessions, /components/inputs
---

# State and handlers

A session has one state. It is a Pydantic model the app declares, it lives
for as long as the session does, and every page is a function of it. A
handler changes that state, the page renders again, and the browser gets
the difference. There is nothing reactive to subscribe to and nothing to
invalidate. Whatever a page shows comes from `s.state`, and a handler is
the only place where things change.

## The loop

A handler is any callable bound to an `on_*` prop. It receives the session
and the event's payload, which is the new value for `on_change`, the
validated model for a form's `on_submit`, and nothing of use for
`on_click`. It may be sync or async. When it returns, the page renders
once, each in its turn, so a render sees state as the handler left it. A
handler that cannot take those two arguments is refused when the page is
built, with the expected shape in the error, so a one-argument lambda
fails before anyone clicks.

```python live
from pydantic import BaseModel


class Counter(BaseModel):
    n: int = 0
    note: str = ""


def bump(s, _):
    s.state.counter.n += 1


async def remember(s, text):
    s.state.counter.note = text


def example(s):
    st = s.state.counter
    return ui.Stack(
        ui.Row(
            ui.Button("Count", on_click=bump),
            ui.Text(f"{st.n} so far", variant="muted"),
            gap=3,
        ),
        ui.Input(value=st.note, placeholder="Type, then look right", max_length=200, on_change=remember),
        ui.Text(f"Python holds {st.note!r}", variant="muted"),
        gap=3,
    )
```

`Counter` here is `s.state.counter` because the manual composes its state
from its examples, as the [Welcome](/) page explains. An app declares the
model itself, as the next section shows.

A handler that raises shows "Something went wrong." as a toast and puts
the traceback in the log. The page stays as it was. A handler that needs
to ask first uses `s.confirm` or `s.ask`, both on the
[Feedback](/components/feedback) page.

## One state for the session

The app names the model once. Every page reads from the same instance,
and it stays as the tab moves from page to page, so what one page set is
there for the next to use. A value a page wants to forget on the way out
is reset in that page's `close` hook.

```python
class State(BaseModel):
    report: str | None = None
    filters: dict[str, str] = {}


app = mw.App("reports", state=State)


@app.page("/")
def choose(s: mw.Session[State]) -> ui.Component:
    return ui.Select(
        options=REPORTS,
        value=s.state.report,
        on_change=lambda s, name: setattr(s.state, "report", name),
    )


@app.page("/report")
def show(s: mw.Session[State]) -> ui.Component:
    return ui.Text(f"Showing {s.state.report}")
```

The `State` here is small because the app is. A bigger app does not grow
one long class, and [Organizing your app](/state/organizing) shows how it
splits.

## Who owns a value

A control shows either what Python says or what the browser holds. With
`value=`, every change is reported through `on_change` and Python decides
what the control shows. With `default=`, the browser holds the value and
changes are reported but not required. The [Inputs](/components/inputs)
page shows the two side by side. Inside a `ui.Form` every control is
browser-owned draft state until the form is submitted.
