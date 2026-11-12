import json
from datetime import date
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, SecretStr
from starlette.testclient import TestClient

import millwork as mw
from millwork import ui
from millwork.forms import field_spec, file_fields, pointer_of, resolve_files, validate


class Recode(BaseModel):
    type: Literal["recode"] = "recode"
    source: str
    mapping: dict[str, str] = {}


class Bucket(BaseModel):
    type: Literal["bucket"] = "bucket"
    source: str
    edges: list[float] = Field(default_factory=list, title="Grenzen")


Operation = Annotated[Recode | Bucket, Field(discriminator="type")]


class Target(BaseModel):
    name: str = Field(title="Naam", description="Hoe de kolom gaat heten")
    weight: float = Field(1.0, ge=0, le=10, json_schema_extra={"widget": "slider"})


class Plan(BaseModel):
    title: str = Field(examples=["Q1 report"])
    language: Literal["nl", "en"] = "nl"
    tags: list[Literal["a", "b", "c"]] = []
    notes: str | None = Field(None, max_length=500)
    starts: date | None = None
    secret: SecretStr | None = None
    count: int = Field(3, ge=1, le=10)
    enabled: bool = True
    target: Target
    operations: list[Operation] = []


def by_name(fields: list[dict]) -> dict[str, dict]:
    return {f["name"]: f for f in fields}


def test_field_spec_covers_the_type_table() -> None:
    spec = by_name(field_spec(Plan)["fields"])
    assert spec["title"]["widget"] == "input" and spec["title"]["placeholder"] == "Q1 report"
    assert spec["title"]["required"] is True
    assert spec["language"]["widget"] == "select" and [
        o["value"] for o in spec["language"]["options"]
    ] == ["nl", "en"]
    assert spec["tags"]["widget"] == "checkboxes"
    assert spec["notes"]["widget"] == "textarea" and spec["notes"]["clearable"] is True
    assert spec["starts"]["widget"] == "date"
    assert spec["secret"]["widget"] == "password"
    assert spec["count"] == {
        **spec["count"],
        "widget": "number",
        "integer": True,
        "min": 1,
        "max": 10,
    }
    assert spec["enabled"]["widget"] == "switch"
    assert spec["target"]["widget"] == "fieldset"
    target = by_name(spec["target"]["fields"])
    assert target["name"]["label"] == "Naam" and target["name"]["help"] == "Hoe de kolom gaat heten"
    assert target["name"]["pointer"] == "/target/name"
    assert target["weight"]["widget"] == "slider" and target["weight"]["max"] == 10
    ops = spec["operations"]
    assert ops["widget"] == "list" and ops["item"]["widget"] == "union"
    assert ops["item"]["discriminator"] == "type"
    assert [v["tag"] for v in ops["item"]["variants"]] == ["recode", "bucket"]
    bucket = by_name(ops["item"]["variants"][1]["fields"])
    assert bucket["edges"]["label"] == "Grenzen" and "type" not in bucket
    json.dumps(field_spec(Plan))  # the whole thing is JSON


def test_validate_maps_errors_to_pointers() -> None:
    instance, issues = validate(
        Plan,
        {"title": "x", "count": 99, "target": {"weight": 3}, "operations": [{"type": "bucket"}]},
    )
    assert instance is None
    assert {i.pointer for i in issues} == {"/count", "/target/name", "/operations/0/source"}
    ok, issues = validate(Plan, {"title": "x", "target": {"name": "n"}})
    assert ok is not None and ok.target.weight == 1.0 and issues == []
    assert pointer_of(("a", 0, "b/c")) == "/a/0/b~1c"


class Settings(BaseModel):
    project_name: str = Field(min_length=2)
    trap: bool = True


def make_app(tmp_path) -> tuple[mw.App, list]:
    got: list = []
    app = mw.App("f", public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Form(
                model=Settings,
                key="f",
                initial={"project_name": "Ab"},
                on_submit=submit,
                labels={"/project_name": {"label": "Naam"}},
            )
        )

    async def submit(s: mw.Session, value: Settings) -> None:
        got.append(value)
        if value.project_name == "taken":
            raise ui.FormIssues([("/project_name", "already used")])

    return app, got


