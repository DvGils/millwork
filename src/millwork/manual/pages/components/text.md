---
title: Text
order: 1
description: Text, Markdown, Code, Badge, Kbd, Link and Tooltip.
---

# Text

Words on a page. Plain text with a variant and a tone, Markdown, code,
and the small pieces that label things.

## Text

`ui.Text` is a string with a `variant`, one of `body`, `muted`, `caption`,
`label`, `title`, `heading`, `subheading` and `mono`. `tone` colors it,
`truncate` keeps it to one line, and `align` sets the alignment.

```python live
ui.Stack(
    ui.Text("Heading", variant="heading"),
    ui.Text("Title", variant="title"),
    ui.Text("Subheading", variant="subheading"),
    ui.Text("Body text, the default."),
    ui.Text("Muted text for secondary information.", variant="muted"),
    ui.Text("A caption.", variant="caption"),
    ui.Text("A label", variant="label"),
    ui.Text("mono: for identifiers and paths", variant="mono"),
    ui.Row(
        ui.Text("success", tone="success"),
        ui.Text("warning", tone="warning"),
        ui.Text("destructive", tone="destructive"),
        ui.Text("primary", tone="primary"),
        gap=4,
    ),
    ui.Text(
        "A long line that is cut with an ellipsis when it does not fit the width it is given, however long it goes on.",
        truncate=True,
    ),
    gap=2,
)
```

## Markdown

`ui.Markdown` renders GitHub-flavored Markdown as real elements, with
headings, lists, tables, links and code. `tight=True` removes the outer
spacing for use inside a card or a table cell.

```python live
ui.Markdown("""
### A heading inside Markdown

Text with **bold**, *italic*, `code` and a [link](https://example.com).

- a list
- with items

| Column | Value |
| --- | --- |
| one | 1 |
| two | 2 |
""")
```

## Code

`ui.Code` shows a block of code with a `language` for highlighting, an
optional `title`, a copy button that `copyable` controls and is on by
default, `wrap` for long lines and `max_height` to scroll past.

```python live
ui.Code(
    'def greet(name: str) -> str:\n    return f"Hello, {name}."\n',
    language="python",
    title="greet.py",
)
```

## Badge

`ui.Badge` is a small label with a `tone` and an optional `icon`.

```python live
ui.Row(
    ui.Badge("default"),
    ui.Badge("muted", tone="muted"),
    ui.Badge("primary", tone="primary"),
    ui.Badge("accent", tone="accent"),
    ui.Badge("success", tone="success", icon="check"),
    ui.Badge("warning", tone="warning"),
    ui.Badge("destructive", tone="destructive"),
    gap=2,
    wrap=True,
)
```

## Icon

`ui.Icon` places an icon on its own, in a row next to text or anywhere a
component goes. `size` is `sm`, `md` or `lg`, and `tone` colors it. `label`
says what the icon means to someone who cannot see it. Without one it is
decoration.

`ui.Icon`, and every `icon` in the catalogue, takes one of two things. A
name is one of lucide's that the bundle carries, the set in `mw.ICONS`. A
path is a file of the app's own under `public/`, such as
`/public/icons/rocket.svg`. A path whose file is not there draws nothing,
and a [development warning](/state/warnings) says so when a page with
such a component is drawn.

```python live
ui.Row(
    ui.Icon("search"),
    ui.Icon("check", tone="success", label="Done"),
    ui.Icon("/public/mark.svg", size="lg"),
    ui.Icon("/public/mark.svg", size="lg", tone="primary"),
    ui.Button("From a file", icon="/public/mark.svg", variant="outline"),
    ui.Badge("From a file", icon="/public/mark.svg", tone="muted"),
    gap=3,
    wrap=True,
)
```

An SVG file is drawn in the color of the text around it, as the bundle's
icons are, so it follows the theme, a tone and dark mode. Only its shape
counts, which means an SVG in several colors comes out as one flat shape.
The file above is this manual's mark, which has a gradient of its own. A
PNG, WebP or JPEG is drawn as it is.

The path starts with `/public/`, no folder or file in it starts with a
dot, and it ends in `.svg`, `.png`, `.webp` or `.jpg`. Anything else is
refused when the component is made, so a path that comes from data cannot
lead out of `/public/` or to another site.
The browser fetches the file, and a file that is not there draws nothing
and is named in the browser's console.

As an icon a file is only looked at, and nothing in it is run. The same
SVG opened at its own address is a document, and a script in it does run
there. `public/` is for the app's own files, and nothing a visitor
uploaded belongs in it.

## Kbd

`ui.Kbd` shows keys as keycaps.

```python live
ui.Row(
    ui.Text("Save with"),
    ui.Kbd(keys=["Ctrl", "S"]),
    ui.Text("or press"),
    ui.Kbd(keys=["Enter"]),
    gap=2,
)
```

## Link

`ui.Link` is a hyperlink. `active=True` marks the link to the page the
session is on, as `aria-current="page"`, which a sidebar styles with
`aria-[current=page]:` classes. A path inside the app navigates over the
session without a reload, and `target="_blank"` opens a new tab.

```python live
ui.Row(
    ui.Link(label="Welcome, inside the app", href="/"),
    ui.Link(
        label="An outside site", href="https://example.com", target="_blank", icon="external-link"
    ),
    gap=6,
)
```

## Stat

`ui.Stat` is a number with a `label`, an optional `hint`, a `tone` and an
`icon`, for telemetry and summaries.

```python live
ui.Grid(
    ui.Stat(label="Tokens", value="12,480", hint="this session", icon="hash"),
    ui.Stat(label="Cost", value="€0.42", tone="success", icon="zap"),
    ui.Stat(label="Latency", value="1.9 s", hint="p95", tone="warning", icon="clock"),
    cols={"sm": 1, "md": 3},
)
```

## Tooltip

`ui.Tooltip` wraps one child and shows `content` on hover or focus.

```python live
ui.Tooltip(ui.Button("Hover me", variant="outline"), content="More about this button.")
```
