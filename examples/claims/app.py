"""Expense claims. Someone files a claim with its receipt, their manager
approves it or sends it back with a question, and finance pays what was
approved and prints the report.

    uv run millwork run examples/claims/app.py

Sign in as nora or omar, who file claims, as priya, who reviews them, or
as lena, who pays them. The password is "claims".

What the company shares is in ``claims.py``, outside every session, and
that is also where it is decided who may do what to a claim. This file is
who may open which page, the pages and the handlers.
"""

from __future__ import annotations

import hmac
import mimetypes
import secrets
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from claims import PEOPLE, Category, Claim, Details, Event, Person, Receipt, Status, seeded
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import Response

import millwork as mw
from millwork import auth, ui

CLAIMS = seeded()

TONES: dict[Status, ui.Tone] = {
    "waiting": "primary",
    "sent back": "warning",
    "approved": "success",
    "paid": "muted",
}
DOES = {"employee": "files claims", "manager": "reviews claims", "finance": "pays claims"}


class State(BaseModel):
    # Whether the form on the page is open, for a new claim or for one
    # that came back.
    filing: bool = False


class Draft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=60, title="What was it for")
    category: Category = "Travel"
    amount: Decimal = Field(gt=0, le=5000, decimal_places=2)
    spent: date = Field(title="Spent on")
    # A new claim has to have one. A claim that is sent again may come
    # without, and keeps the one it has. What the field takes is said here
    # on the model, where the server holds an upload to it as well as the
    # browser.
    receipt: mw.FileRef | None = Field(
        None,
        description="A photo of it.",
        json_schema_extra={"accept": [".png", ".jpg", ".jpeg"], "max_size_mb": 5},
    )
    note: str = Field("", max_length=300)


# How the form shows two of the fields.
FIELDS = {"/amount": {"widget": "number", "step": 0.01}, "/note": {"widget": "textarea", "rows": 3}}


class Reason(BaseModel):
    note: str = Field(min_length=3, max_length=300, title="What is missing")


# ---------------------------------------------------------------- sign-in


def verify(username: str, password: str) -> bool:
    # One password for everyone, since this is a demo. An app checks a hash
    # of each person's own with auth.check_password.
    return username in PEOPLE and hmac.compare_digest(password.encode(), b"claims")


def admit(identity: auth.Identity) -> auth.User | None:
    """Who signed in, as one of the people. Their role goes in the cookie,
    where the rules of the pages read it. Someone whose role changes keeps
    the old one until they sign in again, unless the app rechecks with
    ``Auth(recheck=)``."""
    person = PEOPLE.get(identity.subject) if identity.provider == "password" else None
    if person is None:
        return None
    return auth.User(id=person.id, name=person.name, claims={"role": person.role})


def role(*roles: str) -> Callable[[auth.User], bool]:
    """A rule for a page that the people in one of these roles may open."""

    def rule(user: auth.User) -> bool:
        return str(user.claims["role"]) in roles

    # What `millwork routes` calls the rule, where it lists who may go where.
    rule.__qualname__ = f"role({', '.join(roles)})"
    return rule


app = mw.App(
    "Expenses",
    state=State,
    # A new secret at every start, so a restart signs everyone out. An app
    # keeps one, from wherever it keeps its secrets.
    secret=secrets.token_urlsafe(32),
    auth=auth.Auth(
        [auth.Password(verify)],
        on_login=admit,
        login=ui.Stack(
            ui.SignIn("password"),
            ui.Markdown(
                "Sign in as **nora** or **omar**, who file claims, as **priya**, who"
                " reviews them, or as **lena**, who pays them. The password is `claims`."
            ),
            gap=4,
        ),
    ),
)


def me(s: mw.Session[State]) -> Person:
    return PEOPLE[s.user.id]


def this_claim(s: mw.Session[State]) -> Claim:
    """The claim the page is about."""
    return CLAIMS.all[s.params["claim_id"]]


