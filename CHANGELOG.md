# Changelog

Notable changes to millwork. Before 1.0 the API may move between minor
versions; a release says so here when it does.

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
