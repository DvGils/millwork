---
title: Framework warnings
order: 4
description: Seven mistakes millwork can see, and how it tells you.
related: /running/development, /components/tasks
---

# Framework warnings
<!-- keywords: debug, slow, performance, lint, console, log -->

Some mistakes the framework can see, and it says so once per session, as a
log line with the page's path, and in debug mode as a toast as well.

- **A slow page function**, over 20 ms, the time in its
  [lazy parts](/components/layout#lazy-parts) included. The page function
  builds the tree, and I/O belongs in the page's `connect` hook or a task.
  A page that is slow for its size alone, a thousand rows built one by
  one, shows fewer of them at a time. Where the size is in tabs, `ui.lazy`
  leaves the ones that are not open out of a render.
- **A slow handler**, one that kept its turn for over 250 ms. The page is
  not drawn while a handler runs, so the person sees nothing of what it
  set until it is done. A handler that does not `await` in that time, one
  that reads a file or calls a slow library, also keeps every other
  session waiting. The time a handler waits on a task, on a question or
  on another page does not count, since the page is drawn then. Work that
  takes time goes in a [task](/components/tasks) that the handler itself
  awaits, and `await s.task(work)` gives it the result.
- **A list without keys**, meaning four or more siblings of one type
  without a key whose number changed between renders. Children that are
  written out, one of them left out with `x if shown else None`, are no
  such list, since their places stay where they are.
- **An icon file that is not there**, a component's `icon` given as a
  path under `/public/` whose file is not in the public folder. The
  page draws nothing in its place, which is easy to miss.
- **A progress bar past its end**, a `ui.Progress` whose `value` is
  above 1. The value is a share from 0 to 1, and a percentage such as 50
  is drawn as a full bar.
- **A handler that changed nothing**, no state, no command, no task.
  Usually a forgotten `await`. It is said of a press, which is a click, a
  submit, a row or card action, a click on a table's row and a choice
  from a menu. Other events tell of what the tab shows already, such as
  a value typed or rows ticked, so a handler that only keeps that is not
  warned about. Neither is an event a custom component emits.
- **A sync task that changed state from its thread.** A task reports
  through `progress()` and returns a result, and the handler that awaits it
  puts the result in state, as the [Tasks](/components/tasks) page shows.

Debug mode is `--debug` on `millwork run`, as [Development](/running/development)
describes, and [Sessions](/pages/sessions) has the `connect` hook.
