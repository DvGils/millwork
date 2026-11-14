# Contributing to millwork

millwork is in beta and has one maintainer. Bug reports, fixes and
improvements to the manual are welcome. This page says how to send them
and what a change has to pass.

## Before writing code

A bug with a way to reproduce it is the most useful thing to send, and it
goes in an issue. The smallest app that shows it, the millwork version and
what you expected are enough. A fix for a bug can come straight as a pull
request.

Anything that adds to what an app can write, a component, a prop or a
session method, starts as an issue. Describe the page you are trying to
build and where millwork gets in the way. millwork stays small on
purpose, and a feature earns its place by the apps that need it, so
talking first saves writing code that will not be merged.

A vulnerability is never reported in an issue.
[SECURITY.md](https://github.com/DvGils/millwork/blob/main/SECURITY.md)
says where it goes.

## Setup

millwork needs Python 3.12 or newer and uv 0.12.6 or newer. Node 24 and
pnpm 12 are needed only to change the bundle under `bundle/`. Every
checkout runs without them, since the built bundle is committed.

```
git clone https://github.com/DvGils/millwork
cd millwork
uv sync
uv run millwork docs
```

The last command serves the manual on port 8008. Its pages are live
examples of every component, which makes it the place to see what a
change does.

## The checks

CI runs these on every pull request, on every released Python from 3.12
up on Linux and on the oldest and the newest of them on Windows and macOS.
It runs the tests once more with the oldest version of each dependency
that `pyproject.toml` allows. Run them before you push.

```
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run mypy src
uv run pytest -q
```

A change under `bundle/` has four more.

```
pnpm -C bundle install --frozen-lockfile
pnpm -C bundle exec tsc -b
CI=1 pnpm -C bundle exec vitest run
CI=1 pnpm -C bundle build
```

## What a change comes with

- **A test.** A fix comes with a test that fails without it. The suite
  drives real sessions through `millwork.testing.TestApp`, and the tests
  next to the code you touch show how.
- **The rebuilt bundle.** A change to `bundle/` is committed together with
  the `src/millwork/_bundle/dist` the build writes. CI builds the bundle
  again and refuses a branch whose committed copy differs.
- **The typed signatures.** After a change to a component's fields, run
  `uv run python scripts/typed_inits.py`. It rewrites the signature under
  each class that mypy and pyright read, and a test checks that it was
  run.
- **The manual.** A new component or prop gets a live example in a page
  under `src/millwork/manual/pages`. A test checks that every component
  has one. The manual says what a thing is and shows it working, in plain
  American English.
- **A deprecation, for a spelling that changes.** The old spelling keeps
  working for at least one minor release and warns.
  `src/millwork/deprecation.py` has the pieces. A component's renamed
  keyword goes in its `old_names` with a `Renamed`, written out as a
  literal, since the typed signatures are read off the source. A call with
  the old name then works and warns. So does an app's subclass whose
  `__init__` was written to the old name. The typed signatures take both
  names, and while they do the checker cannot insist on a required one.
  That covers the keyword in a call. The attribute on an instance and the
  prop a test reads go by the new name at once, and a subclass that
  declares a field under the old name is warned that it is a separate
  field now, so the changelog says so. Anything else declares a
  `Deprecation` at module level and calls its `warn()` where the old
  spelling is used. What is noticed while no code of the app runs passes
  what it is about, a handler for one, as `at=`. Every declaration names
  the release that starts warning and the release that drops the spelling,
  and a test fails once the version in `pyproject.toml` reaches the second
  while the old spelling is still in the code.
- **A changelog entry.** Anything a user of millwork would notice gets a
  line under the next version in `CHANGELOG.md`, saying what changed and
  what it did before.

A change to the look of the bundle is judged against the manual. Open the
pages it touches and look at them before and after.

## Dependencies

Dependencies wait two weeks. `tool.uv` in `pyproject.toml` and the
bundle's `pnpm-workspace.yaml` resolve only versions that have been on
their index for fourteen days, and Dependabot proposes a bump on the same
schedule. A dependency is installed from a wheel and never built from
source. A pull request that adds a dependency says why the standard
library or what is already there will not do, because the short list is
part of what millwork is.

A Dependabot bump of the bundle's packages is applied like any bundle
change. Rebuild, look at the manual, and commit the `dist` with it.

Before a release the lockfiles are checked for known vulnerabilities by
hand, on top of Dependabot's alerts.

```
uv export --format requirements-txt --no-emit-project -q -o requirements.txt
uvx pip-audit -r requirements.txt --no-deps
pnpm -C bundle audit
```

## Pull requests

Branch from `main` and keep a pull request to one topic. A commit message
says what changed in a sentence, and the body says why when the diff does
not. The maintainer merges, and releases are cut from a tag.

## The README's GIF

The GIF in the README comes from `.github/readme/demo.py`, an app of a
hundred lines, and `.github/readme/record.py` drives it in a headless
browser to record it. Run the recorder after a change to the look, so
what the README shows is what the code does.

## License

millwork is licensed under Apache-2.0, and a contribution is made under
the same license.
