# Changelog

Notable changes to millwork. Before 1.0 the API may move between minor
versions; a release says so here when it does.

## 0.4.0

### Bug fixes

- What a handler did was drawn about 50 ms late. The page was drawn
  50 ms after any change, so that changes close together became one
  patch, and a press waited that out like everything else. The page is
  now drawn as the handler ends, or 50 ms after the end of the drawing
  before it when that was more recent. What is typed into a `ui.Input`
  or a `ui.Textarea` is drawn within 50 ms as it was, since the field
  shows it already, and so are a task's reports and `s.refresh()`. A
  task that a handler starts shows as running at once, where one that
  was done within 50 ms showed nothing before. A test sees what it saw:
  in `millwork.testing` the end of a handler waits like any other
  change.
- A page that a handler left with `s.navigate()` could be drawn once
  more on its way out, and failed when the handler had left state the
  page could not show. It happened when a drawing came due while the
  handler was still running: a question, a task or `s.refresh()` more
  than 50 ms before it left.
- `s.reset(key)` took the keyboard out of the field it reset. A field
  that its own `on_submit` reset got the first entry and none after.
  The keyboard now stays where it was.

### Features

- A way to retire a spelling without breaking an app. The old spelling
  keeps working for one minor release and warns with a
  `MillworkDeprecationWarning` that points at the app's line, names the
  release that drops it and says what to write now. `millwork run` logs
  each one, once for every line that causes it. Nothing is deprecated yet.

### The manual

- Development has a section on deprecations, with the pytest setting that
  makes a test fail on one.
- The hosting checklist says what happens to a tab whose connection drops
  when there is more than one replica, and that cookie affinity in the
  load balancer brings it back to its session.

## 0.3.3

### Bug fixes

- Typing into a text field whose value the page holds, a `ui.Input`,
  `ui.Textarea` or `ui.NumberInput` with `value=`, could lose letters
  or whole words. The server's answer to what was typed came back a
  moment later and replaced the field's text, with it whatever had been
  typed since. It took a pause of between a quarter and three tenths of
  a second between two words. A field now keeps what was typed after
  the value it sent, and still takes any other value the server gives
  it.
- A text field whose value the page holds kept its text when a handler
  cleared the value right after the typing, as a Post button pressed at
  once does, or Enter in the field. The page held an empty value while
  the field showed the text, and the next keystroke sent the old text
  again. The field is now told.
- Open on a `ui.FileCard` with a session file left an empty tab and
  saved the file. It now shows a PDF, a picture that is no SVG, plain
  text, sound or film in the new tab, and saves any other file without
  opening one.
- `ui.Download` and `s.download` with bytes, text or a path, given as
  they are or made by a callable, kept a copy in the session for every
  press. A button pressed often
  enough used up the session's storage, and every download after that
  failed. The copy is now forgotten once the tab has it.
- **A file is no longer kept where it was before.** The `FileRef` that
  `s.download` returns for bytes, text or a path is good until the tab
  has the file. To keep a file in the session, make it
  with `s.files.add` and download that.
- `ui.Stack(divided=True)` drew no rules. There is now a rule between
  each two children that show.
- A custom component that imported a lucide icon the bundle does not
  carry got nothing for it, and failed with React's "error #130" when
  the icon was first drawn. It now fails when it is loaded, and names
  the icon.
- A task that failed was logged as an error with its traceback even
  when a handler was awaiting it and dealt with the failure. That is
  now one line. Any other failure is an error as before.
- A chat reply that raised sent the exception's own words to the tab as
  part of the reply, and so did a step that raised. Such words can name
  a table, a host or a path. The tab now gets "Something went wrong." in
  their place, and the log has the exception as before. In debug mode
  the words are sent as they were. A handler that wants words of its own
  catches the exception and calls `reply.error`.
- With more than one OAuth provider, the default login page gave the
  button of an intent to the first provider only, and two such buttons
  on a page of the app's own read the same. Every provider now has the
  button, and it names its provider, as in "Try the demo with Google".
  The words are a new theme string, `intent_with`.
- A theme font given as a `url` to a font service was blocked by the
  page's own security policy, so the font never loaded. The policy now
  lets the service's stylesheet and font files in. The reminder that
  such a font calls a third party was logged on every page view, and is
  logged once.
- `Auth(providers)` was typed as a `list[Provider]`, so a type checker
  refused a list of `OAuth` providers. It takes any sequence of them.
- A chart stayed behind its gray placeholder for three tenths of a
  second at the least, however soon its code arrived. On a repeat visit,
  where the code comes from the browser's cache, that was most of the
  wait. A chart is now drawn as soon as its code is there.

### Features

- `animate=True` on a `ui.BarChart`, `ui.LineChart`, `ui.AreaChart` or
  `ui.PieChart` lets the chart draw itself when it is first shown. Bars
  grow from the baseline, a line is drawn from its first point and a pie
  sweeps around. When the rows or the series change, the marks move
  from the old values to the new. It is off unless asked for. A reader whose system
  asks for less motion gets the chart at once, and a page that is
  printed has its charts as they are at the end.

- Six icons join the ones the bundle carries, which makes 150: `euro`,
  `file-search`, `files`, `message-square-plus`, `reply` and `user-pen`.

### The manual

- Charts has a section on motion, with an example.
- Custom says which lucide icons a component can import.
- Inputs says why a send button stays enabled, and what a `ToggleGroup`
  sends when its pressed button is pressed.
- Files says what Open on a `ui.FileCard` shows and what it saves, and
  how long a download's copy is kept.
- Tasks says how a failed task is logged.
- Testing says that a `TestApp` runs the app's startup hooks.
- Chat says what a reader sees of a reply that raised.
- Admitting users says what an intent's button reads with more than one
  provider.
- Hosting checklist says where a page's stylesheets and fonts may come
  from, and what an app with a policy of its own has to add for a font
  service.

## 0.3.2

### Bug fixes

- In a test, `page.event` refused an event of a `ui.Custom` with
  `hidden=True`, though a tab keeps a hidden component running and the
  server takes what it emits. A custom component's events are now taken
  whether it shows or not.
