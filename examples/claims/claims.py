"""What the company shares, which is its people, their claims and what
happened to each one. It is kept outside every session, in one ``Claims``,
with a ``mw.Signal`` beside it that the pages follow, so a claim one
person files is in front of the person who reviews it at once.

Who may do what to a claim is decided here, where every page and every
handler passes through, and not by which buttons a page happens to draw."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from typing import Literal

import millwork as mw

Category = Literal["Travel", "Lodging", "Meals", "Equipment", "Other"]
Status = Literal["waiting", "sent back", "approved", "paid"]


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role: Literal["employee", "manager", "finance"]
    # Who reviews what this person files.
    manager: str | None = None


PEOPLE = {
    p.id: p
    for p in (
        Person("nora", "Nora Feld", "employee", manager="priya"),
        Person("omar", "Omar Reyes", "employee", manager="priya"),
        Person("priya", "Priya Nair", "manager"),
        Person("lena", "Lena Marsh", "finance"),
    )
}


@dataclass(frozen=True)
class Receipt:
    name: str
    data: bytes

    @cached_property
    def digest(self) -> str:
        """A name for these bytes and no others, for an address that a
        browser may keep what it got from."""
        return hashlib.sha256(self.data).hexdigest()[:16]


@dataclass(frozen=True)
class Event:
    at: datetime
    who: Person
    what: str
    note: str = ""


@dataclass(kw_only=True)
class Details:
    """What a claim says, as the person who files it writes it."""

    title: str
    category: Category
    amount: Decimal
    spent: date
    note: str = ""


@dataclass(kw_only=True)
class Claim(Details):
    id: int
    owner: Person
    receipt: Receipt
    status: Status = "waiting"
    history: list[Event] = field(default_factory=list)

    def open_to(self, person: Person) -> bool:
        """Whether someone may see it. That is who filed it, their manager
        and finance."""
        return person == self.owner or person.id == self.owner.manager or person.role == "finance"


class Claims:
    def __init__(self) -> None:
        self.all: dict[int, Claim] = {}
        # Fired at everything that happens to a claim.
        self.changed = mw.Signal()

    def seen_by(self, person: Person, *statuses: Status) -> list[Claim]:
        """The claims someone may see, their own, their people's or
        everyone's, in one of the statuses when any are given."""
        return [
            c
            for c in self.all.values()
            if c.open_to(person) and (not statuses or c.status in statuses)
        ]

    def file(
        self, owner: Person, details: Details, receipt: Receipt, at: datetime | None = None
    ) -> Claim:
        claim = Claim(**asdict(details), id=1041 + len(self.all), owner=owner, receipt=receipt)
        self.all[claim.id] = claim
        self._did(claim, owner, "filed it", at=at)
        return claim

    def send_again(
        self, claim: Claim, by: Person, details: Details, receipt: Receipt | None
    ) -> bool:
        """The claim as its owner changed it, back with their manager. With
        no new receipt it keeps the one it has. Returns whether it was
        done. Only the owner sends a claim again, and only one that was
        sent back."""
        if by != claim.owner or claim.status != "sent back":
            return False
        for name, value in asdict(details).items():
            setattr(claim, name, value)
        claim.receipt = receipt or claim.receipt
        claim.status = "waiting"
        self._did(claim, by, "sent it again")
        return True

    def decide(
        self, claim: Claim, by: Person, approve: bool, note: str = "", at: datetime | None = None
    ) -> bool:
        """Approve a claim or send it back. Returns whether it was done.
        Only the owner's manager decides, and only while the claim waits."""
        if by.id != claim.owner.manager or claim.status != "waiting":
            return False
        claim.status = "approved" if approve else "sent back"
        self._did(claim, by, "approved it" if approve else "sent it back", note, at)
        return True

    def pay(self, claims: Iterable[Claim], by: Person, at: datetime | None = None) -> list[Claim]:
        """Pay the claims that are approved. Returns the ones it paid. Only
        finance pays."""
        paid = [c for c in claims if c.status == "approved" and by.role == "finance"]
        for claim in paid:
            claim.status = "paid"
            self._did(claim, by, "paid it", at=at)
        return paid

    def _did(
        self, claim: Claim, who: Person, what: str, note: str = "", at: datetime | None = None
    ) -> None:
        claim.history.append(Event(at or datetime.now(UTC), who, what, note))
        self.changed.fire()


def seeded() -> Claims:
    """A few weeks of two people's claims, at every stage, so that each of
    the three kinds of people finds something to do."""
    claims = Claims()
    nora, omar, priya, lena = (PEOPLE[name] for name in ("nora", "omar", "priya", "lena"))
    pictures = Path(__file__).parent / "receipts"
    now = datetime.now(UTC)

    def filed(
        who: Person, title: str, category: Category, amount: str, picture: str, days: int
    ) -> Claim:
        """A claim filed so many days ago, for what was spent that day."""
        at = now - timedelta(days=days)
        details = Details(title=title, category=category, amount=Decimal(amount), spent=at.date())
        receipt = Receipt(f"{picture}.png", (pictures / f"{picture}.png").read_bytes())
        return claims.file(who, details, receipt, at)

    # Four that went all the way, approved the day after and paid two days later.
    for claim in (
        filed(nora, "Keyboard for the home office", "Equipment", "103.90", "keyboard", days=26),
        filed(omar, "Lunch with a supplier", "Meals", "48.00", "lunch", days=21),
        filed(nora, "Hotel for the client visit", "Lodging", "327.00", "hotel", days=12),
        filed(nora, "Taxi from the airport", "Travel", "44.00", "taxi", days=11),
    ):
        was_filed = claim.history[0].at
        claims.decide(claim, priya, approve=True, at=was_filed + timedelta(days=1))
        claims.pay([claim], lena, at=was_filed + timedelta(days=3))
    # Two that finance has to pay.
    for claim in (
        filed(omar, "Flight to the conference", "Travel", "212.60", "flight", days=6),
        filed(omar, "Parking at the conference", "Travel", "18.00", "parking", days=6),
    ):
        claims.decide(claim, priya, approve=True, at=now - timedelta(days=5))
    # One that came back with a question, and one that waits for Priya.
    dinner = filed(nora, "Dinner with the launch team", "Meals", "73.20", "dinner", days=4)
    question = "Who was at the table? Put their names in the note."
    claims.decide(dinner, priya, approve=False, note=question, at=now - timedelta(days=3))
    filed(omar, "Monitor for the office", "Equipment", "189.00", "monitor", days=1)
    return claims
