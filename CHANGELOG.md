# Changelog

Notable changes to millwork. Before 1.0 the API may move between minor
versions; a release says so here when it does.

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
