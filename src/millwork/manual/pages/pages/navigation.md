---
title: Navigation
order: 2
description: Links and s.navigate, headings, the history, and navigation in the header and sidebar.
related: /components/layout, /pages/error-pages
---

# Navigation

A `ui.Link` whose `href` is a path inside the app navigates over the
session. Nothing reloads, the tab's history gets an entry, and the back
button works. From a handler, `s.navigate(path)` does the same. A
`#heading` on the path scrolls to that heading once the page is up, which
is how this manual's search opens a section. Without one, the page opens
at the top, and the back button returns to where the reader was.

```python live
def example(s):
    return ui.Row(
        ui.Button("Open the Charts page", on_click=lambda s, _: s.navigate("/components/charts")),
        ui.Link(label="or follow a link", href="/components/charts#stat"),
        ui.Text(f"You are at {s.path}", variant="muted"),
        gap=4,
        wrap=True,
    )
```

A link to another site is an ordinary link. Give it `target="_blank"` to
open a new tab. A link inside `ui.Markdown` behaves the same way: a path
of the app opens on the session, anything else opens a new tab.

## In the header and the sidebar

`ui.Header(links=[...])` puts links in the app bar, and `ui.Sidebar` holds
a longer list. A `ui.Link` in a sidebar is drawn as a row to press, with
its `icon` in front and the one marked `active=True` set apart, so the
list needs no classes of its own. `ui.SidebarGroup` folds a set of links
under a label. This manual's sidebar is a `Sidebar` of such groups. The
[Layout](/components/layout) page shows them all.

## What travels with the session

The session's state, its files, its identity and its tasks stay as the
tab moves around the app, so a value one page set is there for the next.
A page that should forget something on the way out does so in its `close`
hook, which [Sessions](/pages/sessions) describes.
