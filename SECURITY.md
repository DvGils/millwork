# Security policy

## Reporting a vulnerability

Report a vulnerability privately through GitHub's
[private vulnerability reporting](https://github.com/DvGils/millwork/security/advisories/new),
not as a public issue. A report is acknowledged within five working days.
It is then investigated, fixed in a release, and disclosed with credit to
the reporter once the fix is out.

## Supported versions

Only the latest release receives security fixes. Before 1.0 a release may
move the API, so a fix can arrive with other changes; the changelog says
what moved. Upgrade with `uv add millwork` or `pip install -U millwork`.

## What counts

millwork is a framework. A report concerns it when the framework itself
lets a visitor do what the app did not allow: read another session's
state, files or chat; act as another user; escape the session caps, the
upload quotas or the message bounds; run script the page's security policy
should block; or reach the process's filesystem or environment through a
route the framework serves. A weakness in an app built on millwork, in a
custom component an app wrote, or in a provider the app configured, is
the app's to fix, though a report that the framework made the mistake
easy is welcome.

## What the framework does on its own account

The Running and Signing in chapters of the manual describe the behaviour a
report can hold the framework to: the session cookie and its signing, the
origin checks on the socket and the login route, the content security
policy on every page, the handling of forwarded headers behind a proxy,
the bounds on sessions, uploads, socket messages and chat threads, and
what a proxied process trusts.