def send(ws, msg, seq=1):
    ws.send_text(json.dumps({"seq": seq, "msg": msg}))


def recv(ws):
    return json.loads(ws.receive_text())["msg"]


def test_form_submit_validates_before_the_handler(tmp_path) -> None:
    app, got = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        assert recv(ws)["type"] == "session"
        mount = recv(ws)
        form = mount["nodes"]["root/f"]
        assert "model" not in form["props"]
        assert form["props"]["initial"] == {"project_name": "Ab"}
        assert form["props"]["schema"]["fields"][0]["label"] == "Naam"
        send(
            ws,
            {"type": "event", "node": "root/f", "name": "submit", "payload": {"project_name": "x"}},
        )
        msg = recv(ws)
        assert msg["type"] == "command" and msg["name"] == "form_issues"
        assert msg["args"]["issues"][0]["pointer"] == "/project_name"
        assert got == []
        send(
            ws,
            {
                "type": "event",
                "node": "root/f",
                "name": "submit",
                "payload": {"project_name": "fine", "trap": False},
            },
        )
        msg = recv(ws)
        assert msg == {
            "type": "command",
            "name": "form_issues",
            "args": {"node": "root/f", "issues": []},
        }
        assert got[0].project_name == "fine" and got[0].trap is False
        send(
            ws,
            {
                "type": "event",
                "node": "root/f",
                "name": "submit",
                "payload": {"project_name": "taken"},
            },
        )
        msg = recv(ws)
        assert msg["args"]["issues"] == [
            {"pointer": "/project_name", "message": "already used", "code": None}
        ]


class Attach(BaseModel):
    file: mw.FileRef | None = Field(None, json_schema_extra={"accept": [".pdf"]})
    extras: list[mw.FileRef] = Field(default_factory=list, json_schema_extra={"max_files": 2})
    note: str = ""


def test_file_fields_and_draft_resolution() -> None:
    spec = field_spec(Attach)
    fields = by_name(spec["fields"])
    assert fields["file"]["widget"] == "file" and fields["file"]["clearable"] is True
    assert fields["file"]["accept"] == [".pdf"]
    assert fields["extras"]["widget"] == "files" and fields["extras"]["max_files"] == 2
    assert set(file_fields(spec)) == {"/file", "/extras"}
    # The tab echoes file dicts; the session's own records take their place, or None.
    known = {"a": "REF-A"}
    draft = resolve_files(
        {
            "file": {"id": "a", "name": "x.pdf", "size": 1, "mime": "application/pdf", "url": "/u"},
            "extras": [{"id": "zz", "name": "y", "size": 1, "mime": "text/plain"}],
            "note": {"id": "not a file"},
        },
        known.get,
    )
    assert draft == {"file": "REF-A", "extras": [None], "note": {"id": "not a file"}}


class Strict(BaseModel):
    model_config = {"extra": "forbid"}
    name: str


