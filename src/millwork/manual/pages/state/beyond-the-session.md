---
title: Beyond the session
order: 4
description: Where to keep what a second tab, a saved link or tomorrow should still find.
related: /pages/sessions, /pages/path-parameters
---

# Beyond the session

State belongs to one session, and a session is one tab. This page is about
what has to be found from somewhere else, such as a second tab, a link
someone saved, or the same person tomorrow.

## What a session does not cover

A reload gets the same session back, as long as it happens within the
grace period. A second tab does not. It is a new session with a fresh
state, and it cannot read anything the first tab holds. The same goes for
a link that is opened after the first tab has been gone longer than the
grace period.

So a page with an address of its own, say a report at
`/report/{report_id}`, cannot keep the report in `s.state`. The session
that made the report is not always the session that opens it.

## Keeping it in the process

The simplest place is a plain object in the module. Every session of the
process reads the same one.

```python
import secrets
from collections import OrderedDict

import millwork as mw
from millwork import ui

KEEP = 50
REPORTS: OrderedDict[str, Report] = OrderedDict()


def keep(report: Report) -> str:
    report_id = secrets.token_urlsafe(16)
    REPORTS[report_id] = report
    while len(REPORTS) > KEEP:
        REPORTS.popitem(last=False)
    return report_id


async def finished(s, task):
    s.navigate(f"/report/{keep(task.result)}")


@app.page("/report/{report_id}")
def show(s):
    report = REPORTS[s.params["report_id"]]
    return ui.Page(ui.Text(report.title, variant="heading"))


@show.connect
def find(s, report_id: str):
    if report_id not in REPORTS:
        raise mw.NotFound("That report is no longer kept.")
```

Three things in it matter.

- The dictionary has a bound. The end of a session clears its state, and
  nothing clears a module's data, so the app removes what it added.
- The id is long and random, because anyone who has the address opens the
  report. In an app with sign-in, keep the owner beside the report and
  compare it with `s.user.id` in the connect hook.
- The connect hook answers a missing id with the not-found page before
  the page function runs.

## What the process does not cover

A restart empties the module's data, and every deploy is a restart. With
more than one replica, each has its own copy, and a link can land on a
replica that never saw the report.

What has to outlast those lives in a store of the app's own, such as a
database, a bucket, or files on a disk the replicas share. The shape stays
the same. The handler writes to the store, and the connect hook reads from
it and puts what it found in the state for the page.

```python
@show.connect
async def find(s, report_id: str):
    report = await store.load(report_id)
    if report is None:
        raise mw.NotFound("That report is no longer kept.")
    s.state.report = report
```

## Files

A session's files end with it as well, both uploads and what
`s.files.add` made. A file that should be there later is kept by the app
in the same store as the rest. A session that needs it calls
`s.files.add(path, name="report.pdf")`, which makes a copy that belongs to
that session and gives back the `FileRef` a `Download` or an `Image`
takes.