- In a test, `page.upload` to a hidden `ui.FileUpload` and `page.send`
  with files to a hidden `ui.Chat` stored the file before the action was
  refused, and an upload to a hidden `ui.FileUpload` without `on_upload`
  was taken. Both now raise `LookupError` before anything is stored.
- `ui.DropdownMenu` dropped the `tooltip` of its trigger button, so a
  trigger that is an icon alone had no hint on hover and no name for a
  screen reader.
- The `choices` of a `ui.Form` field ignored what a `ui.Option` carries
  beyond its value and label. A disabled choice could be picked and
  submitted, no icon was drawn, and an Option without a label drew an
  empty choice. A choice now keeps its `icon`, `description`, `group`
  and `disabled`, and the form's `select`, `radio`, `toggle`,
  `multiselect` and `checkboxes` widgets draw them. An icon name the
  bundle does not have fails when the page is built, as it does on an
  Option.
- A bare value in a form's `choices`, as in `{"choices": ["a", "b"]}`
  under `labels` or `overrides`, drew an empty choice. It is now a
  choice with the value as its label.
- A form's `toggle` widget on a field that holds a number or a boolean
  never showed which choice was pressed, though the draft held it.

### The manual

- Layout describes `ui.Page(max_width=)`, which takes a CSS length.
- Testing says where a chart's rows are on a found node.
- Form says what a field's `choices` take and which widget draws what.
- The header shows the version of millwork the manual describes, beside
  the title, as a link to that version's release notes. On a narrow
  screen it is in the navigation panel.

## 0.3.1

### Bug fixes

- A tab could go on running an old bundle against a newer server, after
  a deploy or when a browser restored the page from its cache. It then
  drew what it did not know as a broken custom component, as in
  "custom component SidebarGroup: HTTP 404". A tab now says which bundle
  it runs when it connects, and one that is not the bundle the server has
  loads the page again. It does so once. If the page that comes back
  names an old bundle again, as behind a cache that keeps the page, the
  tab says that the page is out of date and offers a reload.
- On a narrow screen a `ui.Header` kept its links in the user menu,
  behind a picture or a sun, and with `user_menu=False` they were gone
  altogether. A button at the left of the header now opens the links in
  a panel, with the page's sidebar below them when it has one. The bar
  that a page with a sidebar got under its header, for the button that
  opens the sidebar, is gone with it. The panel closes when a link in
  it is pressed and when the page behind it changes. The button's label
  is a new theme string, `navigation`, for an app that translates the
  framework's words.
- A `ui.Table` took rows that shared a `row_key`, or had none in that
  field, and ticking one of them ticked them all. Keys are now compared
  as a browser holds them, so 1 and 1.0 are one key, and so are two
  whole numbers too large for a browser to keep apart. A table that only
  shows its rows goes by their position when the field does not tell
  them apart, so the rows of a query's result need no key.
- **A page can now fail where it drew before.** A table that selects,
  opens or acts on a row, or is given `selected`, raises `ValueError`
  for rows that share a `row_key` or have none, and the error names the
  rows. Such a table drew before and acted on the wrong row. Give it a
  `row_key` whose values tell its rows apart.
- A chart in a `ui.Tab` that was not open put a warning in the browser's
  console, twice, about a width and height of 0. A chart is drawn once
  its box has a size.
- The development warning for a list without keys fired for a fixed row
  of children with one of them left out by `x if shown else None`. It
  now counts places, so it fires for children made from data.
- A label on a chart was cut off where it reached the edge: the value
  above the tallest bar, the value after the longest lying bar, and a
  series name longer than a few letters at the end of its line. A chart
  with `labels=True` keeps the room its labels take.
- A component in a chat reply, a table say, was held to the width a
  reply's words keep, 85% of the thread. In an `ui.Assistant` window
  that cut a table of three columns short. A component in a reply now
  gets the width of the thread, and the words keep their measure.
- A page function written to take a path's parameters, as in
  `def job(s, job_id)`, failed when the page was first drawn, with a
  `TypeError` about a missing argument that said nothing of where the
  parameters are. `@app.page` now refuses such a function when the app
  is built, and the error points at `s.params` and the page's connect
  hook.
- `ui.Combobox` was missing from `millwork.ui.__all__`, so
  `millwork reference` and `llms.txt` left it out.
- A `ui.Combobox` with `allow_custom=True` stopped filtering its options,
  so all of them stayed listed whatever was typed. The options filter as
  in any Combobox, and a last row, Use “…”, takes the text as typed.
  Typing the name of a disabled option and leaving the field no longer
  chooses it, and leaving the field after a choice no longer sends the
  choice a second time when the handler is slow to answer.
- `ui.Card(tone=)` drew nothing for `primary`, `success`, `warning` and
  `destructive`. The tone set a border color on a card that has no
  border. It now colors the card's edge.
- A click on a checkbox, a button or any other control inside a
  `ui.Card` with `on_click` also ran the card's handler. So did a choice
  from the menu of a `ui.FileCard` with `on_click`. A press on a control
  inside is now that control's alone. A drag is no click on the card,
  whether it selects text, moves a slider or a handle, or starts in a
  field and ends beside it.
- A `ui.Card`, a `ui.Image` and a `ui.FileCard` with `on_click` could not
  be reached by keyboard. They take focus, and Enter or Space clicks
  them.
- A checkbox, a switch or a radio button in a `ui.Floating` with
  `draggable=True` could not be clicked, and dragging a slider in one
  moved the panel.
- `s.ask` with a `ui.Form`, or anything else that is no dialog, drew it
  at the bottom of the page, out of sight on a long one, while the
  handler waited. A question that brings no `ui.Dialog` or `ui.Sheet` of
  its own is now shown in a dialog. A `ui.Sheet` given to `s.ask` stayed
  closed, and now opens. The Cancel button of a form given to `s.ask`
  did nothing, and now answers None.
- Stop did nothing on a `ui.Chat` that was disabled, which an app does
  while a reply runs, so the reply could not be stopped. Its thumbs and
  message actions did nothing either, and its suggestions, Edit and
  Regenerate could be pressed and did nothing. A disabled chat starts no
  reply, so those three are switched off. Its reply can still be stopped
  and rated, and a message's actions still run.
