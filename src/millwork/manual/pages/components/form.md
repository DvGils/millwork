---
title: Form
order: 6
---

# Form

`ui.Form` renders a Pydantic model as fields and hands `on_submit` a
validated instance. Types choose the controls: `str` an input, `int` and
`float` a number, `bool` a switch, `Literal` and `Enum` a select, `date` a
date picker, a nested model a fieldset, a list of models a repeatable list.
Validation errors land on the field they concern.

## From a model

`Field(title=, description=, examples=)` give a field its label, its help
text and its placeholder. Constraints such as `min_length`, `ge` and `le`
become the control's limits and the validation.

```python live
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class Project(BaseModel):
    title: str = Field(title="Title", examples=["Q1 report"], min_length=3)
    language: Literal["en", "nl", "de"] = Field("en", title="Language")
    starts: dt.date | None = Field(None, title="Starts")
    count: int = Field(3, ge=1, le=10, title="Copies", description="Between one and ten.")
    enabled: bool = Field(True, title="Active")
    notes: str | None = Field(None, title="Notes", max_length=500)


class Saved(BaseModel):
    last: str = "nothing yet"


async def save(s, project: Project):
    state(Saved).last = f"{project.title} ({project.language}, {project.count})"


def example(s):
    return ui.Stack(
        ui.Form(Project, on_submit=save, layout=2),
        ui.Text(f"Saved: {state(Saved).last}", variant="muted"),
        gap=4,
    )
```

## Labels and overrides

`labels` maps a field's pointer, or its name, to a `label`, `help`,
`placeholder` and `choices`, so the model stays free of interface copy.
`overrides` maps a pointer to any spec key: a `widget`, `min`, `max`,
`step`, `rows`. `fields` picks a subset in order.

```python live
from pydantic import BaseModel


class Settings(BaseModel):
    name: str = ""
    level: int = 1
    mood: str = "ok"
    tags: list[Literal["a", "b", "c"]] = []


ui.Form(
    Settings,
    fields=["name", "mood", "level", "tags"],
    labels={"name": {"label": "Display name", "help": "Shown to other users."}},
    overrides={
        "/mood": {"choices": [("ok", "Fine"), ("bad", "Not fine")]},
        "/level": {"widget": "slider", "min": 0, "max": 5},
        "/tags": {"widget": "multiselect"},
    },
    on_submit=lambda s, v: s.toast(f"{v.name or 'someone'} is {v.mood}"),
)
```

## Rejecting a valid draft

A handler that finds something wrong raises `ui.FormIssues` with a list of
`(pointer, message)` pairs; the form shows each at its field and keeps the
draft.

```python live
from pydantic import BaseModel, Field


class Signup(BaseModel):
    email: str = Field(title="Email")
    handle: str = Field(title="Handle", min_length=2)


TAKEN = {"ada", "grace"}


async def register(s, v: Signup):
    if v.handle.lower() in TAKEN:
        raise ui.FormIssues([("/handle", "That handle is taken.")])
    s.toast(f"Welcome, {v.handle}.", tone="success")


ui.Form(Signup, on_submit=register, submit="Register", cancel="Clear")
```

## Submitting from outside

`submit=None` hides the form's own button; a `ui.Button(form=key)` anywhere
on the page submits the form with that key.

```python live
from pydantic import BaseModel, Field


class Quick(BaseModel):
    query: str = Field("", title="Query")


ui.Row(
    ui.Form(
        Quick,
        key="quick",
        submit=None,
        on_submit=lambda s, v: s.toast(f"Searching {v.query!r}"),
        cls="grow",
    ),
    ui.Button("Go", form="quick", icon="search"),
    align="end",
    gap=3,
)
```