def today(s: mw.Session[State]) -> date:
    """The day it is for the person at the screen, wherever the server stands."""
    return datetime.now(s.timezone).date()


# -------------------------------------------------------------- handlers


def open_form(s: mw.Session[State], _: object) -> None:
    s.state.filing = True


def close_form(s: mw.Session[State], _: object) -> None:
    s.state.filing = False


def written(
    s: mw.Session[State], draft: Draft, receipt_needed: bool
) -> tuple[Details, Receipt | None]:
    """What a form holds, as the claim keeps it, or the form's fields with
    what is wrong at them."""
    wrong = []
    if receipt_needed and draft.receipt is None:
        wrong.append(("/receipt", "A claim has a receipt."))
    if draft.spent > today(s):
        wrong.append(("/spent", "That day has not come yet."))
    if wrong:
        raise ui.FormIssues(wrong)
    receipt = None
    if draft.receipt is not None:
        # An upload is the session's and ends with it. The claim keeps the
        # bytes, for whoever looks at it later.
        receipt = Receipt(draft.receipt.name, draft.receipt.path.read_bytes())
        s.files.remove(draft.receipt.id)
    return Details(**draft.model_dump(exclude={"receipt"})), receipt


def file(s: mw.Session[State], draft: Draft) -> None:
    details, receipt = written(s, draft, receipt_needed=True)
    if receipt is not None:
        CLAIMS.file(me(s), details, receipt)
        s.state.filing = False
        s.toast("Sent to your manager.", tone="success")


def send_again(s: mw.Session[State], draft: Draft) -> None:
    details, receipt = written(s, draft, receipt_needed=False)
    s.state.filing = False
    tell(s, CLAIMS.send_again(this_claim(s), me(s), details, receipt), "Sent again.")


def look_at(s: mw.Session[State], claim_id: object) -> None:
    if isinstance(claim_id, int):
        s.navigate(f"/claims/{claim_id}")


def approve(s: mw.Session[State], _: object) -> None:
    tell(s, CLAIMS.decide(this_claim(s), me(s), approve=True), "Approved. Finance will pay it.")


async def send_back(s: mw.Session[State], _: object) -> None:
    claim = this_claim(s)
    why = await s.ask(
        ui.Dialog(
            ui.Form(Reason, submit="Send back", key="reason"),
            title="Send it back",
            description="The claim goes back with your question, to be changed and sent again.",
        )
    )
    if why is not None:
        sent = CLAIMS.decide(claim, me(s), approve=False, note=why.note)
        tell(s, sent, f"Sent back to {claim.owner.name}.")


def pay(s: mw.Session[State], _: object) -> None:
    paid = CLAIMS.pay(CLAIMS.seen_by(me(s), "approved"), me(s))
    tell(s, bool(paid), f"{len(paid)} paid, {total(paid)} in all.")


def tell(s: mw.Session[State], done: bool, words: str) -> None:
    """Say what the shared data did, or that it did nothing, which is what
    it does when someone else got there first."""
    if done:
        s.toast(words, tone="success")
    else:
        s.toast("Nothing was done. This has changed since the page drew it.", tone="warning")


# ----------------------------------------------------------------- pages

# Where each kind of person starts.
HOME = {"employee": "/mine", "manager": "/review", "finance": "/payments"}


@app.page("/")
def front(s: mw.Session[State]) -> ui.Component:
    return ui.Page()


@front.connect
def to_their_own(s: mw.Session[State]) -> None:
    s.navigate(HOME[me(s).role])


