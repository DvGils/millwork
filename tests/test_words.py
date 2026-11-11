"""The framework's own words: every one comes from the theme's strings, so an
app in another language sets them in one place."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError
from starlette.testclient import TestClient

import millwork as mw
from millwork import ui
from millwork.files import Reject
from millwork.forms import validate
from millwork.protocol import pack_frame
from millwork.testing import TestApp
from millwork.theme import STRINGS, Theme

BUNDLE = Path(__file__).resolve().parents[1] / "bundle" / "src"
DUTCH = Theme(
    strings={
        "save": "Opslaan",
        "download": "Downloaden",
        "other": "Overig",
        "issue_required": "Dit is verplicht.",
        "issue_too_short": "Minstens {n} tekens.",
        "issue_min": "Minstens {n}.",
        "issue_whole_number": "Vul een heel getal in.",
        "file_too_large": "het bestand is groter dan {mb} MB",
    }
)


def test_every_string_the_bundle_asks_for_exists() -> None:
    asked: set[str] = set()
    call = re.compile(r'\bt\(\s*(?:[^"()]*\?\s*)?"([a-z0-9_]+)"(?:\s*:\s*"([a-z0-9_]+)")?')
    for path in [*BUNDLE.rglob("*.tsx"), *BUNDLE.rglob("*.ts")]:
        if "__tests__" in path.parts:
            continue
        for match in call.finditer(path.read_text(encoding="utf-8")):
            asked.update(k for k in match.groups() if k)
    assert len(asked) > 40, "the pattern stopped finding the bundle's strings"
    assert sorted(asked - set(STRINGS)) == []


class Person(BaseModel):
    name: str = Field(min_length=3)
    age: int = Field(ge=18)
    tags: list[str] = Field(default_factory=list, max_length=2)
    code: str = ""

    @field_validator("code")
    @classmethod
    def _even(cls, v: str) -> str:
        if v and len(v) % 2:
            raise ValueError("an even number of characters, please")
        return v


def said(draft: dict[str, Any], theme: Theme | None = None) -> dict[str, str]:
    _, issues = validate(Person, draft, (theme or Theme()).text)
    return {i.pointer: i.message for i in issues}


def test_validation_issues_are_said_in_the_themes_words() -> None:
    assert said({}) == {"/name": "This is required.", "/age": "This is required."}
    # Nothing filled in is "required", whatever shape the nothing arrives in.
    assert said({"name": "", "age": ""}) == {
        "/name": "This is required.",
        "/age": "This is required.",
    }
    assert said({"name": None, "age": None}) == said({})
    assert said({"name": "ab", "age": 12, "tags": ["a", "b", "c"]}) == {
        "/name": "At least 3 characters.",
        "/age": "At least 18.",
        "/tags": "The maximum is 2.",
    }
    assert said({"name": "abc", "age": "x"}) == {"/age": "Enter a whole number."}
    assert said({"name": "ab", "age": 12}, DUTCH) == {
        "/name": "Minstens 3 tekens.",
        "/age": "Minstens 18.",
    }
    # A validator of the app's own speaks for itself, without pydantic's label.
    assert said({"name": "abc", "age": 20, "code": "abc"}) == {
        "/code": "an even number of characters, please"
    }
    # Without a theme to ask, and for an error the table does not know,
    # pydantic's own sentence stands.
    _, issues = validate(Person, {"name": "ab", "age": 20})
    assert issues[0].message == "String should have at least 3 characters"
    assert issues[0].code == "string_too_short"


class Limits(BaseModel):
    big: float = Field(0, ge=2500000.0)
    small: float = Field(1, le=0.123456789)
    tiny: float = Field(1, gt=1e-7)
    letter: str = Field("", max_length=1)
    customer: str = ""
    order: str = ""

    @field_validator("customer", mode="before")
    @classmethod
    def _chosen(cls, v: Any) -> Any:
        if not v:
            # One of pydantic's own kinds of error, in the app's words.
            raise PydanticCustomError("missing", "Choose a customer first")
        return v

    @field_validator("order", mode="before")
    @classmethod
    def _number(cls, v: Any) -> Any:
        if v and not str(v).isdigit():
            raise PydanticCustomError("int_parsing", "Only the order number, without letters")
        return v


def test_limits_read_as_written_and_the_apps_words_are_never_replaced() -> None:
    _, issues = validate(
        Limits,
        {"big": 1, "small": 1, "tiny": 0, "letter": "ab", "customer": "", "order": "A7"},
        Theme().text,
    )
    assert {i.pointer: i.message for i in issues} == {
        "/big": "At least 2500000.",
        "/small": "At most 0.123456789.",
        "/tiny": "More than 0.0000001.",
        "/letter": "At most 1 character.",
        "/customer": "Choose a customer first",
        "/order": "Only the order number, without letters",
    }


class GoForm(ui.Form):
    """A form of the app's own, with its own word on the button."""

    submit: str | None = "Go"


# Made before any session exists, as a module of an app might.
EARLY_PIE = ui.PieChart(rows=[{"k": c, "v": 1} for c in "abcdefg"], x="k", y="v", key="early")