- The Cancel button of a `ui.Form` with `read_only=True` or
  `disabled=True` did nothing. Such a form takes no submit, and it can
  still be left.
- On Windows with Python 3.12, an `Auth(recheck_every=)` of 15 ms or
  less asked `recheck` a hundred times a second. An answer is kept for
  two steps of the clock at the least.
- In a test, `page.click` on a `ui.Checkbox` or a `ui.Switch` did nothing
  and the test passed. A click turns one with `checked` to its other
  value. One with `default_checked` keeps its value in the browser, so
  the click says to use `page.change` with the value.
- In a test, `page.upload` of a file that was refused never ran
  `on_reject`. A `ui.FileUpload` with `on_reject` is now told, with the
  reason a browser shows, before `upload` raises
  `millwork.files.Reject` as it did.

### Features

- `ui.Download` takes `size`, as a Button does, so it fits a row of small
  buttons.
- Enter picks the first match in a `ui.Combobox` with `options` and in a
  `ui.MultiSelect`. The first row is lit while typing. Before, Enter
  took a row only after moving to it. A MultiSelect lists what can still
  be added while there is text, so Enter never takes a chosen item away,
  and Enter with text in the field no longer submits the form around it.
- A test fails on an action the page does not take. `page.click`,
  `page.change`, `page.submit`, `page.send`, `page.upload` and
  `page.event` raise `LookupError` for a node that has no handler for
  the event, for one that is disabled or hidden, for a button that is
  loading, and for a submit of a read-only form. These used to log a
  line and pass, so a test could click something dead and assert on
  nothing. A test that did so on purpose now expects the error with
  `pytest.raises(LookupError)`.
- A test's uploads go by what the component allows, as a browser's do.
  `max_size_mb` and a chat's `accept` are checked, `page.upload` to a
  form refuses a `field` that is no file field, `page.send` with `files`
  to a chat without `attachments` is refused, and a `ui.FileUpload`
  without `on_upload` keeps the file and sends no event. A test that
  relied on one of these passing now gets `millwork.files.Reject`.
- A component's `icon` given as a file under `/public/` that is not in
  the public folder gets a development warning when its page is drawn.
  The page draws nothing in its place, which is easy to miss.

### The manual

- Deployment says what a tab does when a new version is put in place.
- Routes and middleware no longer calls `App` a Starlette application.
  What a server runs is `app.asgi`, and Testing shows a route tested on
  it.
- Tasks says what `await task` raises when the task was canceled, ran
  past its timeout or failed.
- Navigation says where a header's links go on a narrow screen.
- Feedback shows `s.ask` with a form and says where the question
  appears.
- Testing says what a refused upload does in a test, and what an action
  the page does not take does.
- Layout, Files and Inputs say what a clickable Card, Image and FileCard
  do with the keyboard and with a press on a control inside, and how a
  Combobox and a MultiSelect take typed text.
- Files says that a phone without a PDF viewer shows an empty frame.

## 0.3.0

### Bug fixes

- A click right after typing could reach Python before the text. A field
  holds a change for a moment so that typing is not a message per key,
  and a button pressed within that moment sent its click first, so the
  handler read what the field held before. What a field is holding now
  goes out ahead of anything else the tab sends: a click, a move to
  another page, an answer or an upload.
- Two events sent one right behind the other could be handled in the
  wrong order in an app with `Auth(recheck=)`. When the user was due to
  be checked again, the first event asked and waited for the answer, and
  the second found the answer there and went ahead of it. A click sent
  behind a change to a field then ran before the change. Events now pass
  one at a time, in the order they came in, on their way to their turn.
- On Windows with Python 3.12 a session in an app with `Auth(recheck=)`
  could keep the server busy for up to 16 ms each time its user was due
  to be checked again. The clock there moves in steps of that length, and
  the timer that asks was called a step before the answer in hand ran
  out. It found the answer good and set itself again, round and round
  until the clock moved on. An answer now counts as run out when less
  than a step of the clock is left of it.
- A `ui.Grid` inside a `ui.Grid` took the outer one's column counts for
  the widths it gave none for. A grid asking for four columns from `md`
  showed three on a wide screen, inside a grid that set three at `lg`.
- A chart with `format="integer"` repeated labels on its value axis for
  small counts, reading 0, 0, 0, 1, 1, 1. An axis whose labels show no
  decimals, counts and money, now steps by one at the least.
- `ui.Form` ignored `rows` in `overrides`, so a textarea in a form kept
  its default height.
- A handler made with `functools.partial` had its shape checked again on
  every render, where a function or a lambda is checked once. A page of
  three hundred such handlers took twice as long to build.
- The `icon` of a `ui.Option` was drawn by `ui.ToggleGroup` alone. A
  Select, a Combobox, a MultiSelect, a RadioGroup and a CheckboxGroup
  took it and showed nothing. It now stands in front of the option's
  label in each of them: in the list, in the closed field of a Select for
  the option that was chosen, and in the chips of a MultiSelect.

### Features

- `App(identify_visitors=True)` gives every browser an id, and
  `s.visitor.id` is that id in every session the browser opens, signed in
  or not. An app without sign-in had nothing to say whose a thing was
  once it was kept outside the session, where another tab can find it.
  It now saves the id with what it keeps and checks it when loading. The
  id comes from a signed, `HttpOnly` cookie named `mw_visitor` that the
  first page load sets and that lasts for the browser's session.
  millwork keeps nothing under the id, and an app that does not ask sets
  no cookie. A `secret` given to an app that asks is 32 characters or
  more, as with sign-in.
- The visitor and the user are separate. `s.user` is the person and
  `s.visitor` the browser, so an app with sign-in can log both. An id is
  good for one sign-in. The browser gets a new one when someone signs in,
  and again when they sign out or their sign-in ends, so nobody is the
  visitor the last person on that browser was.
