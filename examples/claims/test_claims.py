"""The claims app, driven without a browser. A page is opened as one of
the people, and what one of them does is there for the others."""

from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient

import millwork as mw
from millwork import auth, ui
from millwork.files import Reject
from millwork.testing import Page, TestApp

RECEIPTS = Path(__file__).parent / "receipts"
ROLES = {"nora": "employee", "omar": "employee", "priya": "manager", "lena": "finance"}


def who(name: str, role: str | None = None) -> auth.User:
    """One of the people, as the sign-in admits them."""
    return auth.User(id=name, name=name.capitalize(), claims={"role": role or ROLES[name]})


@pytest.fixture
async def t(example: ModuleType) -> AsyncIterator[TestApp]:
    harness = TestApp(example.app)
    yield harness
    await harness.shutdown()


@pytest.fixture
def claims(example: ModuleType) -> dict[str, object]:
    """The claims the app starts with, by the first word of each."""
    return {c.title.split()[0].lower(): c for c in example.CLAIMS.all.values()}


def draft(example: ModuleType, **what: object) -> object:
    filled = {"title": "Train to the workshop", "amount": "94.40", "spent": date.today()}
    return example.Draft(**{**filled, **what})


def details(example: ModuleType, claim: object, **changed: object) -> object:
    """What a claim says, with something in it changed."""
    said = {name: getattr(claim, name) for name in ("title", "category", "amount", "spent", "note")}
    return example.Details(**{**said, **changed})


async def file(page: Page, example: ModuleType) -> None:
    """Fill in the form for a new claim, with a receipt, and send it."""
    await page.click("file")
    receipt = await page.upload("new", RECEIPTS / "train.png", field="/receipt")
    await page.submit("new", draft(example, receipt=receipt))


def statuses(page: Page, table: str) -> dict[str, str]:
    return {row["title"]: row["status"] for row in page.find(table).rows}


def places(page: Page) -> list[str]:
    return [link.props["label"] for link in page.find_all(ui.Link)]


# ------------------------------------------------------------ who gets where


async def test_everyone_starts_on_a_page_of_their_own(t: TestApp) -> None:
    for name, home in (("nora", "/mine"), ("priya", "/review"), ("lena", "/payments")):
        async with t.open("/", user=who(name)) as page:
            assert page.session.path == home


async def test_a_page_is_for_the_people_it_names(t: TestApp, claims: dict[str, object]) -> None:
    refused = (
        ("nora", "/review"),
        ("nora", "/report"),
        ("priya", "/payments"),
        ("lena", "/mine"),
        ("lena", "/team"),
    )
    for name, path in refused:
        with pytest.raises(mw.Forbidden):
            async with t.open(path, user=who(name)):
                pass
    # Someone else's claim is a page there is, and not one for Omar.
    with pytest.raises(mw.Forbidden, match="someone else's"):
        async with t.open(f"/claims/{claims['dinner'].id}", user=who("omar")):
            pass
    with pytest.raises(mw.NotFound):
        async with t.open("/claims/9999", user=who("nora")):
            pass


async def test_the_sidebar_has_the_places_and_the_people_of_its_person(t: TestApp) -> None:
    async with (
        t.open("/mine", user=who("nora")) as nora,
        t.open("/review", user=who("priya")) as priya,
        t.open("/payments", user=who("lena")) as lena,
    ):
        assert places(nora) == ["My claims"]
        assert places(priya) == ["Review", "Team's claims", "Report"]
        assert places(lena) == ["Payments", "Report"]
        assert "Priya Nair" in nora.text() and "Omar Reyes" not in nora.text()
        assert "Omar Reyes" in priya.text() and "Omar Reyes" in lena.text()


async def test_a_manager_sees_and_decides_for_their_own_people_only(
    t: TestApp, example: ModuleType, claims: dict[str, object]
) -> None:
    # A second manager, with nobody under her.
    sana = example.PEOPLE["sana"] = type(example.PEOPLE["priya"])("sana", "Sana Idris", "manager")
    monitor = claims["monitor"]
    for path, table in (("/review", "waiting"), ("/team", "team"), ("/report", "paid")):
        async with t.open(path, user=who("sana", "manager")) as page:
            assert page.find(table).rows == []
    with pytest.raises(mw.Forbidden):
        async with t.open(f"/claims/{monitor.id}", user=who("sana", "manager")):
            pass
    # Nor does the shared data let anyone but Omar's manager decide on it:
    # another manager, Omar himself and finance.
    for name in ("sana", "omar", "lena"):
        assert not example.CLAIMS.decide(monitor, example.PEOPLE[name], approve=True)
    assert monitor.status == "waiting" and sana.manager is None


async def test_the_report_is_of_what_someone_may_see_and_prints(
    t: TestApp, example: ModuleType
) -> None:
    # Omar's manager is someone else now, so Priya's report has Nora's alone.
    example.PEOPLE["omar"] = type(example.PEOPLE["omar"])("omar", "Omar Reyes", "employee", "sana")
    for claim in example.CLAIMS.all.values():
        if claim.owner.id == "omar":
            claim.owner = example.PEOPLE["omar"]
    async with (
        t.open("/report", user=who("lena")) as lena,
        t.open("/report", user=who("priya")) as priya,
    ):
        assert len(lena.find("paid").rows) == 4
        assert {row["owner"] for row in priya.find("paid").rows} == {"Nora Feld"}
        await lena.click("print")
        assert lena.commands[-1].name == "print"