@app.page("/mine", title="My claims", allow=role("employee"))
def mine(s: mw.Session[State]) -> ui.Component:
    claims = CLAIMS.seen_by(me(s))
    came_back = [
        ui.Alert(
            title=f"{c.title} came back",
            description=f"{c.history[-1].who.name} asks: {c.history[-1].note}",
            tone="warning",
            actions=[ui.Button("Open it", size="sm", href=f"/claims/{c.id}")],
            key=f"back-{c.id}",
        )
        for c in claims
        if c.status == "sent back"
    ]
    return frame(
        s,
        "My claims",
        *came_back,
        ui.Grid(
            ui.Stat(label="With your manager", value=total(claims, "waiting", "sent back")),
            ui.Stat(label="Approved, to be paid", value=total(claims, "approved")),
            ui.Stat(label="Paid", value=total(claims, "paid")),
            cols={"sm": 1, "md": 3},
        ),
        ui.Card(table(claims, key="claims"), title="Claims"),
        ui.Sheet(
            # It opens on the day it is for the person filing.
            ui.Form(
                Draft,
                initial={"spent": today(s)},
                submit="Send to my manager",
                on_submit=file,
                overrides=FIELDS,
                key="new",
            ),
            open=s.state.filing,
            title="New claim",
            size="md",
            on_close=close_form,
        ),
        action=ui.Button("New claim", icon="plus", on_click=open_form, key="file"),
    )


@app.page("/review", title="Review", allow=role("manager"))
def review(s: mw.Session[State]) -> ui.Component:
    waiting = CLAIMS.seen_by(me(s), "waiting")
    card = ui.Card(
        table(waiting, owner=True, key="waiting", empty="Nothing is waiting for you."),
        title="Waiting for you",
        description=summed(waiting),
    )
    return frame(s, "Review", card)


@app.page("/team", title="Team's claims", allow=role("manager"))
def team(s: mw.Session[State]) -> ui.Component:
    return frame(s, "Team's claims", ui.Card(table(CLAIMS.seen_by(me(s)), owner=True, key="team")))


@app.page("/payments", title="Payments", allow=role("finance"))
def payments(s: mw.Session[State]) -> ui.Component:
    due = CLAIMS.seen_by(me(s), "approved")
    card = ui.Card(
        table(due, owner=True, key="due", empty="Nothing is waiting to be paid."),
        title="Approved, to pay",
        description=summed(due),
    )
    pay_all = ui.Button("Pay them all", icon="check", disabled=not due, on_click=pay, key="pay")
    return frame(s, "Payments", card, action=pay_all)


@app.page("/report", title="Report", allow=role("manager", "finance"))
def report(s: mw.Session[State]) -> ui.Component:
    # What was paid, of a manager's own people or of everyone.
    paid = CLAIMS.seen_by(me(s), "paid")
    card = ui.Card(table(paid, owner=True, key="paid"), title="Paid", description=summed(paid))
    # The page as it stands, on paper or as a PDF. The sidebar and the
    # header stay off it.
    on_paper = ui.Button(
        "Print", icon="printer", variant="outline", on_click=lambda s, _: s.print(), key="print"
    )
    return frame(s, "Report", card, action=on_paper)


# One connect hook for the five pages that list claims.
@report.connect
@payments.connect
@team.connect
@review.connect
@mine.connect
def enter(s: mw.Session[State]) -> None:
    s.follow(CLAIMS.changed)
    s.state.filing = False