- A route or a mount of the app's own finds the visitor in
  `request.state.visitor`, next to `request.state.user`, so a download
  link can check an owner the way a page does. It is `None` for a browser
  that brought no id, and for a request from another site's page that
  changes something.
- `TestApp.open(path, visitor="a")` opens a page from a browser with that
  visitor id. Two pages opened with the same one are two tabs of it.
- `mw.Visitor` is the type of `s.visitor`.

- An icon can be a file of the app's own. Every `icon` takes the path of
  a file under `public/`, such as `icon="/public/icons/rocket.svg"`, next
  to the names of the bundle's icons. An SVG is drawn in the color of the
  text around it, like the bundle's icons, so it follows the theme, a
  tone and dark mode, and a PNG, WebP or JPEG is drawn as it is. The path
  is checked when the component is made. It starts with `/public/`, holds
  no segment that starts with a dot, and ends in a kind of image, so one
  that comes from data cannot lead out of `/public/`. The file is the
  browser's to fetch, and is never read by the server or put into the
  page as markup.
- `ui.Icon(name)` places an icon on its own, with a `size`, a `tone` and
  a `label` for someone who cannot see it.
- `ui.Input` and `ui.Textarea` take `counter=True`, which shows under the
  field how many characters it holds, against `max_length` when there is
  one, and in the destructive color once the field is full. A text field
  of a `ui.Form` gets the same with `overrides={"/notes": {"counter":
  True}}`.
- `ui.lazy` makes a part of a page lazy, so that it is kept up to date
  only while its tab is open. It goes on a function that returns a
  component, and a call of it goes into a `ui.Tab`, as in
  `ui.Tab(history(s), id="history", label="History")`. The function runs
  when the page is first drawn and then at every render in which its tab
  is the open one. While another tab is open the part stays in the
  browser as it was when the tab was left, with what was typed into it,
  and a render skips it.
  A page of five tabs with sixty cards each renders in 1.9 ms that way,
  against 8.7 ms with every tab built. Before a handler in a closed
  tab's part is called the part is drawn again, so what is called is
  the page as it is now.
- In a test, `page.change(tabs, "history")` opens a tab of `ui.Tabs` by
  its id, whether the tabs keep their own choice or the page does. An id
  that is no tab, or a tab that is disabled, is refused.
- Drawing a page takes less of the server's time. Turning the components
  of a page into what is sent looked at every prop of every component,
  the ones nobody gave included, at full length. A prop that still holds
  what its class gives it is now passed on at a glance. A page of nine
  hundred components went from 9.3 ms to 4.5 ms for that part of a
  render, with the same result.

### The manual

- A new page, Visitors, on what the id is, how to pin what an app keeps
  to it, and what it is no good for. Sessions, App options, the Hosting
  checklist, Sign-out and cookies and Testing point to it.
- Layout has a section on lazy parts, with what they are for, what a
  lazy function may do and what does not belong in one.
- Sessions says what `s.connected` is, which was there and written down
  nowhere, and the reference lists it.
- Testing and Custom components say how a custom component is tested:
  its props are found as they were given, and its events are sent by
  name with `page.event`.

## 0.2.4

### Bug fixes

- The button of a `ui.Assistant` came back somewhere else after the window
  was opened and minimized without being touched. The window kept a place
  of its own, and it was pushed inside the screen when the button sat too
  high for it, so minimizing put the button at a corner it had never been
  in. The window now opens from where the button is every time and keeps
  only its size. Minimized, the button is where it was, and it moves to
  the window's near corner only once the window has been dragged or
  resized.
- A page function that raised before anything was shown left the tab on
  "Loading…" for good, after a toast, and one that raised after a
  navigation left the old page on screen under the new address with
  buttons that did nothing. Both now get a failure page in the frame of
  the not-found page, with a button that draws the page again. The page
  takes its place as soon as it renders, a reload tries it again, and in
  debug mode the exception is on the failure page. A test that opens such
  a page with `strict=False` finds the failure page and no toast in
  `page.errors`.
- `ui.Floating` with both `draggable=True` and `resizable=True` could not
  be resized, because a press on its edge did nothing. It resizes from
  the edges and is dragged from anywhere else.
- A `ui.Assistant` on a phone lost what was typed in it when its sheet was
  closed. The sheet keeps what it holds.
- The window of a `ui.Assistant` took its first size from the browser
  window as it was when the page loaded, so a page opened in a small
  window kept a small assistant after the browser was enlarged. The size
  is fitted when the window opens.
- Escape minimized every open `ui.Assistant` on the page, wherever the
  focus was, and also when a search field in the window used the key to
  clear itself. It minimizes the window that has the focus, when nothing
  inside had a use for the key.
- A `ui.Assistant` whose `open` is Python's, closed from Python after its
  window was dragged, left the button behind. The button follows the
  window however it is closed.
- `ui.Code(wrap=True)` did not wrap a long text without spaces.
- A clearable `ui.Input` lost the focus when its clear button was pressed.
- A password field showed two reveal buttons in Edge, the browser's and
  the field's. The browser's is hidden.
- A search field with `clearable=True` showed two clear buttons in
  Chromium browsers once it had focus. The browser's is hidden there.
- A password that is shown is no longer spellchecked. Shown, it is a text
  field to the browser, and a browser may send what it checks to a
  service.
- A text that is not a date in a table's `date` or `datetime` column, an
  empty one included, replaced the whole table with an error. It is shown
  as it came now, and an empty one is a dash.
- An empty text in a table column with the `code`, `badge` or `link`
  format drew an empty pill or nothing at all, and in a number format an
  empty cell. It is a dash now, as a missing value is, and so is a text
  of only spaces.
- `ui.Stat(trend=)` is typed to take any numbers, so a type checker
  accepts a `list[int]`.

### Features

- `ui.Assistant(pinned=True)` keeps the button in its corner. It cannot be
  dragged, and the window always opens from there and folds back to it.
  The window is still dragged and resized.
- `ui.Input` and `ui.Textarea` take `spellcheck`. `False` turns the
  browser's spellchecker off for text that is not prose, `True` keeps it
  on however long the text gets, and left alone it is on until the field
  holds more than 5,000 characters.
