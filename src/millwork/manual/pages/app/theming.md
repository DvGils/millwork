---
title: Theming
order: 3
---

# Theming

An app's look is one JSON file: `public/theme.json`, found on its own, or
any path given as `App(theme=...)`. It holds the colour tokens for light
and dark, the fonts, the logo and a few options. The server renders it
into the page before the bundle loads, so there is no flash of the default
look. Without a file the app looks like stock shadcn.

```json
{
  "mode": "system",
  "fonts": [{"family": "Inter", "src": "/public/fonts/InterVariable.woff2", "weights": "100 900"}],
  "tokens": {
    "light": {"primary": "#0a7ea4", "primary-foreground": "#ffffff", "radius": "0.5rem",
              "font-sans": "'Inter', ui-sans-serif, system-ui, sans-serif"},
    "dark": {"primary": "#2a9ac4"}
  },
  "logo": {"light": "/public/logo.svg", "dark": "/public/logo-dark.svg"},
  "favicon": "/public/favicon.svg",
  "login_image": "/public/login.jpg",
  "density": "comfortable"
}
```

## Tokens

The tokens are shadcn's: `background`, `foreground`, `card`, `popover`,
`primary`, `secondary`, `muted`, `accent`, `destructive`, each with its
`-foreground`, then `border`, `input`, `ring`, `chart-1` to `chart-5`, the
`sidebar-*` group, `radius`, `font-sans`, `font-mono` and `font-heading`.
Three are millwork's own, with their `-foreground`: `success` and
`warning`, which the catalogue's `tone` vocabulary needs, and `info`, which
a custom component may use as `bg-info text-info-foreground`. A value is
one CSS value, hex, `oklch(...)`, a length or a font stack. A token left
out keeps the default, so a brand is four or five values. An unknown
token, or a value CSS could misuse, is refused when the app starts.

Light and dark are both always there: `mode` is `light`, `dark` or
`system`, and the user menu in the header lets a person choose, kept in
their browser. The tones below take their colours from this manual's
theme file, in whichever scheme you are reading.

```python live
ui.Stack(
    ui.Row(
        ui.Badge("primary", tone="primary"),
        ui.Badge("success", tone="success", icon="check"),
        ui.Badge("warning", tone="warning"),
        ui.Badge("destructive", tone="destructive"),
        ui.Badge("accent", tone="accent"),
        gap=2,
        wrap=True,
    ),
    ui.Alert(title="Saved", description="A success alert takes the success tokens.", tone="success"),
    gap=3,
)
```

The five chart tokens are read in order by the charts. Pick them as a set
that stays apart for colour-blind readers in both schemes.

## Fonts

A font is a file under `public/`, served by the app: `family`, `src`,
`weights` (one weight or a range) and `style`. It becomes an `@font-face`
rule, and the `font-sans` token names it. A `url` to a font service is
accepted instead of `src` and logged once at start, as a reminder that
every page view then calls a third party.

## Logo, favicon and login image

`logo` is one path, or `light` and `dark` paths; the `ui.Header` shows it
unless `logo=False`, and `ui.Logo` puts it on a page of the app's own, an
error page for instance. `favicon` and `login_image` are paths under
`/public/` too. The login page and the framework's error pages show the
logo and the app's name. A theme sets colours, fonts and these images;
layout belongs to the components.

## Options

`density` is `comfortable` or `compact`; compact tightens tables, forms,
stacks and cards for data tools. `scrollbars` is `thin` (the default, in
the page's own ink) or `auto` for the platform's. `locale` sets the page
language and how dates and numbers are formatted.

## Strings

Interface copy comes from the app's own Python, in its own language. The
framework has strings of its own: the bundle's controls (`send`, `stop`,
`attach`, `search`, `no_results`, `clear`, `loading`, `reconnecting`,
`sign_in`, `username`, `password`) and the messages the server sends on
its own account (`wait_for_reply`, `message_too_long`, `something_went_wrong`,
`too_many_sessions`, `signed_out` and the rest). They are English; an app in
another language sets them in the theme's `strings` section, key by key,
and a key the framework does not know is refused. Every key is in the
table below, with its English.

```json
{"locale": "nl", "strings": {"send": "Verstuur", "stop": "Stop", "search": "Zoeken"}}
```

```python live
from millwork.theme import STRINGS

ui.Table(
    rows=[{"key": k, "english": v} for k, v in sorted(STRINGS.items())],
    row_key="key",
    height=320,
)
```

## While designing

In debug mode the theme file is watched: a save reaches every open tab as
a command, without a reload. `millwork docs --theme path/to/theme.json`
shows this whole manual in a theme, which is the quickest way to see a
token set on every component in both schemes.
