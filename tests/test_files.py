import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

import millwork as mw
from millwork import ui
from millwork.files import Files, Reject, check_content, safe_name
from millwork.protocol import pack_frame, unpack_frame

NO_COMPONENT = "no upload component for this node"


def make_app(tmp_path: Path) -> tuple[mw.App, dict[str, Any]]:
    seen: dict[str, Any] = {}
    app = mw.App(
        "files",
        public=None,
        bundle_dir=tmp_path / "nobundle",
        secret="s3cret",
        files=Files(tmp_path / "files", default_max_mb=1),
    )

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        files = s.files.all()
        return ui.Page(
            ui.FileUpload(key="up", accept=[".pdf", ".txt"], max_size_mb=1, on_upload=uploaded),
            ui.FileUpload(key="any", on_upload=uploaded),
            ui.FileUpload(key="off", disabled=True, on_upload=uploaded),
            ui.FileCard(key="card", file=files[0]) if files else None,
            ui.Download(
                "Get", key="dl", filename="out.txt", content=lambda: "hello " + str(len(files))
            ),
        )

    async def uploaded(s: mw.Session, refs: list[mw.FileRef]) -> None:
        seen.setdefault("refs", []).extend(refs)

    return app, seen


def send(ws: Any, msg: dict[str, Any]) -> None:
    ws.send_text(json.dumps({"seq": 1, "msg": msg}))


def recv(ws: Any) -> dict[str, Any]:
    return json.loads(ws.receive_text())["msg"]


def upload(
    ws: Any,
    node: str,
    name: str | None,
    body: bytes,
    mime: str | None = None,
    field: str | None = None,
    *,
    size: int | None = None,
    rid: str = "u",
    chunk: int = 1000,
) -> dict[str, Any]:
    """An upload as the tab does it: the request, the bytes in frames, the reply."""
    payload: dict[str, Any] = {"name": name, "mime": mime}
    if field is not None:
        payload["field"] = field
    msg = {"type": "request", "node": node, "name": "upload", "request": rid, "payload": payload}
    msg["size"] = len(body) if size is None else size
    send(ws, msg)
    for i in range(0, len(body), chunk):
        ws.send_bytes(pack_frame(rid, body[i : i + chunk]))
    while True:
        reply = recv(ws)
        if reply["type"] == "reply" and reply["request"] == rid:
            return reply


def fetch(ws: Any, file_id: str, rid: str = "f") -> tuple[dict[str, Any] | None, bytes]:
    """A file as the tab fetches it: head, frames, reply. ``(head, bytes)``; no head on error."""
    send(
        ws,
        {"type": "request", "node": "", "name": "file", "request": rid, "payload": {"id": file_id}},
    )
    head: dict[str, Any] | None = None
    data = b""
    while True:
        m = ws.receive()
        if "bytes" in m and m["bytes"] is not None:
            frid, chunk = unpack_frame(m["bytes"])
            assert frid == rid
            data += chunk
            continue
        msg = json.loads(m["text"])["msg"]
        if msg["type"] == "head" and msg["request"] == rid:
            head = msg["payload"]
        elif msg["type"] == "reply" and msg["request"] == rid:
            if msg["error"]:
                assert head is None and not data
                return None, b""
            assert head is not None and len(data) == head["size"] == msg["payload"]["size"]
            return head, data


