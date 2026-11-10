---
title: Visitors
order: 5
description: An id for the browser behind a session, so an app without sign-in can say whose something is.
related: /pages/sessions, /sign-in/sign-out-and-cookies, /running/hosting-checklist
---

# Visitors

A session is one tab, and what an app keeps outside the session needs an
owner. In an app with sign-in the owner is `s.user.id`. In an app without
it nothing says who is asking, unless the app identifies its visitors.

```python
app = mw.App("reports", identify_visitors=True)
```

A visitor is a browser. `s.visitor.id` is a string that is the same in
every tab of one browser and different in every other, a private window
included. millwork keeps nothing under the id. It is a name for the app
to store things by.

With the argument left out, `s.visitor` raises an error that names it,
and an app without sign-in sets no cookie at all.

## Pinning to a visitor

What is saved carries the id of the visitor who made it, and what is
loaded is checked against the visitor who asks.

```python
async def save(s: mw.Session[State], _: object) -> None:
    report = await store.save(s.state.draft, owner=s.visitor.id)
    s.navigate(f"/reports/{report.id}")


@app.page("/reports/{report_id}")
def report(s: mw.Session[State]) -> ui.Component:
    return ui.Page(ui.Markdown(s.state.report.text))


@report.connect
async def load(s: mw.Session[State], report_id: str) -> None:
    found = await store.report(report_id)
    if found is None or found.owner != s.visitor.id:
        raise mw.NotFound()
    s.state.report = found
```

The address now opens in any tab of the browser that made the report. In
any other browser it is a page that does not exist, so the address tells
nobody that there is something behind it.

The store is the app's, and so is how long it keeps things. millwork does
not say when a visitor has left for good, so what is kept for one gets an
age of its own.

Without sign-in a browser is one visitor, whoever sits at it. What people
who share a browser should not see of each other needs sign-in.

## The user and the visitor

In an app with sign-in a session has both. `s.user` is the person and
`s.visitor` is the browser they are using, and neither stands in for the
other. Such an app pins to the user, who is the same person in another
browser, and can note the visitor next to it, in a log of who worked from
where.

A browser can be shared, so an id is good for one sign-in and no longer.
The browser gets a new id when someone signs in, and again when they sign
out or their sign-in ends. Whoever uses the browser next is never the
visitor the last person was, and a tab that was open before the sign-in
keeps the id it had, which the person who signed in never used.

What a visitor made before signing in is therefore not within their reach
afterwards, in an app that pins to the visitor alone.

## What the id is good for

The id comes from a cookie the first page load sets. The cookie is signed,
`HttpOnly`, `SameSite=Lax` and `Secure` over HTTPS. It has no lifetime of
its own, so it lasts for the browser's session, which a browser set to
bring its tabs back carries over a restart. Its name and path carry the
app's prefix, `mw_visitor_sales` under `/sales`.

- The id cannot be made up or changed, and one read from a log is not
  enough to become that visitor, since the cookie holds a signature too.
- The cookie can be thrown away, and the browser is then a new visitor.
  That makes the id no basis for a limit, and the caps on sessions go on
  counting by address.
- A browser that refuses the cookie is a visitor of its own in every tab.
  What is pinned there stays private to the tab.
- A session keeps the visitor it was opened with for as long as it lives.
- Tabs that load at the same moment in a browser that has no cookie yet
  can each get an id, and a tab keeps its own until its session ends.

The cookie is signed with the app's `secret`. An app that sets none gets
a new one at every start, and every browser a new id with it. That suits
an app that keeps things in memory, where they are gone as well. An app
that keeps them longer, or runs on more than one replica, sets a secret
of 32 characters or more, as the
[Hosting checklist](/running/hosting-checklist) says.

## In a test

`open(path, visitor="a")` opens the page from a browser whose id is `a`.
Two pages opened with the same one are two tabs of it, and a page opened
without is a browser of its own.

```python
async def test_a_report_is_its_makers_alone() -> None:
    tabs = TestApp(app)
    async with tabs.open("/", visitor="a") as page:
        await page.click("save")
        address = page.session.path
    async with tabs.open(address, visitor="a") as page:
        assert page.find(ui.Markdown) is not None
    with pytest.raises(mw.NotFound):
        async with tabs.open(address, visitor="b"):
            pass
```
