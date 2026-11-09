---
title: Framework warnings
order: 5
description: Four mistakes millwork can see, and how it tells you.
related: /running/development, /components/tasks
---

# Framework warnings

Some mistakes the framework can see, and it says so once per session, as a
log line with the page's path, and in debug mode as a toast as well.

- **A slow page function**, over 20 ms. The page function builds the tree,
  and I/O belongs in the page's `connect` hook or a task.
- **A list without keys**, meaning four or more siblings of one type
  without a key whose number changed between renders.
- **A handler that changed nothing**, no state, no command, no task.
  Usually a forgotten `await`.
- **A sync task that changed state from its thread.** A task reports
  through `progress()` and returns a result, and the handler that awaits it
  puts the result in state, as the [Tasks](/components/tasks) page shows.

Debug mode is `--debug` on `millwork run`, as [Development](/running/development)
describes, and [Sessions](/pages/sessions) has the `connect` hook.
