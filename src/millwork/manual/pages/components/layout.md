---
title: Layout
order: 0
---

# Layout

A page is a tree. Layout components arrange their children, carry no
state and emit no events. Children are positional, so a page reads like
the screen it makes.

## Page

`ui.Page` is the root of every page. It is as high as the viewport,
scrolls its body under a fixed header, and lays itself out around a
`ui.Sidebar` child when there is one. Give it a `title` for the browser
tab and a `header` for the app bar. `padding=False` lets a child such as
`ui.Chat` fill it edge to edge.

This manual is a `Page` with a `Sidebar`, so it is not shown inline.

## Stack and Row

`ui.Stack` lays children out vertically and `ui.Row` horizontally. Both
take `gap`, `align` and `justify`, and a `Row` can `wrap`.

```python live
ui.Stack(
    ui.Row(ui.Badge("one"), ui.Badge("two"), ui.Badge("three"), gap=2),
    ui.Row(ui.Button("Left", variant="outline"), ui.Button("Right"), justify="between"),
    ui.Row(ui.Text("Centered", variant="muted"), justify="center"),
    gap=4,
)
```

`divided=True` draws a rule between the children of a `Stack`.

```python live
ui.Stack(ui.Text("First"), ui.Text("Second"), ui.Text("Third"), divided=True, gap=2)
```

## Grid

`ui.Grid` places children in columns. `cols` is a number, or a mapping with
`sm`, `md` and `lg` for the breakpoints at which the count changes.

```python live
ui.Grid(
    ui.Stat(label="Sessions", value="1,204", hint="today"),
    ui.Stat(label="Replies", value="3.8 s", hint="median", tone="success"),
    ui.Stat(label="Errors", value="2", tone="destructive"),
    cols={"sm": 1, "md": 3},
)
```

## Card

`ui.Card` frames content with an optional `title`, `description` and
`footer`. `tone` colors its border, and `on_click` makes the whole card a
target.

```python live
ui.Grid(
    ui.Card(
        ui.Text("The body of the card goes here, as children."),
        title="A card",
        description="With a description under the title.",
        footer=ui.Button("Action", size="sm"),
    ),
    ui.Card(
        ui.Text("Clicking me toasts."),
        title="Clickable",
        tone="primary",
        on_click=lambda s, _: s.toast("The card was clicked."),
    ),
    cols={"sm": 1, "md": 2},
)
```

## Separator

A rule between things, with an optional `label`.

```python live
ui.Stack(
    ui.Text("Above"),
    ui.Separator(),
    ui.Text("Between, with a label below"),
    ui.Separator(label="or"),
    ui.Text("Below"),
    gap=3,
)
```

## Split

`ui.Split` puts its children in resizable panes. `sizes` are the starting
percentages, `min_sizes` the smallest each may be dragged to, and
`collapsible` lets a pane fold away under its minimum. Give it a height with
`cls`, since it fills what it is given.

```python live
ui.Split(
    ui.Card(ui.Text("Left pane. Drag the handle."), title="Left"),
    ui.Card(ui.Text("Right pane."), title="Right"),
    sizes=[40, 60],
    min_sizes=[20, 20],
    cls="h-48",
)
```

## Tabs

`ui.Tabs` holds `ui.Tab` children, each with an `id` and a `label`, and
an optional `icon` or `badge`. The chosen tab is the tab's own business
unless the page passes `value`, and `default` names the first one shown.
Panels stay mounted when hidden, so what the user typed in one survives a
switch.

```python live
ui.Tabs(
    ui.Tab(ui.Text("Overview text."), id="overview", label="Overview"),
    ui.Tab(ui.Input(placeholder="Type, switch away and back"), id="edit", label="Edit", badge="1"),
    ui.Tab(ui.Text("Settings text."), id="settings", label="Settings", icon="settings"),
    default="overview",
)
```

## Accordion and Collapsible

`ui.Accordion` opens one `ui.AccordionItem` at a time, or several with
`multiple=True`. `ui.Collapsible` is a single section with a `title`.

```python live
ui.Stack(
    ui.Accordion(
        ui.AccordionItem(
            ui.Text("What a session is, and what it holds."), id="s", title="Sessions"
        ),
        ui.AccordionItem(ui.Text("How a handler changes state."), id="h", title="Handlers"),
        default=["s"],
    ),
    ui.Collapsible(ui.Text("Details that are usually folded away."), title="Advanced"),
    gap=4,
)
```

## ScrollArea

`ui.ScrollArea` scrolls its children inside a fixed `height`.

```python live
ui.ScrollArea(
    ui.Stack(*(ui.Text(f"Line {i + 1}") for i in range(30)), gap=1),
    height="8rem",
)
```