def test_content_checks_and_names() -> None:
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("my report (v2).docx") == "my report (v2).docx"
    check_content("a.pdf", b"%PDF-1.7 ...")
    check_content("a.docx", b"PK\x03\x04rest")
    check_content("a.png", b"\x89PNG\r\n")
    with pytest.raises(Reject):
        check_content("a.png", b"GIF89a")
    with pytest.raises(Reject):
        check_content("a.txt", b"\xff\xfe\x00bad")
    with pytest.raises(Reject):
        check_content("a.pdf", b"")
    check_content("a.bin", b"\x00\x01")  # unknown extension: only non-empty is required
    # A long name is cut in the stem; its extension, and so its type, survives.
    assert safe_name("n" * 300 + ".pdf") == "n" * 196 + ".pdf"
    assert safe_name("n" * 300) == "n" * 200
    # Names Windows cannot write get a prefix; trailing dots and spaces go.
    assert safe_name("CON.txt") == "_CON.txt" and safe_name("nul") == "_nul"
    assert safe_name("com1.csv") == "_com1.csv" and safe_name("common.csv") == "common.csv"
    assert safe_name("report. ") == "report" and safe_name("...") == "file"
    assert safe_name("." * 300) == "file"
    cut = safe_name("n" * 300 + ".tar.gz")
    assert len(cut) == 200 and cut.endswith(".gz")
    long_suffix = safe_name("n" * 300 + "." + "e" * 30)
    assert len(long_suffix) == 200 and long_suffix.endswith("." + "e" * 19)


class Attach(BaseModel):
    file: mw.FileRef
    note: str = ""