- 45 more icons, for 144 in all: activity, award, book-open, box,
  briefcase, bug, building-2, camera, cpu, credit-card, dollar-sign,
  file-code, flag, flask-conical, gauge, git-branch, globe, hard-drive,
  heart, layout-dashboard, layout-grid, lightbulb, line-chart,
  list-checks, log-in, map-pin, monitor, package, phone, pie-chart,
  rocket, rotate-ccw, server, shield, shield-check, shopping-cart,
  sliders-horizontal, target, timer, trending-down, trending-up, truck,
  undo-2, user-plus and wrench.
- `ui.Tone` is part of `millwork.ui` by name, for an app that keeps a
  table of tones. `millwork reference` lists it, and lists `p.log()`.
- Bundle packages updated: lucide-react 1.61 and Vite 8.3.5.

### The manual

- Sessions says that a session is one tab, and that what another tab or
  a later visit should find lives in storage the app brings.
- Tasks says that canceling stops a coroutine at once, and that `check()`
  is for work in a thread.
- Sessions says that a sheet or a dialog whose `open` is in the state is
  open again after a reload.
- Error pages describes the failure page.

## 0.2.3

### Bug fixes

- Pasting a long text into an input or a textarea froze the tab for
  seconds, or for good. The browser's spellchecker marks every word of a
  change, and its cost grows faster than the text. A text field now turns
  spellchecking off once it holds more than 5,000 characters and back on
  when it shrinks below that, so a long paste lands at once. A `Textarea`
  also no longer grows past the viewport: it follows `rows` unless
  `autosize=True`, and then stops at most of the window's height and
  scrolls inside.

### Features

- `ui.Input` takes `max_length`, as `ui.Textarea` does, to cap what can be
  typed or pasted into it.
- `ui.Assistant` is a round button in a corner of the page that becomes a
  window, for a chat that should be at hand on every page. The window
  grows from the button's corner, gives its child its height, is dragged
  by its header and resized from any edge, and folds back into the button
  when minimized. The browser remembers where both are, and on a phone the
  window is a sheet. `ui.Floating` is the plain form: children pinned in a
  corner, draggable and resizable when asked, never past the edge of the
  browser window.

## 0.2.2

### Features

- `ui.SidebarGroup` folds a set of sidebar links under a label. It opens
  and closes in the browser unless `open` is given, in which case
  `on_toggle` reports the click. `collapsible=False` makes it a plain
  heading over its links.
- A link in `ui.Markdown` to a path of the app opens that page on the
  session, as `ui.Link` does. A link to anywhere else opens a new tab, as
  before.

### The manual

- The App chapters are gone, and in their place are short pages in
  groups: Pages, State, Sign-in and Running, with Theming and Testing on
  their own and a Quickstart next to the Welcome. Each page ends with the
  next one in its group and cards to the pages that relate to it. The
  sidebar folds each group to its label, with the one you are in open.
  The old addresses redirect.

### Bug fixes

- A page that uses a class the precompiled stylesheet does not have, through
  `cls` or a custom component, waited for nothing and painted before the
  runtime compiler had styled it, then jumped into place. The first such
  page now waits for the compiler, which is a moment on a fresh tab and
  nothing after.
- A page with Markdown on it painted the Markdown's source first, in a
  monospace block, and then the rendered text once the renderer's chunk
  had arrived, which moved everything below it. The first such page now
  waits for the chunk, as it does for the runtime compiler, and draws
  once. A theme's self-hosted fonts are preloaded from the page's head,
  so the text is drawn in them from the first paint.
- A page opened over the session kept the scroll position of the page
  before it, so a reader halfway down one chapter landed halfway down the
  next. A new page opens at the top. The back and forward buttons return to
  where the reader was on that page.
- Two examples in the manual, the navigation row and the chat buttons, ran
  past their panel on a phone. They wrap now, and an example wider than its
  panel scrolls inside it instead of floating over the border.
- A chart example in the manual labeled its series after an app the reader
  has never seen.

## 0.2.1

- The `public` and `components` folders, and a theme given by path, are
  found next to the file that calls `App(...)`, wherever the server is
  started from. Before, they were looked up from the working directory,
  so `millwork run pond/app.py` from one folder up silently lost the
  theme and the custom components. A folder the app names that does not
  exist is now said in the log at startup. A `components` folder next to
  the app file is served from now on, where before only one in the
  working directory was. Code with no file, a notebook cell or the REPL,
  keeps working from the working directory, and an app made by a helper
  in another module finds the folders next to that module, so a helper
  passes absolute paths.
- `cls` and `hidden` on `ui.Custom` are applied around the component, as
  for every other component. Before, they arrived among the component's
  own props and it had to apply them itself, and a component that still
  reads `props.cls` finds nothing there now. A custom prop named `key`,
  `cls`, `hidden` or `on_event` is refused, since it would collide with
  the component's own.
- `ui.Progress(percent=False)` draws a plain meter, without the value
  written out next to the bar.
- In tests, `page.notices` lists every toast with its tone and title,
  where `page.toasts` gives the messages alone.
- A password field has a button that shows what was typed: on
  `ui.Input(kind="password")`, on a form's password field and on the
  sign-in page. Its label comes from the theme's new `show_password`
  string.
- The value axis of a line or area chart now sits where the data is,
  rounded out to its ticks, where before it started at zero. `y_range=(low,
  high)` pins either end, with `None` for one that follows the data, for
  when zero should stay in view. Every chart's axis now has its ticks at
  round steps (10, 20, 30), where they could read 13, 26, 39 before. Bars
  keep their zero baseline.

## 0.2.0

- A page, a route or a mount takes `allow=`, a rule about the signed-in
  user that says who may open it. A rule is a plain function of the user
  and of the path parameters it names. millwork asks it on a page load,
  when a tab connects or comes back, on navigation and for a route, so a
  page cannot be reached around it, and a refused page never runs its
  `connect` hook. `s.can(path)` asks the same rule for a link, and
  `millwork routes app.py` lists who may reach what. Before, the only way
  to keep a page to some users was to raise `mw.Forbidden` in `connect`,
  and a page that forgot to was open to everyone signed in.