async def test_forms_over_the_wire_nested_lists_unions_and_rejections(tmp_path) -> None:
    from millwork.testing import TestApp

    got: list = []
    app = mw.App("fw", public=None, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Form(
                Plan,
                key="plan",
                initial=Plan(title="Init", target=Target(name="t")),
                fields=["title", "target", "operations"],
                labels={"language": {"choices": [("nl", "Dutch")]}},
                on_submit=submit,
                on_cancel=lambda s, _: got.append("cancelled"),
            ),
            ui.Form(Strict, key="strict", on_submit=lambda s, v: got.append(v)),
            ui.Form(Strict, key="ro", read_only=True, on_submit=lambda s, v: got.append(v)),
            ui.Form(Strict, key="off", disabled=True, on_submit=lambda s, v: got.append(v)),
        )

    async def submit(s: mw.Session, value: Plan) -> None:
        got.append(value)
        if value.target.name == "dup":
            raise ui.FormIssues([("/target/name", "exists"), ("/operations/0/source", "unknown")])

    async with TestApp(app).open("/") as page:
        form = page.find("plan")
        # ``fields`` narrows and orders the spec; ``initial`` as a model lands as JSON.
        assert [f["name"] for f in form.props["schema"]["fields"]] == [
            "title",
            "target",
            "operations",
        ]
        assert form.props["initial"]["title"] == "Init" and "model" not in form.props

        # Nested and list errors come back at their pointers, with pydantic's codes.
        await page.submit(form, {"title": "x", "target": {}, "operations": [{"type": "bucket"}]})
        issues = page.commands[-1].args["issues"]
        assert {i["pointer"]: i["code"] for i in issues} == {
            "/target/name": "missing",
            "/operations/0/source": "missing",
        }
        # A draft that is not even an object is an issue at the root, not a crash.
        await page.submit(form, "not a form")
        assert page.commands[-1].args["issues"][0]["pointer"] == "/"
        assert got == []

        # A valid union list reaches the handler as model instances.
        await page.submit(
            form,
            {
                "title": "ok",
                "target": {"name": "n"},
                "operations": [
                    {"type": "recode", "source": "q1", "mapping": {"1": "a"}},
                    {"type": "bucket", "source": "q2", "edges": [1, 2.5]},
                ],
            },
        )
        plan = got[-1]
        assert isinstance(plan.operations[0], Recode) and isinstance(plan.operations[1], Bucket)
        assert plan.operations[1].edges == [1.0, 2.5]
        assert page.commands[-1].name == "form_issues" and page.commands[-1].args["issues"] == []

        # The handler's own issues land at nested pointers, and no acknowledgement follows.
        await page.submit(form, {"title": "ok", "target": {"name": "dup"}, "operations": []})
        assert [i["pointer"] for i in page.commands[-1].args["issues"]] == [
            "/target/name",
            "/operations/0/source",
        ]
        await page.event(form, "cancel")
        assert got[-1] == "cancelled"

        # A strict model reports a stray key; read-only and disabled forms take no submit.
        await page.submit("strict", {"name": "a", "extra": 1})
        assert page.commands[-1].args["issues"][0]["pointer"] == "/extra"
        before = len(page.commands)
        with pytest.raises(LookupError, match="is read-only"):
            await page.submit("ro", {"name": "a"})
        with pytest.raises(LookupError, match="is disabled"):
            await page.submit("off", {"name": "a"})
        assert len(page.commands) == before and not any(isinstance(v, Strict) for v in got)


def test_form_initial_must_be_a_model_or_a_mapping() -> None:
    from millwork.nodes import build

    with pytest.raises(TypeError):
        build(ui.Form(Strict, key="f", initial=["nope"]))
    node = build(ui.Form(Strict, key="f", initial=Strict(name="n"))).nodes["root"]
    assert node.props["initial"] == {"name": "n"}
    assert node.props["schema"]["fields"][0]["name"] == "name"


def test_overrides_merge_into_the_spec_and_the_key_names_the_form_element() -> None:
    from millwork.nodes import build

    class Inner(BaseModel):
        level: int = 1

    class Model(BaseModel):
        name: str = ""
        mood: str = "ok"
        inner: Inner = Inner()

    form = ui.Form(
        Model,
        key="settings",
        overrides={
            "name": {"placeholder": "Who?", "help": "Full name"},
            "/mood": {"choices": [("ok", "Fine"), ("bad", "Not fine")]},
            "/inner/level": {"widget": "slider", "min": 0, "max": 5},
        },
    )
    props = build(form).nodes["root"].props
    by_name = {f["name"]: f for f in props["schema"]["fields"]}
    assert by_name["name"]["placeholder"] == "Who?" and by_name["name"]["help"] == "Full name"
    assert by_name["mood"]["widget"] == "select"
    assert by_name["mood"]["options"] == [
        {"value": "ok", "label": "Fine"},
        {"value": "bad", "label": "Not fine"},
    ]
    level = by_name["inner"]["fields"][0]
    assert level["widget"] == "slider" and level["min"] == 0 and level["max"] == 5
    assert props["form_id"] == "settings"
    assert build(ui.Button("Save", form="settings")).nodes["root"].props["form"] == "settings"