@app.page("/claims/{claim_id:int}", title="A claim")
def claim(s: mw.Session[State]) -> ui.Component:
    c = this_claim(s)
    mine_to_change = c.status == "sent back" and me(s) == c.owner
    return frame(
        s,
        f"Claim {c.id}",
        ui.Grid(
            ui.Card(
                # From a route of the app's own, which asks who is looking.
                # The address names the picture's bytes, so a receipt that
                # is replaced has a new one and is fetched again.
                ui.Image(
                    src=f"/receipts/{c.id}/{c.receipt.digest}",
                    alt=f"The receipt for {c.title}",
                    size="full",
                ),
                title="Receipt",
                description=c.receipt.name,
            ),
            ui.Stack(
                ui.Card(
                    ui.Row(
                        ui.Text(money(c.amount), variant="title"),
                        ui.Badge(c.status.capitalize(), tone=TONES[c.status]),
                        justify="between",
                    ),
                    fact("Filed by", c.owner.name),
                    fact("Category", c.category),
                    fact("Spent on", f"{c.spent:%a} {c.spent.day} {c.spent:%B}"),
                    fact("Note", c.note or "None"),
                    title=c.title,
                    footer=actions(s, c),
                ),
                ui.Card(*(happened(s, e, n) for n, e in enumerate(c.history)), title="History"),
                gap=6,
            ),
            cols={"sm": 1, "md": 2},
        ),
        # The form is on the page of the one person who may send it. A sheet
        # that is closed is still on the page, and so is the form in it.
        ui.Sheet(
            ui.Form(
                Draft,
                initial={
                    "title": c.title,
                    "category": c.category,
                    "amount": c.amount,
                    "spent": c.spent,
                    "note": c.note,
                },
                submit="Send it again",
                on_submit=send_again,
                overrides=FIELDS,
                key="again",
            ),
            open=s.state.filing,
            title="Change the claim",
            description="A new receipt takes the place of the one it has.",
            size="md",
            on_close=close_form,
        )
        if mine_to_change
        else None,
    )


@claim.connect
def open_claim(s: mw.Session[State], claim_id: int) -> None:
    c = CLAIMS.all.get(claim_id)
    if c is None:
        raise mw.NotFound()
    # Whose claim it is takes a look at the claim, and a rule only reads
    # the user and the path it is handed. So the page asks here.
    if not c.open_to(me(s)):
        raise mw.Forbidden("This claim is someone else's.")
    s.follow(CLAIMS.changed)
    s.state.filing = False


async def receipt(request: Request) -> Response:
    """A claim's receipt, for whoever may see the claim. It is a route
    behind the sign-in, since a file that several people look at cannot
    be a file of one of their sessions."""
    c = CLAIMS.all.get(request.path_params["claim_id"])
    person = PEOPLE.get(request.state.user.id)
    digest = request.path_params["digest"]
    if c is None or person is None or not c.open_to(person) or c.receipt.digest != digest:
        return Response(status_code=404)
    # A browser may keep the picture and has to ask before it shows it
    # again, so that someone who may no longer see it does not.
    headers = {"Cache-Control": "private, no-cache", "ETag": f'"{digest}"'}
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    kind = mimetypes.guess_type(c.receipt.name)[0] or "application/octet-stream"
    return Response(c.receipt.data, media_type=kind, headers=headers)


app.route("/receipts/{claim_id:int}/{digest}", receipt)


# ----------------------------------------------------------------- parts

# The places there are, with the status whose claims are counted beside each.
PLACES: list[tuple[str, str, str, Status | None]] = [
    ("/mine", "My claims", "file-text", "sent back"),
    ("/review", "Review", "inbox", "waiting"),
    ("/team", "Team's claims", "users", None),
    ("/payments", "Payments", "credit-card", "approved"),
    ("/report", "Report", "printer", None),
]


def frame(
    s: mw.Session[State],
    title: str,
    *children: ui.Component | None,
    action: ui.Component | None = None,
) -> ui.Component:
    """A page with the sidebar every page has. A link is there for whoever
    may follow it, so each kind of person has a sidebar of their own, and
    under the links are the people they work with."""
    who = me(s)
    links = []
    for path, label, icon, counted in PLACES:
        if s.can(path):
            count = len(CLAIMS.seen_by(who, counted)) if counted else 0
            links.append(
                ui.Link(
                    label=label,
                    href=path,
                    icon=icon,
                    active=s.path == path,
                    badge=str(count) if count else None,
                    key=path,
                )
            )
    return ui.Page(
        ui.Sidebar(
            ui.SidebarGroup(*links, label="Claims", collapsible=False),
            ui.SidebarGroup(
                *(person(p) for p in PEOPLE.values() if works_with(who, p)),
                label="People",
                collapsible=False,
            ),
            title="Expenses",
        ),
        *children,
        title=title,
        header=ui.Header(action, title=title),
    )