- Breaking: in an app with auth, `app.route` and `app.mount` now need a
  sign-in, and a request that changes something must come from the app's
  own origin. Before, they were open to anyone, signed out included. A
  webhook or a health check has to be marked `public=True`. The endpoint
  finds the user in `request.state.user`.
- `Auth(recheck=)` keeps a signed-in user current. The hook returns who
  the person is now, or `None` to end the sign-in, and is asked at most
  once per `recheck_every`, five minutes by default, for page loads,
  routes and open sessions alike. A session whose user changed ends, and
  its tab loads the page again as the person they are now. Before, a
  person kept what their cookie said until it expired.
- A session is resumed after a dropped connection only by the same user,
  unchanged. Before, the same id was enough, so behind a proxy a session
  could come back with the user it started with after `on_login` had
  made them someone else.
- A page is found by its path as the browser spelled it, without what
  follows a `?` or a `#` and decoded once, on a page load and in the tab
  alike. Before, a path the tab sent kept its query in the last parameter
  and its percent-encoding, where a page load had neither, so the two
  could disagree about a parameter.
- A session no longer waits on a socket for anything. What it has to say
  is kept in order and carried to the tab by its connection, so a tab
  that reads slowly holds up its own messages and nothing else. Before,
  one tab that had stopped reading could keep its session open, hold up
  the sessions ended after it, and stall a theme or a component pushed to
  every tab. A tab that is not reading when its session ends holds
  nothing of it after two seconds, and starts a new session when it comes
  back.
- A session that is over runs nothing more. Work started on it after the
  end is cancelled at once, a task the end cancelled does not come back
  through its `on_done`, and nothing after `await s.end(...)` runs in a
  handler or a task of that session, which before went on to its next
  `await`. A handler that waits on a task when its session ends is
  cancelled with it. Before, it was handed `mw.Cancelled` and could go on.
- A page is closed exactly once, by its session and by nothing else. Its
  close hook runs to its end whatever becomes of the handler or
  navigation that was leaving the page, may end the session it is
  closing, and is stopped after thirty seconds, so one that never returns
  cannot keep the server from stopping. A `connect` that is still running
  when its session ends is stopped where it stands, and a `connect` that
  did not return is not followed by a close.
- A page is drawn when its `connect` has returned, also when the hook
  waits on a task. Before, such a page was drawn while it was still
  connecting, and two navigations in a row could connect side by side
  and leave a page that was never closed.
- A request or a chat message cancelled in the moment it arrives is
  forgotten. Before, the request stayed on the session's books, an upload
  behind it could block everything else its tab sent, and the chat stayed
  busy for good.
- Cancelling a task stops it. A task started with `s.later` that had
  already begun was marked cancelled while its work ran on, and a task
  cancelled in the moment it was started stayed running, with whatever
  awaited it waiting for good.
- A tab that reconnects or is loaded again in the middle of a long
  handler gets the page as it was last drawn, at once. Before, the page
  was built anew at that moment, from state the handler had half changed.
- Making room for a new session, and signing out, no longer wait for the
  close hook of the sessions they end. `await session.end(...)` from
  outside the session returns as soon as the session is over, and
  `session.gone` is there to wait on for its page to be closed.
  `s.spawn` returns `None` on a session that is over.
- When the server stops, nothing of a session is left running. Before, a
  `recheck` or an `on_logout` that was being asked went on after it.
- Smaller changes in how a session behaves. What a session said just
  before it ended, and its tab had not yet taken, is not sent, so a toast
  right before `s.end` is not seen. A render whose timer fires while a
  handler holds the turn is drawn as the turn comes free, ahead of the
  handlers waiting in line, where it waited in line with them. A tab that
  has fallen further behind than the session keeps for replay gets the
  page mounted anew. An event that was waiting its turn behind a
  navigation is dropped when it was meant for the page that was left.
  `s.ask` and `s.confirm` answer `None` and `False` at once from a connect
  or a close hook, or on a session that is over, where a question asked
  in a first connect waited for good. `await s.navigate_to(...)` works
  from a handler, which lends its turn, where it waited for its own turn
  before, and returns at once from a connect or a close hook, which the
  session follows once the hook has returned.
- Something an app mounts sees the app's own sign-in. Before, the cookie
  was looked up under a name that included the mount's path, so
  `app.user_for` found nobody there.
- More of the framework's own words come from the theme's strings. A
  table's row count, which read "1 rows", the upload box, the chat's
  placeholder and a union field's "Type" were English whatever the theme
  said. So were the default labels of a form's submit button, a
  `ui.Download` and a pie chart's folded slice, which now follow `save`,
  `download` and `other` until the app sets its own.
- What is wrong with a form field is said in the theme's words, the new
  strings that start with `issue_`, where it was pydantic's English
  sentence. A validator of the model's own is shown with the words it
  raised, without "Value error," in front. An empty field reads as
  required whatever limit it has.
- Why an upload was refused is said in the theme's words, the new strings
  that start with `file_`. A file of a type that is not accepted is told
  "this type of file is not accepted", where the sentence used to start
  with the file's extension.
- `ui.Button(href=)` makes a button that goes somewhere. A page of the
  app opens on the session, and since the button is a real link it opens
  in a new tab on a middle click.
- A `ui.Link` in a `ui.Sidebar` is drawn as a row to press, with its icon
  and the active page set apart. Before, it looked like a link in running
  text and every app styled it with classes of its own. Classes an app
  passes still win.
- `s.print()` opens the browser's print dialog once the page has been
  drawn again, and in print a heading stays with what follows it. There
  is a `printer` icon.
- Where a path fits several pages, the one that is exact soonest wins.
  A literal segment comes before a parameter, so `/orders/new` is found
  next to `/orders/{id}` in either order, a parameter with a converter
  comes before a bare one, and `{rest:path}` comes last. Before, the page
  added first won, so an app that relied on that order for two pages of
  different exactness now gets the more exact one.
- Testing: `page.find` and `page.find_all` take props as keywords,
  `page.find(ui.Button, label="Delete")`, and `page.click` on a link or
  a button with an `href` takes the session to that page.