def test_dates_and_multiselect_hints_reach_the_spec() -> None:
    import datetime as dt
    from typing import Literal

    class Model(BaseModel):
        when: dt.date = Field(json_schema_extra={"min_date": "2025-01-01"})
        tags: list[Literal["a", "b", "c"]] = Field(
            default=[], max_length=2, json_schema_extra={"widget": "multiselect", "sortable": True}
        )
        plain: list[Literal["a", "b"]] = []

    by_name = {f["name"]: f for f in field_spec(Model)["fields"]}
    assert by_name["when"]["widget"] == "date" and by_name["when"]["min_date"] == "2025-01-01"
    assert by_name["tags"]["widget"] == "multiselect" and by_name["tags"]["max_items"] == 2
    assert by_name["tags"]["sortable"] is True and "sortable" not in by_name["plain"]


def test_factory_defaults_reach_the_spec() -> None:
    class Inner(BaseModel):
        tags: list[str] = Field(default_factory=lambda: ["a"])

    class Model(BaseModel):
        when: date = Field(default_factory=lambda: date(2026, 1, 2))
        inner: Inner = Field(default_factory=Inner)
        maybe: Inner | None = None
        plain: int

    by_name = {f["name"]: f for f in field_spec(Model)["fields"]}
    assert by_name["when"]["default"] == "2026-01-02" and not by_name["when"]["required"]
    assert by_name["plain"]["required"]
    inner = {f["name"]: f for f in by_name["inner"]["fields"]}
    assert inner["tags"]["default"] == ["a"]
    maybe = {f["name"]: f for f in by_name["maybe"]["fields"]}
    assert maybe["tags"]["default"] == ["a"]


def test_an_unstable_factory_gives_the_form_no_default() -> None:
    from itertools import count
    from uuid import uuid4

    class Variant(BaseModel):
        kind: Literal["v"] = "v"
        tags: list[str] = Field(default_factory=lambda: ["x"])

    ticks = count()

    class Model(BaseModel):
        id: str = Field(default_factory=lambda: uuid4().hex)
        n: int = Field(default_factory=lambda: next(ticks))
        v: Variant | int = Field(default_factory=Variant)

    by_name = {f["name"]: f for f in field_spec(Model)["fields"]}
    assert "default" not in by_name["id"] and not by_name["id"]["required"]
    assert "default" not in by_name["n"]
    assert field_spec(Model)["fields"] == field_spec(Model)["fields"]
    assert by_name["v"]["default"] == {"kind": "v", "tags": ["x"]}


def test_a_choice_keeps_what_an_option_carries() -> None:
    from millwork.nodes import build

    class Model(BaseModel):
        plan: Literal["free", "pro", "team"] = "free"
        size: int = Field(
            1, json_schema_extra={"choices": [{"value": 1, "icon": "star"}, (2, "Two")]}
        )
        tone: str = "a"

    form = ui.Form(
        Model,
        labels={
            "plan": {
                "choices": [
                    ui.Option(value="free", label="Free", icon="heart", group="Open"),
                    ui.Option(value="pro", description="For a few"),
                    ui.Option(value="team", label="Team (sold out)", disabled=True),
                ]
            },
            "tone": {"choices": ["a", "b"]},
        },
    )
    fields = {f["name"]: f for f in build(form).nodes["root"].props["schema"]["fields"]}
    assert fields["plan"]["options"] == [
        {"value": "free", "label": "Free", "group": "Open", "icon": "heart"},
        {"value": "pro", "label": "pro", "description": "For a few"},
        {"value": "team", "label": "Team (sold out)", "disabled": True},
    ]
    # The value of a dict or a pair keeps its type, since the field holds it
    # when the choice is made.
    assert fields["size"]["options"] == [
        {"value": 1, "label": "1", "icon": "star"},
        {"value": 2, "label": "Two"},
    ]
    assert fields["tone"]["options"] == [{"value": "a", "label": "a"}, {"value": "b", "label": "b"}]
    assert fields["tone"]["widget"] == "select"
    with pytest.raises(ValueError, match="names its value"):
        build(ui.Form(Model, labels={"tone": {"choices": [{"label": "A"}]}}))
    # An icon the bundle does not draw fails here, as it does on an Option.
    with pytest.raises(ValueError, match="no icon named"):
        build(ui.Form(Model, labels={"tone": {"choices": [{"value": "a", "icon": "nope"}]}}))