async def test_store_streams_limits_quota_and_names(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    app, _ = make_app(tmp_path)
    app.files.max_session_bytes = 1024 * 1024
    async with TestApp(app).open("/") as page:
        s = page.session
        files = app.files
        pulled: list[int] = []

        def chunks(parts: list[bytes]) -> Any:
            for i, part in enumerate(parts):
                pulled.append(i)
                yield part

        # The size limit stops the stream where it is crossed; nothing is left on disk.
        with pytest.raises(Reject) as info:
            files.store(s, "big.txt", chunks([b"x" * 600, b"y" * 600, b"z"]), max_bytes=1000)
        assert info.value.status == 413 and pulled == [0, 1]
        assert list(files.session_dir(s.id).iterdir()) == []
        # A bad header is rejected as soon as it is readable, before the body streams in.
        pulled.clear()
        with pytest.raises(Reject, match="valid .pdf"):
            files.store(s, "a.pdf", chunks([b"not a pdf at all", b"more", b"more"]))
        assert pulled == [0]
        # A header split across chunks is still checked once it is readable.
        files.store(s, "ok.pdf", chunks([b"%PD", b"F-1.7 and the rest"]))
        with pytest.raises(Reject, match="valid .pdf"):
            files.store(s, "split.pdf", chunks([b"no", b"t a pdf at all, really"]))
        assert sorted(f.name for f in s.files.all()) == ["ok.pdf"]
        # The quota counts what the session already holds.
        files.store(s, "a.bin", chunks([b"a" * 700_000]), max_bytes=2_000_000)
        with pytest.raises(Reject, match="quota"):
            files.store(s, "b.bin", chunks([b"b" * 400_000]), max_bytes=2_000_000)
        assert len(s.files.all()) == 2  # ok.pdf and a.bin; the rejected one is gone
        # Accept lists work with or without the dot, case-insensitively.
        ref = files.store(s, "Notes.TXT", [b"hi"], accept=["txt"])
        assert ref.mime == "text/plain" and ref.kind == "text"
        with pytest.raises(Reject, match="not accepted"):
            files.store(s, "notes.md", [b"hi"], accept=[".TXT"])
        # Names are basenames, cleaned, and cut to a sane length; empty chunks are skipped.
        ref = files.store(s, "dir/" + "n" * 300 + ".csv", [b"", b"a,b", b""])
        assert ref.name.endswith(".csv") and len(ref.name) == 200 and ref.size == 3
        assert safe_name("we|rd:name?.txt") == "we_rd_name_.txt"

        # Kinds by MIME, for the card and the viewer.
        kinds = {
            n: s.files.add(b"\x00", name=n).kind
            for n in ("p.png", "d.pdf", "s.mp3", "v.mp4", "j.json", "z.zip", "x.unknownext")
        }
        assert kinds == {
            "p.png": "image",
            "d.pdf": "pdf",
            "s.mp3": "audio",
            "v.mp4": "video",
            "j.json": "text",
            "z.zip": "file",
            "x.unknownext": "file",
        }
        # Server-side data: text, bytes and an existing path all become session files.
        (tmp_path / "src.txt").write_text("from disk")
        assert s.files.add("text", name="t.txt").path.read_text() == "text"
        assert s.files.add(tmp_path / "src.txt", name="copy.txt").path.read_text() == "from disk"
        assert s.files.add(b"\x01\x02", name="raw", mime="application/x-raw").mime == (
            "application/x-raw"
        )


def test_root_permissions_and_sweep(tmp_path: Path) -> None:
    import os
    import time as _time

    files = Files(tmp_path / "root")
    files._ensure_root()
    if os.name == "posix":
        os.chmod(files.root, 0o755)
        files._ensure_root()
        assert files.root.stat().st_mode & 0o777 == 0o700
    old, new = files.root / "old-session", files.root / "new-session"
    old.mkdir()
    new.mkdir()
    (old / "f").write_bytes(b"x")
    stale = _time.time() - 10_000
    os.utime(old, (stale, stale))
    assert files.sweep(older_than=3600) == 1
    assert not old.exists() and new.exists()
    assert Files(tmp_path / "nowhere").sweep(older_than=1) == 0


async def test_remove_deletes_the_file_and_frees_its_quota(tmp_path: Path) -> None:
    from millwork.testing import TestApp

    app, _ = make_app(tmp_path)
    app.files.max_session_bytes = 10
    async with TestApp(app).open("/") as page:
        s = page.session
        ref = s.files.add(b"x" * 8, name="a.bin")
        with pytest.raises(Reject):
            s.files.add(b"x" * 8, name="b.bin")
        assert s.files.remove(ref.id) and not ref.path.exists()
        assert s.files.get(ref.id) is None and s.files.all() == []
        assert not s.files.remove(ref.id)
        assert s.files.add(b"x" * 8, name="b.bin").size == 8


def test_upload_validate_fetch_and_download(tmp_path: Path) -> None:
    app, seen = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        info = recv(ws)
        assert recv(ws)["type"] == "mount"
        sid = info["id"]

        # The node's spec and the content checks gate the upload.
        assert upload(ws, "root/nope", "a.txt", b"hi")["error"] == NO_COMPONENT
        assert upload(ws, "root/off", "a.txt", b"hi")["error"] == NO_COMPONENT
        assert "not accepted" in upload(ws, "root/up", "x.exe", b"MZ..")["error"]
        assert "valid .pdf" in upload(ws, "root/up", "fake.pdf", b"not a pdf at all......")["error"]
        # The announced size is checked before a byte arrives; the real size as it streams.
        r = upload(ws, "root/up", "big.txt", b"", size=5 * 1024 * 1024)
        assert r["error"] == "the file is larger than 1 MB"
        r = upload(ws, "root/up", "big.txt", b"x" * (1024 * 1024 + 1), size=10)
        assert "interrupted" in r["error"] or "larger" in r["error"]
        session_dir = app.files.session_dir(sid)
        assert not session_dir.exists() or not any(session_dir.glob("*"))

        r = upload(ws, "root/up", "../notes.txt", b"hello", "text/html")
        ref = r["payload"]
        # The name is a basename and the MIME comes from the extension, not the browser.
        assert r["error"] is None and ref["name"] == "notes.txt" and ref["size"] == 5
        assert ref["mime"] == "text/plain" and "path" not in ref and "url" not in ref

        # The handler receives FileRefs with paths; the page then shows a card.
        send(ws, {"type": "event", "node": "root/up", "name": "upload", "payload": [ref]})
        patch = recv(ws)
        card = next(op["node"] for op in patch["ops"] if op["op"] == "add")
        assert card["props"]["file"] == ref
        assert seen["refs"][0].path.read_bytes() == b"hello"
        # A file uploaded for one node is not handed to another node's handler.
        send(ws, {"type": "event", "node": "root/any", "name": "upload", "payload": [ref]})
        send(ws, {"type": "event", "node": "root/dl", "name": "download"})
        assert recv(ws)["name"] == "download"  # the upload event above produced nothing
        assert len(seen["refs"]) == 1

        # Fetching: the session's own files by id, as head, frames and reply.
        head, data = fetch(ws, ref["id"])
        assert head == {"name": "notes.txt", "mime": "text/plain", "size": 5} and data == b"hello"
        assert fetch(ws, "missing") == (None, b"")
        assert fetch(ws, "") == (None, b"")
        # An id from another session opens nothing here.
        other = Files(tmp_path / "other")
        assert fetch(ws, other.session_dir("x").name) == (None, b"")

        # A Download button: the callable runs on click, the command names the file.
        send(ws, {"type": "event", "node": "root/dl", "name": "download"})
        cmd = recv(ws)
        assert cmd["type"] == "command" and cmd["name"] == "download"
        assert cmd["args"]["filename"] == "out.txt"
        head, data = fetch(ws, cmd["args"]["id"])
        assert data == b"hello 1" and head["name"] == "out.txt"
        assert session_dir.is_dir()
    # The lifespan closed the session; its directory went with it.
    assert not session_dir.exists()


def test_an_upload_is_cancelled_or_interrupted_cleanly(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        info = recv(ws)
        recv(ws)
        sid = info["id"]
        payload = {"name": "a.txt", "mime": "text/plain"}
        send(
            ws,
            {
                "type": "request",
                "node": "root/up",
                "name": "upload",
                "request": "c",
                "payload": payload,
                "size": 10,
            },
        )
        ws.send_bytes(pack_frame("c", b"hello"))
        send(ws, {"type": "cancel", "request": "c"})
        assert recv(ws) == {"type": "reply", "request": "c", "payload": None, "error": "cancelled"}
        # Frames for a finished request are dropped, and the request id is free again.
        ws.send_bytes(pack_frame("c", b"world"))
        assert upload(ws, "root/up", "b.txt", b"fine", rid="c")["payload"]["name"] == "b.txt"
        # A request id in use is refused.
        send(
            ws,
            {
                "type": "request",
                "node": "root/up",
                "name": "upload",
                "request": "d",
                "payload": payload,
                "size": 4,
            },
        )
        send(
            ws,
            {
                "type": "request",
                "node": "root/up",
                "name": "upload",
                "request": "d",
                "payload": payload,
                "size": 4,
            },
        )
        assert recv(ws)["error"] == "duplicate request"
        ws.send_bytes(pack_frame("d", b"done"))
        assert recv(ws)["payload"]["name"] == "a.txt"
        # Nothing half-written is left behind.
        files = {p.name for p in app.files.session_dir(sid).glob("*")}
        session = app.sessions[sid]
        assert files == {f.path.name for f in session.files.all()} and len(files) == 2
        # Unknown and malformed frames never break the loop.
        ws.send_bytes(pack_frame("zzz", b"x"))
        ws.send_bytes(b"\xff")
        send(ws, {"type": "event", "node": "root/dl", "name": "download"})
        assert recv(ws)["name"] == "download"

    # The socket going away mid-upload fails the stream and leaves no file.
    with TestClient(app.asgi) as client:
        with client.websocket_connect("/_mw/ws") as ws:
            send(ws, {"type": "hello", "path": "/"})
            sid = recv(ws)["id"]
            recv(ws)
            send(
                ws,
                {
                    "type": "request",
                    "node": "root/up",
                    "name": "upload",
                    "request": "e",
                    "payload": payload,
                    "size": 10,
                },
            )
            ws.send_bytes(pack_frame("e", b"hello"))
            time.sleep(0.1)
        time.sleep(0.2)
        session = app.sessions[sid]
        assert session.files.all() == [] and not any(app.files.session_dir(sid).glob("*"))


def test_form_file_field_round_trip_and_download_by_id(tmp_path: Path) -> None:
    got: list[Any] = []
    app = mw.App("ff", public=None, bundle_dir=tmp_path, secret="s3cret", files=Files(tmp_path))

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        files = s.files.all()
        return ui.Page(
            ui.Form(Attach, key="f", on_submit=lambda s, v: got.append(v)),
            ui.Download("Get", key="dl", filename="x.txt", content=files[0]) if files else None,
        )

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        recv(ws)
        assert recv(ws)["type"] == "mount"
        # The field pointer must name a file field of the form.
        assert (
            upload(ws, "root/f", "a.txt", b"hi", field="/note")["error"]
            == "no file field at this pointer"
        )
        ref = upload(ws, "root/f", "a.txt", b"hi", field="/file")["payload"]
        # An unknown id validates as a missing file; the form reports the field.
        send(
            ws,
            {
                "type": "event",
                "node": "root/f",
                "name": "submit",
                "payload": {"file": {**ref, "id": "nope"}},
            },
        )
        msg = recv(ws)
        assert msg["name"] == "form_issues" and msg["args"]["issues"][0]["pointer"] == "/file"
        send(
            ws,
            {
                "type": "event",
                "node": "root/f",
                "name": "submit",
                "payload": {"file": ref, "note": "n"},
            },
        )
        msgs = [recv(ws), recv(ws)]
        assert got[0].file.path.read_bytes() == b"hi" and got[0].note == "n"
        # The render after the submit carries a Download whose button names the file itself.
        patch = next(m for m in msgs if m["type"] == "patch")
        dl = next(
            op["node"]
            for op in patch["ops"]
            if op["op"] == "add" and op["node"]["type"] == "Download"
        )
        assert dl["props"]["file_id"] == ref["id"] and "content" not in dl["props"]
        assert fetch(ws, ref["id"])[1] == b"hi"


def test_chat_and_form_uploads_take_their_specs_from_the_node(tmp_path: Path) -> None:
    class Batch(BaseModel):
        extras: list[mw.FileRef] = []

    app = mw.App("cu", public=None, bundle_dir=tmp_path, secret="s3cret", files=Files(tmp_path))

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Chat(
                key="chat", on_message=lambda s, t: None, attachments=ui.Accept(accept=[".txt"])
            ),
            ui.Chat(key="plain", on_message=lambda s, t: None),
            ui.Form(Batch, key="f", on_submit=lambda s, v: None),
            ui.Form(Batch, key="ro", read_only=True, on_submit=lambda s, v: None),
        )

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        sid = recv(ws)["id"]
        recv(ws)
        assert upload(ws, "root/chat", "a.txt", b"hi")["error"] is None
        assert "not accepted" in upload(ws, "root/chat", "a.md", b"hi")["error"]
        # A chat without attachments takes none at all.
        assert upload(ws, "root/plain", "a.txt", b"hi")["error"] == NO_COMPONENT
        # A list field's pointer carries the item index on the wire; the spec is found without it.
        r = upload(ws, "root/f", "sp ace.txt", b"hi", field="/extras/3")
        assert r["error"] is None and r["payload"]["name"] == "sp ace.txt"
        assert (
            upload(ws, "root/ro", "a.txt", b"hi", field="/extras")["error"]
            == "no upload component for this node"
        )
        # No name: the file is still stored, under a placeholder name.
        form_ref = upload(ws, "root/f", None, b"hi", field="/extras")["payload"]
        assert form_ref["name"] == "file"
        # A chat message only carries files uploaded for that chat.
        chat_ref = upload(ws, "root/chat", "b.txt", b"yo")["payload"]
        send(
            ws,
            {
                "type": "event",
                "node": "root/chat",
                "name": "message",
                "payload": {"text": "", "files": [chat_ref, form_ref, {"id": "zz"}, "junk"]},
            },
        )
        session = app.sessions[sid]
        assert recv(ws)["type"] == "patch"
        parts = session.chat("chat").messages[0].parts
        assert [p["filename"] for p in parts] == ["b.txt"] and parts[0]["url"] == ""


def test_download_contents_reach_the_tab_by_id(tmp_path: Path) -> None:
    app = mw.App("dl", public=None, bundle_dir=tmp_path, secret="s3cret", files=Files(tmp_path))
    (tmp_path / "report.csv").write_text("a,b\n1,2\n")

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(
            ui.Download("bytes", key="b", filename="track", content=b"\x00\x01", mime="audio/mpeg"),
            ui.Download("path", key="p", filename="r.csv", content=tmp_path / "report.csv"),
            ui.Download("call", key="c", filename="c.zip", content=lambda: b"PK\x03\x04zip"),
            ui.Download("bad", key="x", filename="x", content=42),
            ui.Download("off", key="off", filename="o.txt", content="no", disabled=True),
            ui.Button("push", key="push", on_click=push),
        )

    async def push(s: mw.Session, _: Any) -> None:
        ref = s.download("pushed.txt", "from a handler")
        s.toast(ref.name)

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        recv(ws)
        mount = recv(ws)
        # Only a session file names itself on the button; the rest fetch on click.
        assert all("file_id" not in mount["nodes"][f"root/{k}"]["props"] for k in "bpcx")

        send(ws, {"type": "event", "node": "root/b", "name": "download"})
        cmd = recv(ws)
        assert cmd["name"] == "download" and cmd["args"]["filename"] == "track"
        head, data = fetch(ws, cmd["args"]["id"])
        assert data == b"\x00\x01" and head["mime"] == "audio/mpeg"
        send(ws, {"type": "event", "node": "root/p", "name": "download"})
        assert fetch(ws, recv(ws)["args"]["id"])[1] == b"a,b\n1,2\n"
        send(ws, {"type": "event", "node": "root/c", "name": "download"})
        assert fetch(ws, recv(ws)["args"]["id"])[1] == b"PK\x03\x04zip"
        send(ws, {"type": "event", "node": "root/x", "name": "download"})
        assert recv(ws)["args"]["message"] == "The download failed."
        send(ws, {"type": "event", "node": "root/off", "name": "download"})
        send(ws, {"type": "event", "node": "root/push", "name": "click"})
        first, second = recv(ws), recv(ws)
        names = {m["name"]: m for m in (first, second)}
        assert set(names) == {"download", "toast"}  # the disabled button produced nothing
        assert names["toast"]["args"]["message"] == "pushed.txt"
        head, data = fetch(ws, names["download"]["args"]["id"])
        assert data == b"from a handler" and head["mime"] == "text/plain"


def test_text_check_allows_a_cut_character() -> None:
    check_content("note.txt", ("a" * 63 + "é").encode()[:64])  # cut inside the é
    check_content("note.csv", "é".encode()[:1])
    with pytest.raises(Reject):
        check_content("note.txt", b"a" * 10 + b"\xff\xfe")


def test_a_file_field_inside_a_list_row_uploads(tmp_path: Path) -> None:
    from millwork.forms import field_spec, file_fields

    class Item(BaseModel):
        title: str
        attachment: mw.FileRef | None = None

    class Batch(BaseModel):
        items: list[Item] = []

    spec = field_spec(Batch)
    item_fields = spec["fields"][0]["item"]["fields"]
    assert [f["pointer"] for f in item_fields] == ["/items/title", "/items/attachment"]
    assert "/items/attachment" in file_fields(spec)

    got: list[Any] = []
    app = mw.App("lf", public=None, bundle_dir=tmp_path, files=Files(tmp_path))

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Form(Batch, key="f", on_submit=lambda s, v: got.append(v)))

    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        recv(ws)
        assert recv(ws)["type"] == "mount"
        # The tab names the field by its draft pointer, index included.
        r = upload(ws, "root/f", "a.txt", b"hi", field="/items/0/attachment")
        assert r["error"] is None, r
        draft = {"items": [{"title": "t", "attachment": r["payload"]}]}
        send(ws, {"type": "event", "node": "root/f", "name": "submit", "payload": draft})
        for _ in range(10):
            m = recv(ws)
            if m["type"] == "command" and m["name"] == "form_issues":
                assert m["args"]["issues"] == []
                break
        else:
            raise AssertionError("no acknowledgement")
    assert got and got[0].items[0].attachment.name == "a.txt"