def works_with(one: Person, other: Person) -> bool:
    """Whether two people have a hand in the same claims. Finance has in
    everyone's, and a manager in those of their own people."""
    if one == other:
        return False
    return "finance" in (one.role, other.role) or one.id == other.manager or other.id == one.manager


def person(p: Person) -> ui.Component:
    initials = "".join(word[0] for word in p.name.split())
    return ui.Row(
        ui.Stack(
            ui.Text(initials, cls="text-[10px] font-semibold"),
            align="center",
            justify="center",
            cls="size-7 shrink-0 rounded-full bg-sidebar-accent text-sidebar-accent-foreground",
        ),
        ui.Stack(ui.Text(p.name), ui.Text(DOES[p.role], variant="caption"), gap=0),
        gap=2,
        cls="px-2 py-1",
        key=p.id,
    )


def table(claims: list[Claim], key: str, owner: bool = False, **more: Any) -> ui.Component:
    return ui.Table(
        rows=[
            {
                "id": c.id,
                "owner": c.owner.name,
                "title": c.title,
                "status": c.status.capitalize(),
                "category": c.category,
                "spent": c.spent,
                "amount": c.amount,
            }
            for c in claims
        ],
        columns=[
            ui.Column(key="owner", header="Filed by", hidden=not owner),
            ui.Column(key="title", header="Claim"),
            # Next to the claim, where a narrow screen still shows it.
            ui.Column(key="status", header="Status", format="badge"),
            # Whose it is takes the room of what kind it is.
            ui.Column(key="category", header="Category", hidden=owner),
            ui.Column(key="spent", header="Spent on", format="date"),
            ui.Column(key="amount", header="Amount", format="currency", align="right"),
        ],
        default_sort=[("spent", "desc")],
        tones={"status": lambda row, value: TONES[value.lower()]},
        summary=False,
        on_row_click=look_at,
        key=key,
        **more,
    )


def actions(s: mw.Session[State], c: Claim) -> ui.Component | None:
    """What the person looking at a claim can do with it now. The shared
    data asks again who it is when a button is pressed."""
    if c.status == "waiting" and me(s).id == c.owner.manager:
        return ui.Row(
            ui.Button(
                "Send back", icon="undo-2", variant="outline", on_click=send_back, key="back"
            ),
            ui.Button("Approve", icon="check", on_click=approve, key="approve"),
            justify="end",
            cls="w-full",
        )
    if c.status == "sent back" and me(s) == c.owner:
        return ui.Row(
            ui.Text(f"{c.history[-1].who.name} asks: {c.history[-1].note}", tone="warning"),
            ui.Button("Change it", icon="pencil", on_click=open_form, key="change"),
            justify="between",
            cls="w-full",
        )
    return None


def fact(label: str, value: str) -> ui.Component:
    return ui.Row(
        ui.Text(label, variant="muted", cls="w-24 shrink-0"), ui.Text(value), align="start"
    )


def happened(s: mw.Session[State], e: Event, n: int) -> ui.Component:
    # On the clock of whoever reads it.
    at = e.at.astimezone(s.timezone)
    return ui.Stack(
        ui.Text(f"{e.who.name} {e.what}", variant="label"),
        ui.Text(f"{at:%a} {at.day} {at:%b}, {at:%H:%M}", variant="caption"),
        ui.Text(e.note, variant="muted") if e.note else None,
        gap=0,
        key=f"event-{n}",
    )


def summed(claims: list[Claim]) -> str:
    return f"{len(claims)} claim{'' if len(claims) == 1 else 's'}, {total(claims)}"


def total(claims: list[Claim], *statuses: Status) -> str:
    return money(
        sum((c.amount for c in claims if not statuses or c.status in statuses), Decimal(0))
    )


def money(amount: Decimal) -> str:
    # As a table's currency column writes it.
    return f"€{amount:,.2f}"