- A page prints in full. The shell is a viewport-high column whose body
  scrolls, so printing gave one sheet and cut the rest. In print the
  column and its scrolling boxes now run as long as their content, the
  sidebar and header are left out, and a dark page prints light.
- A theme takes a `stylesheet`, the path of a CSS file under `/public/`
  that loads after the theme, for rules the tokens cannot express.
- A dropdown menu grows to fit its longest item. Before, it was as wide
  as its trigger, so long items needed a wide button.
- `ui.Alert` shows its children under the description. Before, they were
  dropped.
- The buttons of `Button(confirm=)`, a menu item's `confirm` and
  `s.confirm` come from the theme's strings, `ok` and `cancel`. Before,
  they said "OK" and "Cancel" whatever the theme. The labels for screen
  readers on a dialog's close button, a toast, the spinner and the
  sidebar toggle follow the theme too, with the new strings `close` and
  `toggle_sidebar`.
- Testing: `page.find` and `page.find_all` take `within=` to look inside
  one node, a component type finds its subclasses, so `ui.Custom` finds
  custom components, and `page.choose(menu, item)` picks an item of a
  dropdown menu.
- A session ends when the sign-in it runs on expires. Its tab leaves for
  the login page and comes back to its page after a new sign-in, and a
  tab on a public page reloads for a visitor. Before, the lifetime set by
  `Auth(session=)` was checked only when a page loaded or a socket
  connected, so a tab left open kept working past it until its
  connection dropped.
- `Auth(on_logout=)` decides where a person goes when they sign out or
  their sign-in expires under an open tab. The hook gets the `User` and
  returns a path on the app or a URL, and `None` keeps the login page.
  Before, sign-out always landed on the login page.
- The sign-out route answers the app's own pages only. Before, it
  answered a request from any site.
- The login page can be laid out by the app. `Auth(login=)` takes
  components, with a `ui.SignIn(provider_id)` where each way in goes, so
  a heading, a note or a line with "or" sits wherever it is wanted, and
  the ways in come in the app's order. Left alone, the page now draws a
  line between the provider buttons and the password form, whose word is
  the new interface string `or`, for a theme that sets its own strings.
  `ui.SignIn` works on a public page too.
- The Microsoft and Google buttons show their brand's mark.
  `auth.OAuth(icon=)` takes `microsoft`, `google`, the path of an image
  under `public/`, or an icon name, and an icon the bundle does not have
  is now refused when the app starts.
- A link is underlined, faintly, and the line firms up under the pointer.
  Under the default theme the primary color is the color of the text, so
  a link in Markdown, a `ui.Link`, a link cell in a table and a file
  card's link looked like the words around them. Links in a sidebar and
  in the header stay plain.
- A card's footer sits at the bottom of the card. In a grid, a card with
  less in it than its neighbor left its footer floating under the content
  with empty card below it.

## 0.1.7

- A theme's `font-sans` and `font-heading` tokens had no effect. The
  stylesheet carried the default font as a fixed value where it should
  have read the token, so only `font-mono` could be set. Both are read
  now, and `font-heading` is the font of headings and of the titles of
  cards, dialogs, sheets and the header.
- A dialog is never taller than the window, and its body scrolls when
  what it holds is taller or wider. Before, a wide table or a long line
  ran out of the side of the dialog, and tall content ran off the screen
  with no way to reach it. A sheet wraps a long word the same way.
- Large tables are quick to change. A render used to convert every cell
  of every table on the page one by one, 250 ms for ten thousand rows on
  each click anywhere on the page, and that is now one pass of about
  35 ms. A change sent the whole table again, and now sends the
  rows that changed. The tab drew every row again, and now draws the ones
  that changed. A table longer than two hundred rows draws the rows in
  view, so ten thousand rows open in under a second where they took
  eight.
- A table's header stays at the top of the table's own box, the one
  `height` gives it. `sticky_header` never took effect before.
  `ui.Column(wrap=True)` wraps, which it did not, and a row may be a
  dataclass, as the manual already said.
- A page's `close` hook is no longer cut off at its first `await` when a
  handler or a task ends its own session with `s.end()`. When the server
  stops, pages close before the `on_shutdown` hooks run, so a close hook
  still has the database those hooks close. In a strict test, a close
  hook that raises fails the test.
- `Session.close()` is gone from the public surface. Called from a
  handler it ended the session without telling the tab, which then sat
  there doing nothing. `s.end(message)` is the way to end a session, and
  the manual now says plainly that a closed tab ends its session after
  the grace period, not at once.
- The wire protocol is version 4, for the op that carries the changed
  items of a list. A tab left open across the upgrade reloads itself.
- `ui.Grid(cols={...})` takes `xl` next to `sm`, `md` and `lg`, refuses a
  width it does not know where it dropped one in silence, and draws any
  count from 1 to 12, where a count without a class of its own fell back
  to two columns. `sm` is the count on the narrowest screens, as before,
  and the manual now says so.
- `ui.Sheet` has a `size`, on the Dialog's scale. A width given through
  `cls` lost to the sheet's own.
- A chat command is a message without any text, so a command that takes
  no words can be sent from its chip. The message shows the command it
  was sent under. In a test, `page.send(chat, command="...")`.
- The reference says what a table's `tones` functions are called with and
  what `page.stream` holds, and the manual puts the five series limit next
  to `by`.
- Working on millwork needs uv 0.12.6 or newer. An older uv could not
  install the project under its own `no-build` setting, and is now told to
  update. Installing millwork from PyPI is not affected.

## 0.1.6

- The typed signatures a checker sees lost every positional parameter the
  runtime takes, so `ui.Form(Model)` and `ui.BarChart(rows)` failed to
  type-check, and `ui.Select(options=["a"])` was refused since the stub
  named what the field holds, not what the call accepts. The generator now
  finds the runtime's `__init__` where it lives and the one a chart
  inherits, and says what a validator accepts.
- `ui.Text` refuses a `variant`, `tone` or `align` it does not have, as
  Badge and Button already did; before, an unknown one rendered as body
  text.