def test_a_file_streams_while_other_messages_flow(tmp_path: Path) -> None:
    """A request is not disturbed by events, renders and commands sent alongside it."""
    app, _ = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        recv(ws)
        recv(ws)
        ref = upload(ws, "root/up", "big.txt", b"x" * 600_000)["payload"]
        send(ws, {"type": "event", "node": "root/up", "name": "upload", "payload": [ref]})
        recv(ws)
        msg = {
            "type": "request",
            "node": "",
            "name": "file",
            "request": "f",
            "payload": {"id": ref["id"]},
        }
        send(ws, msg)
        send(ws, {"type": "event", "node": "root/dl", "name": "download"})
        send(ws, {"type": "event", "node": "root/dl", "name": "download"})
        data = b""
        commands = 0
        reply: dict[str, Any] | None = None
        while reply is None:
            m = ws.receive()
            if m.get("bytes"):
                data += unpack_frame(m["bytes"])[1]
                continue
            got = json.loads(m["text"])["msg"]
            if got["type"] == "command":
                commands += 1
            elif got["type"] == "reply":
                reply = got
        assert reply["error"] is None and len(data) == 600_000
        while commands < 2:
            got = recv(ws)
            commands += got["type"] == "command"


def test_abandoned_streams_never_block_the_receive_loop(tmp_path: Path) -> None:
    """Frames behind a refused upload, a sized non-upload request, or a cancel are
    dropped, and the socket keeps answering."""
    app, _ = make_app(tmp_path)
    with TestClient(app.asgi) as client, client.websocket_connect("/_mw/ws") as ws:
        send(ws, {"type": "hello", "path": "/"})
        recv(ws)
        recv(ws)
        alive = lambda: (  # noqa: E731
            send(ws, {"type": "event", "node": "root/dl", "name": "download"}),
            recv(ws)["name"],
        )[1]
        # A bad PDF is refused on the first frame; forty more frames follow it.
        body = b"not a pdf" * 5000
        r = upload(ws, "root/up", "x.pdf", body, chunk=1000)
        assert "valid .pdf" in r["error"]
        assert alive() == "download"
        # A file request with a size and frames behind it: no stream is opened.
        msg = {"type": "request", "node": "", "name": "file", "request": "z", "size": 50_000}
        send(ws, {**msg, "payload": {"id": "nope"}})
        for _ in range(40):
            ws.send_bytes(pack_frame("z", b"x" * 1000))
        assert recv(ws)["error"] == "no such file"
        assert alive() == "download"
        # A cancel right behind the request, before any frame.
        start = {"type": "request", "node": "root/up", "name": "upload", "request": "q"}
        send(ws, {**start, "payload": {"name": "a.txt"}, "size": 40_000})
        send(ws, {"type": "cancel", "request": "q"})
        for _ in range(40):
            ws.send_bytes(pack_frame("q", b"x" * 1000))
        assert recv(ws)["error"] == "cancelled"
        assert alive() == "download"
        # A request id that cannot head a frame is a bad message, not a dead socket.
        send(ws, {**msg, "request": "ü", "payload": {"id": "nope"}})
        send(ws, {**msg, "request": "x" * 33, "payload": {"id": "nope"}})
        assert alive() == "download"
        # An empty file is refused as such.
        assert upload(ws, "root/up", "e.txt", b"")["error"] == "the file is empty"
        # A tab may hold a bounded number of requests.
        for i in range(32):
            send(ws, {**start, "request": f"m{i}", "payload": {"name": "a.txt"}, "size": 10})
        send(ws, {**start, "request": "m99", "payload": {"name": "a.txt"}, "size": 10})
        assert recv(ws) == {
            "type": "reply",
            "request": "m99",
            "payload": None,
            "error": "too many requests",
        }
        for i in range(32):
            ws.send_bytes(pack_frame(f"m{i}", b"0123456789"))
        done = {recv(ws)["request"] for _ in range(32)}
        assert done == {f"m{i}" for i in range(32)}
        assert alive() == "download"
