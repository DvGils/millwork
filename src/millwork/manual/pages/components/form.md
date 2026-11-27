---
title: Form
order: 6
description: A form from a Pydantic model, with issues by field.
---

# Form
<!-- keywords: pydantic, model, validation, schema, fields -->

`ui.Form` renders a Pydantic model as fields and hands `on_submit` a
validated instance. The types choose the controls. A `str` becomes an
input, `int` and `float` a number, `bool` a switch, `Literal` and `Enum` a
select, `date` a date picker, a nested model a fieldset, and a list of
models a repeatable list. Validation errors land on the field they
concern.

## From a model

`Field(title=, description=, examples=)` give a field its label, its help
text and its placeholder. Constraints such as `min_length`, `ge` and `le`
become the control's limits and the validation. What a person reads
when a field is wrong comes from the theme's strings, the ones that start
with `issue_`, so it is in the app's language. A validator of the model's
own is shown with the words it raised, whether that is a `ValueError` or
a `PydanticCustomError`.

`layout` is `"vertical"` with each label above its field,
`"horizontal"` with the label beside it, or a number of columns from 1
to 12. On a narrow screen the columns are one.

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
    s.state.saved.last = f"{project.title} ({project.language}, {project.count})"


def example(s):
    return ui.Stack(
        ui.Form(Project, on_submit=save, layout=2),
        ui.Text(f"Saved: {s.state.saved.last}", variant="muted"),
        gap=4,
    )
```

## Labels and overrides
<!-- keywords: customize a field, widget, placeholder -->

`labels` maps a field's pointer, or its name, to a `label`, `help`,
`placeholder` and `choices`, so the model stays free of interface copy.
`overrides` maps a pointer to any spec key, such as a `widget`, `min`,
`max`, `step` or `rows`. `counter` shows under a text field how much it
holds, against its `max_length`. `fields` picks a subset in order.
What `overrides` says of a file field, its `accept` and `max_size_mb`,
is checked on the server as well as in the browser, and goes before the
same keys in the model's `json_schema_extra`. A field that `fields`
leaves out takes no upload.

A text field that may hold more than 200 characters is drawn as a
multi-line box. `overrides={"/label": {"widget": "input"}}` keeps it to
one line. The button under a repeatable list says `Add` and the name of a
row, from the theme's string `add_item`.

`choices` is a list of bare values, `(value, label)` pairs, dicts and
`ui.Option`s. A dict takes the keys an Option has. An Option's value is
a string, so a field that holds a number takes its choices as dicts or
pairs. A choice's `icon` is drawn wherever the choice is listed, and
`disabled=True` keeps it from being picked. Its `description` shows
under a choice of a `radio` or `checkboxes` widget, and its `group`
heads a section of a `select`. A field that already holds a disabled
choice keeps it until the field is changed. A text field given `choices`
becomes a `select`. A field of another type names the widget that shows
them in `overrides`.

The widgets are `input`, `textarea`, `password`, `number`, `slider`,
`switch`, `checkbox`, `select`, `radio`, `toggle`, `multiselect`,
`checkboxes`, `tags`, `date`, `datetime`, `color`, `file`, `files` and
`hidden`.
Each field gets one from its type, and an override swaps it for another
that fits the same value, such as `radio` for a short enum or `toggle` for
a boolean that is given its two `choices`. The `color` widget makes a
text field a [color picker](/components/inputs#colorpicker), and takes
the picker's `swatches`. A field with a `default_factory` opens with what the factory
makes, so a date field defaulting to today shows today. A factory that
makes a new value on every call, a uuid or the time of day, gives the form
nothing, and the model makes that value on submit as it always did.

```python live
from pydantic import BaseModel


class Prefs(BaseModel):
    name: str = ""
    level: int = 1
    mood: str = "ok"
    tags: list[Literal["a", "b", "c"]] = []


ui.Form(
    Prefs,
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

## Models in a model
<!-- keywords: nested model, list of models, repeatable rows, discriminated union, variant, one of several types, polymorphic, hidden field, recursive -->

A field that holds another model is a group of that model's fields,
headed by the field's label. A list of models is a list of rows, with a button
that adds a row and one on each row that removes it. The add button names
a row by the title of the row's model. A list of several models has no
one title to take, so it says the field's name until `overrides` gives
the list an `item_label`.

A field that is one of several models, a union with a discriminator, has
a select of its type above the fields of the model that is chosen. The
select's label is the theme's string `type`, and each choice is the title
of its model. A change of type keeps what both models have, such as a
name, and gives the rest the new model's defaults.

```python live
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Email(BaseModel):
    kind: Literal["email"] = "email"
    name: str = Field("", title="Name")
    address: str = Field("", title="Address")


class Phone(BaseModel):
    kind: Literal["phone"] = "phone"
    name: str = Field("", title="Name")
    number: str = Field("", title="Number")


class Contact(BaseModel):
    person: str = Field("", title="Person")
    ways: list[Annotated[Email | Phone, Field(discriminator="kind")]] = Field(default=[], title="Ways to reach them")


ui.Form(
    Contact,
    initial={"ways": [{"kind": "email", "name": "Office", "address": ""}]},
    overrides={"/ways": {"item_label": "Way"}},
    on_submit=lambda s, v: s.toast(f"{len(v.ways)} ways to reach {v.person or 'someone'}"),
)
```

In a form laid out in columns, a list and a union lie across all of
them, and the fields of a row stand in the same columns. In a group or
in a nested model they keep to its one column.

A field is kept off the page in two ways. The `hidden` widget, given in
`overrides`, hides it in one form. `json_schema_extra={"hidden": True}`
on the model's field leaves it out of every form. Either way, what
`initial` holds of it comes back on submit, which is how a row keeps its
id.

A model that holds itself, such as a folder with a list of folders,
cannot be a form, since a form is drawn whole. `ui.Form` refuses it and
names the field where the model comes back. Each level gets a model of
its own, or the field is left out with
`json_schema_extra={"hidden": True}`. The `hidden` widget does not do
that.

## Rejecting a valid draft
<!-- keywords: server-side validation, custom error message -->

A handler that finds something wrong raises `ui.FormIssues` with a list
of `(pointer, message)` pairs. The form shows each at its field and keeps
the draft. An issue for a place that has no field of its own, such as
one tag of a list of tags, is shown at the nearest field above it, and at
the foot of the form when there is none.

A field in a row of a list has two pointers. An issue names one row, so
it has the row's number, `/groups/1/values`. `labels` and `overrides`
speak of the field in every row, so they leave the number out,
`/groups/values`.

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

The form's button is greyed from the press until the handler is done,
and it turns when that takes more than a moment.

## Submitting from outside

`submit=None` hides the form's own button, and a `ui.Button(form=key)`
anywhere on the page submits the form with that key.

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
