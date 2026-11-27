---
title: Theming
order: 3
description: The theme file, tokens, fonts, logo, strings and a stylesheet of the app's own.
related: /components/custom, /sign-in/login-page
---

# Theming
<!-- keywords: theme, dark mode, light mode, colors, branding, css, style, palette, design -->

An app's look is one JSON file, either `public/theme.json`, which is found
on its own, or any path given as `App(theme=...)`. It holds the color
tokens for light and dark, the fonts, the logo and a few options. The
server renders it into the page before the bundle loads, so there is no
flash of the default look. Without a file the app looks like stock shadcn.

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
  "stylesheet": "/public/app.css",
  "density": "comfortable"
}
```

## Tokens
<!-- keywords: color variables, primary color, palette -->

The tokens are shadcn's. There are `background`, `foreground`, `card`,
`popover`, `primary`, `secondary`, `muted`, `accent` and `destructive`,
each with its `-foreground`, then `border`, `input`, `ring`, `chart-1` to
`chart-5`, the `sidebar-*` group, `radius`, `font-sans`, `font-mono` and
`font-heading`. `accent` is the tint a button or a row takes under the
pointer, so it wants to stand apart from `background` and `card`, while
`muted` is the quiet fill behind a code block or a skeleton. Three tokens
are millwork's own, with their `-foreground`. `success` and `warning` are
what the catalog's `tone` vocabulary needs, and `info` is there for a
custom component to use as `bg-info text-info-foreground`.

A value is one CSS value, so hex, `oklch(...)`, a length or a font stack.
A token left out keeps the default, which means a brand is four or five
values. An unknown token, or a value CSS could misuse, is refused when the
app starts.

A color under `light` is for the light scheme only. The dark scheme keeps
its default for that token until `dark` names it too. `radius` and the
fonts have no dark default, so they go under `light` and hold in both.

Light and dark are both always there. `mode` is `light`, `dark` or
`system`, and the user menu in the header lets a person choose, which
their browser remembers. The tones below take their colors from this
manual's theme file, in whichever scheme you are reading.

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
that stays apart for color-blind readers in both schemes.

## Fonts
<!-- keywords: typography, typeface -->

A font is a file under `public/`, served by the app, described by
`family`, `src`, `weights` (one weight or a range) and `style`. It becomes
an `@font-face` rule, and a token puts it to use. `font-sans` is the font
of the whole page. `font-heading` is the font of headings and of the
titles of cards, dialogs, sheets and the header, and follows `font-sans`
until it is set. `font-mono` is the font of code. A `url` to a font
service is accepted instead of `src`. That is logged once at start, as a
reminder that every page view then calls a third party. The page's
security policy lets that service's stylesheet and its font files in. An
app with a policy of its own names them there.

## Logo, favicon and login image

`logo` is one path, or `light` and `dark` paths. The `ui.Header` shows it
unless `logo=False`, and `ui.Logo` puts it on a page of the app's own,
such as an error page. `favicon` and `login_image` are paths under
`/public/` as well. The login page and the framework's error pages show
the logo and the app's name. A theme sets colors, fonts and these images.
Layout belongs to the components.

## Options

`density` is `comfortable` or `compact`. Compact tightens tables, forms,
stacks and cards, which suits data tools. `scrollbars` is `thin`, the
default, drawn in the page's own ink, or `auto` for the platform's.
`tooltip_mark` is what shows that a card's title or a field's label has
a `tooltip`. It is `help`, a question mark after the text, unless the
theme says `info`, an info icon there, or `underline`, a dotted line
under the text itself. An icon also answers to a tap on a phone, which
the line does not. A tab that is open takes a new mark when it loads
again.
`locale` sets the page language and how dates and numbers are formatted,
and `currency` is the ISO code the `currency` format uses, `EUR` unless
the theme says otherwise.

## A stylesheet of the app's own
<!-- keywords: custom css, tailwind, override styles -->

`stylesheet` is the path of a CSS file under `/public/`, loaded on every
page after the theme. It holds what tokens cannot say, such as a class
the app's `cls` props name, or a rule for print. Where one of its rules
and one of the bundle's classes set the same property, the app's rule
wins.

```css
/* public/app.css */
.figure { break-inside: avoid; }

@media print {
  .screen-only { display: none; }
}
```

## Strings
<!-- keywords: translation, i18n, localization, language, wording -->

Interface copy comes from the app's own Python, in its own language. The
framework has a few strings of its own, for the bundle's controls (`send`,
`stop`, `attach`, `search`, `no_results`, `clear`, `loading`,
`reconnecting`, `sign_in`, `username`, `password`) and for the messages
the server sends on its own account (`wait_for_reply`, `message_too_long`,
`something_went_wrong`, `too_many_sessions`, `signed_out` and the rest).
They are English. An app in another language sets them in the theme's
`strings` section, key by key, and a key the framework does not know is
refused. Every key is in the table below, with its English.

A label the framework fills in follows the same table. A form's submit
button says `save`, a `ui.Download` says `download`, a `ui.Assistant`
says `assistant` and a pie chart's folded slice says `other`, until the
app gives the component a label of its own.

A string can hold a name in braces that the framework fills in.
`add_item` is `Add {item}`, where `{item}` is the name of a row in lower
case and `{Item}` is the same as it was written, so a language that puts
the name first can start with it.

The keys that start with `issue_` say what is wrong with a form
field when pydantic found it, and the ones that start with `file_` say
why an upload was refused. Words the app wrote itself, in a validator or
a refusal of its own, are shown as written.

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

## Changing the theme while the app runs
<!-- keywords: reload theme, live theme, runtime, rebrand, switch theme -->

`await app.reload_theme()` reads the theme file again and shows it in
every open tab, without a reload of the page. An app that lets someone
change its look writes the file and then calls it.

```python
import json
from pathlib import Path

from millwork.theme import Theme

THEME = Path(__file__).parent / "public" / "theme.json"


async def publish(s: mw.Session, tokens: dict[str, dict[str, str]]) -> None:
    look = json.loads(THEME.read_text()) if THEME.exists() else {}
    look["tokens"] = tokens
    try:
        Theme.model_validate(look)
    except ValueError as error:
        s.toast(str(error), tone="destructive")
        return
    THEME.write_text(json.dumps(look))
    await app.reload_theme()
```

The rest of the file, such as the logo and the fonts, is kept, and only
the tokens are replaced. `Theme.model_validate` checks the look before it
is written. A file that is no theme would otherwise stay behind, and the
app would refuse it at its next start.

The file is the one given as `App(theme=...)`, or `public/theme.json`,
which need not be there when the app starts. The call returns `False`
when there is no file or it is not a valid theme, and the theme then stays
as it was. An app that was made with a `Theme` object has no file to read.

## While designing

In debug mode the theme file and its stylesheet are watched, and a save
reaches every open tab as a command, without a reload. `millwork docs --theme path/to/theme.json`
shows this whole manual in a theme, which is the quickest way to see a
token set on every component in both schemes.