- A destructive menu item no longer asks before its handler runs. Whether
  an action can be undone is the app's knowledge, so `confirm="..."` is
  what asks, in the dialog's destructive style when the item is
  destructive. The same holds for a table's row actions and a file card's
  actions.
- `ui.Link(active=True)` marks the link to the page the session is on, as
  `aria-current="page"`, and the manual's sidebar uses it.
- The reference says what each handler's payload is, and has sections on
  tasks and `mw.progress()`, forms and `ui.FormIssues`, path parameters
  and `mw.NotFound`, and `TestApp`. Session, task, app and harness methods
  that had no docstring have one.
- In a test, `page.click` on a `Download` starts the download, and
  `page.text()` leaves out props that pick from a fixed set, a variant or
  an alignment, so a check for a word on the page is not fooled by one.

## 0.1.5

- Dependencies wait two weeks. uv and pnpm resolve only versions that have
  been on their index for fourteen days, Dependabot proposes a bump on the
  same schedule, and a Python dependency is installed from a wheel, never
  built from a source distribution.
- The bundle's type check in CI checked nothing, since it ran against the
  solution-style tsconfig; it now runs the build's check.
- The State chapter says a session is one tab, shows a task that follows
  changes made elsewhere, and the reference describes the session's state
  as kept across pages.
- `TestApp`'s `settle()` no longer waits for a quiet task, the kind that
  waits for a change made elsewhere, and gives up after ten seconds
  naming what still runs instead of after a hundred. `page.toast_action
  ("Undo")` presses a toast's button.
- A table cell's tone colors the cell for every format, and a badge wears
  `success` and `warning` in color. Before, a cell tone reached only
  badges, as an outline.
- `ui.Header` is in the reference, and its links reach a narrow screen
  through the menu.
- `ui.Progress(task=)` shows a canceled task as canceled instead of
  freezing at its last value.
- `--debug` no longer turns on uvicorn's frame-level log, which buried
  millwork's own warnings, and reaches the server `--reload` starts, which
  had no log of its own before.
- A task that fails and that no handler awaits is reported like a handler
  that raised, so a strict `TestApp` raises it in the test.
- The "changed nothing" warning says what it checks: nothing the page
  shows changed.

## 0.1.4

- One state per session. The app declares the model, `s.state` is the
  session's instance of it, and it stays as the tab moves between pages,
  so a value one page set is there for the next. `@app.page(state=)` is
  gone, and a page's `close` hook runs when the session leaves the page
  as well as when it ends. The State chapter shows how a bigger app
  splits the model into a slice per feature, and how a page renders
  components it cannot count.
- The manual's examples read `s.state.<model>` as an app would. The
  manual composes its state from the models the examples define.
- An unknown icon name fails in Python, with the closest names in the
  error, instead of a warning in the browser console. The set is
  `mw.ICONS`.
- `ui.Page(title=)` names the browser tab, and a title that changes
  between renders follows.
- `ui.NumberInput` reports on Enter as the manual said.
- A `ui.MenuItem` asks before a destructive action wherever it is, in a
  `DropdownMenu` too, and `confirm="..."` gives it the question's words.
- A form opens with the value a field's `default_factory` makes.
- A state model may hold a task as `mw.Task | None`.
- `page.find("key")` in a test finds a keyed component in a slot such as a
  card's footer.
- The built-in not-found page draws its home icon again.
- Every component carries a typed signature for mypy and pyright, so
  positional children pass and a wrong prop or value shows in the editor.
- `TestApp` raises in the test what a page function, handler or hook
  raised, with a note saying where; `strict=False` keeps the old way.
- A handler that cannot take `(session, payload)` is refused when the page
  is built, with the expected shape in the error.
- `ui.Page` lays its children out with a `gap`, six by default.
- `Theme(currency=)` names the currency the `currency` format uses, and
  number and date formats follow the theme's locale as the manual said.
- `millwork reference` prints the catalog as a Markdown lookup table, and
  the manual serves it at `/llms.txt`.
- A chart's `colors={"name": slot}` fixes a series, or a pie's slice, to
  one of the five chart colors, so two charts over the same categories
  agree. A named slot stays reserved while its series is filtered away,
  and the rest take the free slots in order.
- The README has a whole page, the manual lists the form widgets, says
  where an upload's bytes are, and that a `Stat` is a card of its own.

## 0.1.3

- A `ui.Progress` draws one bar again. The progress primitive had started
  drawing a second track of its own.
- The hosted manual is deployed from the release's own wheel, so a deploy
  no longer waits on PyPI's index.
- A security policy, in `SECURITY.md`.
- `ui.PieChart`, one slice per row, with the smallest folding into one
  gray slice past five, a donut with a figure in the middle, share labels
  and a click per slice.

## 0.1.2

- Fix the automatic docs release.
- Improve docs prose and sentences.

## 0.1.1

- What can be pressed shows it: buttons, toggles, table rows, file cards
  and badges take the theme's `accent` tint under the pointer, buttons get
  the pointer cursor and a pressed shade, and a toggle that is on carries
  the primary color. Under a theme whose `muted` is close to white, the
  composer's buttons and command chips had shown nothing.
- The manual is hosted at millwork-ui.com, deployed from PyPI by each
  release; its examples take uploads under a small quota.
- Bundle packages updated: cn 0.5, lucide-react 1.59, React 19.3.1,
  recharts 3.10.1.

## 0.1.0

The first release on PyPI.

- A catalog of components on shadcn/ui: layout, text, inputs, feedback,
  tables, charts, forms from Pydantic models, files, tasks with progress,
  and a chat surface that streams replies from Python.
- One model of state: Python owns it, a page is a function of it, and the
  browser receives patches.
- Files, uploads and downloads over the session's socket, so replicas need
  no sticky routing and no shared storage.
- Sign-in with password, OAuth and proxy-header providers behind one
  `on_login` hook; a theme file in the shadcn token vocabulary.
- A test harness that drives a page without a browser.
- `millwork run` serves an app on a port or a unix socket, behind a proxy
  and under a path prefix; `millwork docs` serves the manual, whose every
  example runs.
