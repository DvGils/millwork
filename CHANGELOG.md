# Changelog

Notable changes to millwork. Before 1.0 the API may move between minor
versions; a release says so here when it does.

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