# ----------------------------------------------------------------- filing


async def test_a_claim_filed_is_with_the_manager_at_once(t: TestApp, example: ModuleType) -> None:
    async with (
        t.open("/mine", user=who("nora")) as nora,
        t.open("/review", user=who("priya")) as priya,
    ):
        assert priya.find("/review").props["badge"] == "1"
        await file(nora, example)
        assert not nora.state.filing and nora.toasts[-1] == "Sent to your manager."
        assert statuses(nora, "claims")["Train to the workshop"] == "Waiting"
        await priya.settle()
        assert priya.find("/review").props["badge"] == "2"
        assert "Train to the workshop" in statuses(priya, "waiting")
        # The claim keeps the receipt, and the upload is no longer the session's.
        claim = max(example.CLAIMS.all.values(), key=lambda c: c.id)
        assert claim.receipt.data == (RECEIPTS / "train.png").read_bytes()
        assert claim.amount == Decimal("94.40")
        assert nora.session.files.all() == []


async def test_a_claim_without_a_receipt_or_from_tomorrow_is_refused(
    t: TestApp, example: ModuleType
) -> None:
    # These two are 25 hours apart, so it is always another day in one
    # than in the other, and a day is the day it is for the person filing.
    ahead, behind = "Pacific/Kiritimati", "Pacific/Pago_Pago"
    there = datetime.now(ZoneInfo(ahead)).date()
    here = datetime.now(ZoneInfo(behind)).date()
    assert there > here
    async with t.open("/mine", user=who("nora"), timezone=behind) as nora:
        before = len(example.CLAIMS.all)
        await nora.click("file")
        assert nora.find("new").props["initial"]["spent"] == str(here)
        await nora.submit("new", draft(example, spent=there))
        issues = {i["pointer"]: i["message"] for i in nora.commands[-1].args["issues"]}
        assert issues == {
            "/receipt": "A claim has a receipt.",
            "/spent": "That day has not come yet.",
        }
        assert len(example.CLAIMS.all) == before and nora.state.filing
    # The same day is today for someone who is there.
    async with t.open("/mine", user=who("nora"), timezone=ahead) as nora:
        await nora.click("file")
        receipt = await nora.upload("new", RECEIPTS / "train.png", field="/receipt")
        await nora.submit("new", draft(example, spent=there, receipt=receipt))
        assert len(example.CLAIMS.all) == before + 1


