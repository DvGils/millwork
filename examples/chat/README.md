# Team chat

![Ada at a desk and Sam on a phone in the same channel. Sam asks a question, Ada sees him typing and answers, and what Sam says while she reads another channel is counted beside the one she left. When she comes back a line stands above what is new, and her reaction to it shows on both screens.](chat.gif)

Channels with unread counts, messages that arrive as they are sent,
three dots where someone is typing, mentions, reactions, and who is here
right now. In the picture Ada is at a desk in London and Sam on a phone
in Athens. They read the same messages, each at the time it was for
them.

```
uv run millwork run examples/chat/app.py
```

Open http://127.0.0.1:8000 and give a name. A second browser, or a
private window, is a second person.

## What it shows

| In the app | Made with | In the manual |
|---|---|---|
| The messages scroll and the field under them stays where it is | `ui.Stack(fill=True)` around a `ui.ScrollArea(fill=True, stick_to_end=True)` | [A page that fills the window](https://millwork-ui.com/components/layout#a-page-that-fills-the-window) |
| What one person does is there for the others | The chat is kept outside the sessions, with a `mw.Signal` beside each thing that changes by itself | [Data that sessions share](https://millwork-ui.com/state/accessing-the-session#data-that-sessions-share) |
| A field that empties at Enter and keeps a draft per channel | `ui.Input(clear_on_submit=True)` with an `on_change` | [Input](https://millwork-ui.com/components/inputs#input) |
| Dots at the first letter someone types | The same `on_change`, with `debounce_ms=0`, and a signal of the channel's own | [Input](https://millwork-ui.com/components/inputs#input) |
| A line above what is new, and a tint on what mentions the reader | Each session draws the same messages for its own person. What was new when the channel was opened is in the session's state | [State and handlers](https://millwork-ui.com/state/state-and-handlers) |
| A reaction chosen from a menu at a message | `ui.DropdownMenu`, with a handler bound to its message | [Lists and keys](https://millwork-ui.com/state/lists-and-keys) |
| Someone is a person without signing in | `App(identify_visitors=True)` and `s.visitor.id` | [Visitors](https://millwork-ui.com/pages/visitors) |
| A time is on the clock of whoever reads it | `s.timezone` | [The viewer's time zone](https://millwork-ui.com/pages/sessions#the-viewer-s-time-zone) |
| A count beside a channel with something new | `ui.Link(badge=)` | [Sidebar](https://millwork-ui.com/components/layout#sidebar) |
| A new channel, refused when its name is taken | A `ui.Form` in a `ui.Dialog`, and `ui.FormIssues` | [Rejecting a valid draft](https://millwork-ui.com/components/form#rejecting-a-valid-draft) |
| A look of its own, in the light and in the dark | `public/theme.json` and one font file | [Theming](https://millwork-ui.com/theming) |
| Tests with several people in them | One `TestApp`, a page for each person | [Two sessions](https://millwork-ui.com/testing#two-sessions) |

## The files

- `app.py` is the pages and the handlers.
- `chat.py` is what everyone shares. That is the channels, the messages,
  who has read what and who is typing. It builds no page, and of a
  session it only asks whose it is and whether its tab is there.
- `public/theme.json` is the look. The font is Figtree, under the SIL
  Open Font License that lies beside it.
- `test_team_chat.py` drives the app without a browser.
- `record.py` makes the picture above.

## Two signals

A message, a new channel and someone coming or going change what every
page shows in its sidebar, so every page follows `Chat.changed`. Typing
and reactions are different. They only show on their own channel, and
typing happens at every keystroke, so each channel has a signal of its
own, `Channel.changed`, and a keystroke in one draws no page on another.

The dots are there at the first letter because the field tells every
keystroke, with `debounce_ms=0`. Each one draws the typist's own page
again, which is a few milliseconds here and would be too much for a page
that is heavy to draw.

A mention shows in the sidebar as an `@` in front of the count, `@2`
where it would say `2`. That is all a `ui.Link` has for it.

## What it leaves out

Everything is kept in memory, so a restart empties it. A browser is a
person, and anyone can give any name. The signals reach the sessions of
one process. A message is Markdown, so one with an image in it makes
every reader's browser fetch that image from wherever it is. An app that
many strangers use needs sign-in, a store, a way to take messages down
and a rule for what a message may load.
