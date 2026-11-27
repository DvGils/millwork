---
title: Layout
order: 0
description: Page, Sidebar, Stack, Row, Grid, Card, Tabs and the rest of the frame.
---

# Layout

A page is a tree. Layout components arrange their children, carry no
state and emit no events. Children are positional, so a page reads like
the screen it makes.

## Page
<!-- keywords: shell, frame, root layout -->

`ui.Page` is the root of every page. It is as high as the viewport,
scrolls its body under a fixed header, and lays itself out around a
`ui.Sidebar` child when there is one. Its children form a column with
`gap` between them, six steps unless told otherwise, so a header, a row
of stats, a chart and a table stand apart without a `Stack` around them.
Give it a `title` for the browser tab and a `header` for the app bar.
`padding=False` lets a child such as `ui.Chat` fill it edge to edge.
`max_width` keeps the column from growing wider than a CSS length, such
as `"60rem"` or `"960px"`, and centers it in the room the page has.

A page prints in full, on as many sheets as its content needs. The
sidebar and the header stay off the paper, a box that scrolls on screen,
such as a table with a `height`, prints its whole content, and a page in
the dark scheme prints in the light one. A heading or a card's title
stays on the sheet of what follows it. A table of more than 200 rows
draws only the rows in view, and those are the ones that print.
`s.print()` opens the browser's print dialog from a handler, which is
also how a person saves the page as a PDF.

This manual is a `Page` with a `Sidebar`, so the page itself is not
shown inline. The sidebar is.

## Sidebar
<!-- keywords: navigation, nav, menu, drawer -->

`ui.Sidebar` holds the places to go. A `ui.Link` in it is drawn as a row
to press, with its `icon` in front, a `badge` such as a count at its end,
and the one marked `active=True` set apart. `ui.SidebarGroup` folds a set
of links under a label: open by default, folded with `default_open=False`,
and the browser remembers what the reader did unless `open` is given, in
which case `on_toggle` reports the click and Python decides.
`collapsible=False` makes it a plain heading over its links. This manual's
sidebar is one such group per part. Outside a `Page`, a `Sidebar` is its
children in a column, which is how it is shown here.

```python live
ui.Sidebar(
    ui.Link(label="Overview", href="/components/layout#sidebar", icon="home", active=True),
    ui.SidebarGroup(
        ui.Link(label="Orders", href="/components/layout#sidebar", icon="table", badge="3"),
        ui.Link(label="Customers", href="/components/layout#sidebar", icon="users"),
        label="Sales",
    ),
    ui.SidebarGroup(
        ui.Link(label="Members", href="/components/layout#sidebar", icon="user"),
        ui.Link(label="Billing", href="/components/layout#sidebar", icon="settings"),
        label="Settings",
        default_open=False,
    ),
    cls="max-w-xs rounded-lg border bg-sidebar p-3 text-sidebar-foreground",
)
```

## Floating
<!-- keywords: draggable window, popover, overlay -->

`ui.Floating` pins its children over the page in a bottom corner, where
they stay while the page scrolls, for a status chip or a small panel that
should always be at hand. `side` picks the corner, `draggable=True` lets
the reader move it, and `resizable=True` lets them pull its edges, with
the browser remembering both. It never leaves the browser window, and
shrinks to fit when the window does. The button below pins a badge to
this page; it goes away with the page. A button that becomes a window with
a chat in it is `ui.Assistant`, on the [Chat](/components/chat) page.

```python live
from pydantic import BaseModel


class Pinned(BaseModel):
    shown: bool = False


def example(s):
    st = s.state.pinned
    return ui.Stack(
        ui.Button(
            "Unpin the badge" if st.shown else "Pin a badge to this page",
            variant="outline",
            on_click=lambda s, _: setattr(st, "shown", not st.shown),
            cls="self-start",
        ),
        ui.Floating(ui.Badge("3 tasks running", tone="primary"), side="left", draggable=True) if st.shown else None,
        gap=3,
    )
```