async def test_a_receipt_is_a_small_picture_whatever_sends_it(t: TestApp, tmp_path: Path) -> None:
    (tmp_path / "page.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (tmp_path / "huge.png").write_bytes(b"\x89PNG" + bytes(6_000_000))
    async with t.open("/mine", user=who("nora")) as nora:
        await nora.click("file")
        for name in ("page.svg", "huge.png"):
            with pytest.raises(Reject):
                await nora.upload("new", tmp_path / name, field="/receipt")
        assert nora.session.files.all() == []


async def test_an_open_form_does_not_follow_someone_to_another_page(
    t: TestApp, claims: dict[str, object]
) -> None:
    async with t.open(f"/claims/{claims['dinner'].id}", user=who("nora")) as nora:
        await nora.click("change")
        assert nora.state.filing
        await nora.navigate("/mine")
        assert not nora.state.filing
        # A row's click goes to that claim, and to nowhere a tab makes up.
        await nora.event("claims", "row_click", f"{claims['dinner'].id}/../../payments")
        assert nora.session.path == "/mine"


# --------------------------------------------------------------- deciding


async def test_a_manager_approves_and_finance_pays(t: TestApp, claims: dict[str, object]) -> None:
    monitor = claims["monitor"]
    async with (
        t.open(f"/claims/{monitor.id}", user=who("priya")) as priya,
        t.open("/payments", user=who("lena")) as lena,
        t.open("/mine", user=who("omar")) as omar,
    ):
        assert statuses(lena, "due").keys() == {
            "Flight to the conference",
            "Parking at the conference",
        }
        await priya.click("approve")
        assert monitor.status == "approved"
        # What she could do is done, and the buttons are gone with it.
        assert not priya.find_all("approve") and "Priya Nair approved it" in priya.text()
        await lena.settle()
        assert "Monitor for the office" in statuses(lena, "due")
        await lena.click("pay")
        assert lena.toasts[-1] == "3 paid, €419.60 in all."
        assert lena.find("due").rows == [] and lena.find("pay").props["disabled"]
        await omar.settle()
        assert statuses(omar, "claims")["Monitor for the office"] == "Paid"


async def test_a_claim_sent_back_is_changed_and_sent_again(
    t: TestApp, example: ModuleType, claims: dict[str, object]
) -> None:
    monitor = claims["monitor"]
    async with (
        t.open(f"/claims/{monitor.id}", user=who("priya")) as priya,
        t.open("/mine", user=who("omar")) as omar,
    ):
        was_shown = priya.find(ui.Image).props["src"]
        asking = priya.session.spawn(priya.click("back"), "the question")
        await priya.settle()
        await priya.answer({"note": "Which office is it for?"})
        await asking
        assert monitor.status == "sent back" and priya.toasts[-1] == "Sent back to Omar Reyes."
        await omar.settle()
        assert "Priya Nair asks: Which office is it for?" in omar.text()
        # Omar opens it, answers in the note and sends it again with another picture.
        await omar.navigate(f"/claims/{monitor.id}")
        await omar.click("change")
        receipt = await omar.upload("again", RECEIPTS / "keyboard.png", field="/receipt")
        again = draft(example, title=monitor.title, amount="189.00", note="Quay.", receipt=receipt)
        await omar.submit("again", again)
        assert monitor.status == "waiting" and monitor.note == "Quay."
        assert monitor.receipt.name == "keyboard.png" and not omar.state.filing
        assert [e.what for e in monitor.history] == ["filed it", "sent it back", "sent it again"]
        # Priya, who had it open all along, decides on the picture it has now.
        await priya.settle()
        assert priya.find_all("approve")
        assert priya.find(ui.Image).props["src"] not in (was_shown, None)
        assert priya.find(ui.Image).props["src"].endswith(monitor.receipt.digest)


async def test_only_its_owner_changes_a_claim_and_only_one_sent_back(
    t: TestApp, example: ModuleType, claims: dict[str, object]
) -> None:
    dinner, monitor, flight = claims["dinner"], claims["monitor"], claims["flight"]
    for name in ("priya", "lena"):
        async with t.open(f"/claims/{dinner.id}", user=who(name)) as other:
            # Neither the button nor the form behind it is on their page.
            assert not other.find_all("change") and not other.find_all("again")
    people = example.PEOPLE
    changed = details(example, dinner, title="Changed", amount=Decimal("4999"))
    assert not example.CLAIMS.send_again(dinner, people["priya"], changed, None)
    assert dinner.title == "Dinner with the launch team" and dinner.status == "sent back"
    # Omar's own claim is waiting, which is not his moment to change it.
    assert not example.CLAIMS.send_again(monitor, people["omar"], details(example, monitor), None)
    # And paying is for what is approved, by finance, once.
    assert example.CLAIMS.pay([monitor, flight], people["priya"]) == []
    assert example.CLAIMS.pay([monitor, flight], people["lena"]) == [flight]
    assert example.CLAIMS.pay([flight], people["lena"]) == []


async def test_a_claim_someone_else_got_to_first_says_so(
    t: TestApp, example: ModuleType, claims: dict[str, object]
) -> None:
    monitor = claims["monitor"]
    async with t.open(f"/claims/{monitor.id}", user=who("priya")) as priya:
        # Approved from another tab of hers, as this one was being pressed.
        example.CLAIMS.decide(monitor, example.PEOPLE["priya"], approve=True)
        await priya.event("approve", "click")
        assert "Nothing was done." in priya.toasts[-1]


# ---------------------------------------------------------------- sign-in


def test_the_people_sign_in_with_the_password_and_nobody_else(example: ModuleType) -> None:
    assert example.verify("nora", "claims")
    for name, password in (("nora", "wrong"), ("nobody", "claims"), ("nora", "clàims")):
        assert not example.verify(name, password)
    user = example.admit(auth.Identity(provider="password", subject="priya"))
    assert user is not None and user.claims == {"role": "manager"}
    # The same name from another way of signing in is not that person.
    assert example.admit(auth.Identity(provider="google", subject="priya")) is None


def test_a_receipt_is_served_to_who_may_see_its_claim(
    example: ModuleType, claims: dict[str, object]
) -> None:
    dinner = claims["dinner"]
    address = f"/receipts/{dinner.id}/{dinner.receipt.digest}"
    with TestClient(example.app.asgi) as browser:
        # Signed out there is nothing to get.
        assert browser.get(address, follow_redirects=False).status_code != 200
        for name, status in (("nora", 200), ("priya", 200), ("lena", 200), ("omar", 404)):
            browser.cookies.clear()
            signed_in = browser.post(
                "/_mw/auth/login", json={"username": name, "password": "claims"}
            )
            assert signed_in.status_code == 200, signed_in.text
            assert browser.get(address).status_code == status, name
        browser.cookies.clear()
        browser.post("/_mw/auth/login", json={"username": "nora", "password": "claims"})
        got = browser.get(address)
        assert got.content == dinner.receipt.data and got.headers["content-type"] == "image/png"
        # A browser that kept it asks again, and is told it still holds.
        again = browser.get(address, headers={"If-None-Match": got.headers["etag"]})
        assert again.status_code == 304 and again.content == b""
        # An address of other bytes, or of no claim, leads nowhere.
        assert browser.get(f"/receipts/{dinner.id}/0000").status_code == 404
        assert browser.get(f"/receipts/9999/{dinner.receipt.digest}").status_code == 404
