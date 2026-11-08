---
title: What the framework notices
order: 4
description: The mistakes millwork can see and says so, once per session.
related: /running/development, /components/tasks
---

# What the framework notices

Some mistakes the framework can see, and it says so once per session, as a
log line with the page's path, and in debug mode as a toast as well.

- **A slow page function**, over 20 ms. The page function builds the tree,
  and I/O belongs in `connect` or a task.
- **A list without keys**, meaning four or more siblings of one type
  without a key whose number changed between renders.
- **A handler that changed nothing**, no state, no command, no task.
  Usually a forgotten `await`.
- **A sync task that changed state from its thread.** A task reports
  through `progress()` and returns a result, and the handler that awaits it
  puts the result in state.

[Development](/running/development) says how to turn debug mode on.