## Stack and Row
<!-- keywords: flex, horizontal, vertical, side by side, align, spacing, gap -->

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

`fill=True` makes a `Stack` as high as the window has room, for
[a page that fills the window](#a-page-that-fills-the-window).

## Grid
<!-- keywords: columns, two columns, side by side, responsive, breakpoints -->

`ui.Grid` places children in columns. `cols` is a count from 1 to 12, or a
mapping of counts by width. `sm` is the count on the narrowest screens, a
phone included, and `md`, `lg` and `xl` take over from 768, 1024 and 1280
pixels up. A width left out keeps the count of the one below it.

```python live
ui.Grid(
    ui.Stat(label="Sessions", value="1,204", hint="today"),
    ui.Stat(label="Replies", value="3.8 s", hint="median", tone="success"),
    ui.Stat(label="Errors", value="2", tone="destructive"),
    cols={"sm": 1, "md": 3},
)
```

## Card
<!-- keywords: panel, box, container, tile -->

`ui.Card` frames content with an optional `title`, `description` and
`footer`. `tone` colors its edge, and `on_click` makes the whole card a
target. A clickable card takes focus, and Enter or Space clicks it. A
press on a button, a field, a slider or any other control inside the card
is that control's and does not click the card. Neither does a drag, to
select text or to move a handle.

`padding=False` takes the room around the content away, so a list, a
table or a `ui.Chat` reaches the card's edges. A title keeps the room
above it.

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
<!-- keywords: resizable panes, splitter -->

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
<!-- keywords: tab strip, tabbed -->

`ui.Tabs` holds `ui.Tab` children, each with an `id` and a `label`, and
an optional `icon` or `badge`. The chosen tab is the tab's own business
unless the page passes `value`, and `default` names the first one shown.
Panels stay mounted when hidden, so what the user typed in one survives a
switch. A strip wider than its place, as on a phone, scrolls sideways.

```python live
ui.Tabs(
    ui.Tab(ui.Text("Overview text."), id="overview", label="Overview"),
    ui.Tab(ui.Input(placeholder="Type, switch away and back"), id="edit", label="Edit", badge="1"),
    ui.Tab(ui.Text("Settings text."), id="settings", label="Settings", icon="settings"),
    default="overview",
)
```

## Lazy parts
<!-- keywords: performance, lazy load, defer rendering, render only what shows -->

A page function builds the whole page at every render, the tabs nobody is
looking at included. `ui.lazy` marks a function whose part of the page is
kept up to date only while its tab is open.

```python
@ui.lazy
def history(s: mw.Session[State]) -> ui.Component:
    return ui.Table(s.state.history, columns=COLUMNS)


@app.page("/")
def home(s: mw.Session[State]) -> ui.Component:
    return ui.Page(
        ui.Tabs(
            ui.Tab(overview(s), id="overview", label="Overview"),
            ui.Tab(history(s), id="history", label="History"),
        )
    )
```

`history(s)` puts the function and its arguments in the page. The
function runs when the page is first drawn, after that at every render in
which its tab is the open one, and once more as the tab is left. While
another tab is open the part stays in the browser as it was when it was
left, with what was typed into it, and a render does not look at it.
Opening the tab draws it again.

In this example each part counts how often it was drawn, which a real one
would not do. Tick a few times, then open the other tab.

```python live
from pydantic import BaseModel


class Ticks(BaseModel):
    n: int = 0
    drawn: dict[str, int] = {}


@ui.lazy
def part(s, name):
    st = s.state.ticks
    st.drawn[name] = st.drawn.get(name, 0) + 1
    return ui.Text(f"{name}: tick {st.n}, drawn {st.drawn[name]} times.")


def example(s):
    st = s.state.ticks
    return ui.Stack(
        ui.Row(ui.Button("Tick", on_click=lambda s, _: setattr(st, "n", st.n + 1))),
        ui.Tabs(
            ui.Tab(part(s, "First"), id="first", label="First"),
            ui.Tab(part(s, "Second"), id="second", label="Second"),
        ),
    )
```

It pays on a page with heavy tabs that renders often, where every render
then costs what the open tab costs. The first draw holds every tab, as it
does without `ui.lazy`.

- The arguments are worked out at every render, like those of any call.
  Only the body of the function waits.
- A lazy function follows the rule of a page function. It builds its part
  from the state and does nothing else. What a tab needs loaded is loaded
  by a handler, the `on_change` of the `ui.Tabs` for one, or by the
  page's `connect`.
- A lazy part goes where a child goes, directly in a `ui.Tab` or deeper,
  as in `ui.Tab(ui.Stack(intro, history(s)), ...)`. A lazy part can hold
  lazy parts, and tabs of its own. A `ui.Tab` itself is not lazy.
- Anywhere but inside a `ui.Tab` a lazy part is built at every render,
  so one function serves a tab on one page and a plain page elsewhere.
- Nothing is wired for it. With `value` the page says which tab is open,
  and with `default` the browser says so by itself.
- What has to change while its tab is closed does not belong in a lazy
  part. A `ui.Dialog` that a button in another tab opens is one.
- What is still going on in a closed tab goes on. A reply keeps
  streaming and an upload finishes. Before a handler in a closed tab's
  part is called the part is drawn again, so what is called is always
  the page as it is now.

## Accordion and Collapsible
<!-- keywords: collapse, expand, faq, details -->

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
<!-- keywords: overflow, scrollable, auto scroll, scroll to bottom, stick to bottom, follow, log, tail -->

`ui.ScrollArea` scrolls its children inside a fixed `height`.

```python live
ui.ScrollArea(
    ui.Stack(*(ui.Text(f"Line {i + 1}") for i in range(30)), gap=1),
    height="8rem",
)
```

`stick_to_end=True` is for a list that grows at its end, such as
messages or a log. The area opens at its end and stays there as rows
arrive. A reader who scrolls up is left where they are, and the area
stays at its end again once they are back there.

```python live
from pydantic import BaseModel


class Feed(BaseModel):
    lines: list[str] = [f"Line {i + 1}" for i in range(30)]


def more(s, _):
    lines = s.state.feed.lines
    lines.append(f"Line {len(lines) + 1}")


def example(s):
    return ui.Stack(
        ui.ScrollArea(
            ui.Stack(*(ui.Text(line, key=line) for line in s.state.feed.lines), gap=1),
            height="8rem",
            stick_to_end=True,
        ),
        ui.Button("Add a line", variant="outline", on_click=more),
        gap=2,
    )
```

## A page that fills the window
<!-- keywords: full height, viewport height, 100vh, fixed footer, sticky footer, composer, message list, chat layout, app shell, frame -->

A page is as long as its content and scrolls as a whole. Some pages are
a frame instead, with a bar on top, a list that scrolls in the middle
and a field that stays at the bottom. `ui.Stack(fill=True)` makes that
frame. The stack is as high as the window has room under the header, and
no higher, so what is in it has to fit. The part that is long goes in a
`ui.ScrollArea(fill=True)`, which takes the height the other children
leave and scrolls inside it.

```python
@app.page("/channel")
def channel(s: mw.Session[State]) -> ui.Component:
    return ui.Page(
        ui.Stack(
            ui.Text("# general", variant="subheading"),
            ui.ScrollArea(
                ui.Stack(*(ui.Text(m.text, key=m.id) for m in s.state.messages), gap=1),
                fill=True,
                stick_to_end=True,
            ),
            ui.Input(placeholder="Message", clear_on_submit=True, on_submit=post),
            fill=True,
        ),
    )
```

`fill` works on a child of the `Page` and on a child of a `Stack` that
fills. Anywhere else there is no height to take, and the stack or the
area is as high as its content. `padding=False` on the `Page` takes the
frame to the edges of the window. A `ui.Chat` and a `ui.Split` fill a
page the same way without being told. A `ui.Table(fill=True)` takes the
room that is left as well. Its rows scroll inside it, and what comes
after it stands at the foot of the window. A `Stack` that fills works in
a pane of a `Split` too.
