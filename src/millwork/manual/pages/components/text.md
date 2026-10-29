---
title: Text
order: 1
---

# Text

Words on a page: plain text with a variant and a tone, Markdown, code, and
the small pieces that label things.

## Text

`ui.Text` is a string with a `variant`: `body`, `muted`, `caption`, `label`,
`title`, `heading`, `subheading` or `mono`. `tone` colours it, `truncate`
keeps it to one line, `align` sets the alignment.

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

`ui.Markdown` renders GitHub-flavoured Markdown as real elements: headings,
lists, tables, links and code. `tight=True` removes the outer spacing for use
inside a card or a table cell.

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
optional `title`, a copy button (`copyable`, on by default), `wrap` for long
lines and `max_height` to scroll past.

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

`ui.Link` is a hyperlink. A path inside the app navigates over the session
without a reload; `target="_blank"` opens a new tab.

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