def themed_app(tmp_path: Path, theme: Theme) -> mw.App:
    app = mw.App("w", public=None, bundle_dir=tmp_path, files=mw.Files(tmp_path), theme=theme)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Form(Person, key="form", on_submit=lambda s, v: None),
            ui.Form(Person, key="own", submit="Send", on_submit=lambda s, v: None),
            ui.Form(Person, key="same", submit="Save", on_submit=lambda s, v: None),
            GoForm(Person, key="sub", on_submit=lambda s, v: None),
            ui.Form(Person, key="none", submit=None, on_submit=lambda s, v: None),
            ui.Download(filename="a.txt", content="x", key="dl"),
            ui.Download("Get it", filename="a.txt", content="x", key="own-dl"),
            ui.Download("Download", filename="a.txt", content="x", key="same-dl"),
            ui.PieChart(rows=[{"k": c, "v": 1} for c in "abcdefg"], x="k", y="v", key="pie"),
            EARLY_PIE,
            ui.PieChart(
                rows=[{"k": c, "v": 1} for c in "abcdefg"],
                x="k",
                y="v",
                other="Other",
                key="own-pie",
            ),
            ui.FileUpload(max_size_mb=1, accept=[".txt"], key="up", on_upload=lambda s, r: None),
        )

    return app


async def test_default_labels_follow_the_theme_and_given_ones_stay(tmp_path: Path) -> None:
    async with TestApp(themed_app(tmp_path, DUTCH)).open("/") as page:
        assert page.find("form").props["submit"] == "Opslaan"
        assert page.find("own").props["submit"] == "Send"
        # A word the app wrote is the app's, even where it reads the same as
        # the framework's, and so is a subclass's own default.
        assert page.find("same").props["submit"] == "Save"
        assert page.find("sub").props["submit"] == "Go"
        assert page.find("same-dl").props["label"] == "Download"
        assert page.find("own-pie").props["data"][-1]["x"] == "Other"
        assert page.find("early").props["data"][-1]["x"] == "Overig"
        assert page.find("none").props["submit"] is None
        assert page.find("dl").props["label"] == "Downloaden"
        assert page.find("own-dl").props["label"] == "Get it"
        assert page.find("pie").props["data"][-1]["x"] == "Overig"
        await page.submit("form", {"name": "ab"})
        issues = {i["pointer"]: i["message"] for i in page.commands[-1].args["issues"]}
        assert issues == {"/name": "Minstens 3 tekens.", "/age": "Dit is verplicht."}
    async with TestApp(themed_app(tmp_path, Theme())).open("/") as page:
        assert page.find("form").props["submit"] == "Save"
        assert page.find("dl").props["label"] == "Download"


def test_an_upload_is_refused_in_the_themes_words(tmp_path: Path) -> None:
    def hello(ws: Any) -> None:
        ws.send_text(json.dumps({"seq": 1, "msg": {"type": "hello", "path": "/"}}))
        ws.receive_text()
        ws.receive_text()

    def refused(ws: Any, name: str, size: int, body: bytes | None = None) -> str:
        request = f"r-{name}"
        ws.send_text(
            json.dumps(
                {
                    "seq": 2,
                    "msg": {
                        "type": "request",
                        "request": request,
                        "node": "root/up",
                        "name": "upload",
                        "payload": {"name": name, "mime": "text/plain"},
                        "size": size,
                    },
                }
            )
        )
        if body is not None:
            ws.send_bytes(pack_frame(request, body))
        while True:
            msg = json.loads(ws.receive_text())["msg"]
            if msg.get("type") == "reply" and msg.get("request") == request:
                return str(msg["error"])

    big = 2 * 1024 * 1024
    dutch = DUTCH.model_copy(
        update={
            "strings": {
                **DUTCH.strings,
                "file_not_accepted": "dit soort bestand mag niet; wel {expected}",
                "file_not_text": "het bestand is geen tekst",
            }
        }
    )
    with (
        TestClient(themed_app(tmp_path, dutch).asgi) as client,
        client.websocket_connect("/_mw/ws") as ws,
    ):
        hello(ws)
        assert refused(ws, "big.txt", big) == "het bestand is groter dan 1 MB"
        assert refused(ws, "a.exe", 4) == "dit soort bestand mag niet; wel .txt"
        assert refused(ws, "b.txt", 4, b"\xff\xfe\xff\xfe") == "het bestand is geen tekst"
    with (
        TestClient(themed_app(tmp_path, Theme()).asgi) as client,
        client.websocket_connect("/_mw/ws") as ws,
    ):
        hello(ws)
        assert refused(ws, "big.txt", big) == "the file is larger than 1 MB"
        assert refused(ws, "a.exe", 4) == "this type of file is not accepted; expected .txt"
    # The reason itself stays as written, for the log and for a test, and a
    # refusal of the app's own has no theme string and is read as it is.
    with pytest.raises(Reject) as caught:
        mw.Files(tmp_path).begin(None, "a.exe", accept=[".txt"])  # type: ignore[arg-type]
    assert caught.value.reason == ".exe is not accepted; expected .txt"
    assert caught.value.key == "file_not_accepted" and caught.value.vars == {"expected": ".txt"}
    assert Reject("we take no files on Fridays").key is None
    # Every refusal the framework words has its string, with the same blanks.
    for key in (k for k in STRINGS if k.startswith("file_")):
        assert Theme().text(key, mb=1, ext="pdf", expected=".txt")
