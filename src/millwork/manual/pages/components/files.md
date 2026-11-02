---
title: Files
order: 7
---

# Files

Files belong to the session. An upload becomes a `mw.FileRef` with an
id, a name, a size and a type. The bytes live on the server for as long as
the session does and travel to the browser over the session's own socket,
so a file has no URL and needs no signing.

## FileUpload

`ui.FileUpload` is a drop zone, or a button with `dropzone=False`.
`accept` lists extensions, `multiple` and `max_files` allow more than one,
and `max_size_mb` caps each. `on_upload` receives the `FileRef`s, and
`on_reject` receives `{name, reason}` for a file that was refused.

```python live
from pydantic import BaseModel


class Uploads(BaseModel):
    files: list = []


async def uploaded(s, refs):
    state(Uploads).files.extend(refs)


def example(s):
    st = state(Uploads)
    return ui.Stack(
        ui.FileUpload(
            accept=[".txt", ".md", ".png", ".pdf"],
            multiple=True,
            max_files=3,
            max_size_mb=5,
            on_upload=uploaded,
            on_reject=lambda s, r: s.toast(f"{r['name']}: {r['reason']}", tone="warning"),
        ),
        *(ui.FileCard(file=f, key=f.id) for f in st.files),
        gap=3,
    )
```

## FileCard

`ui.FileCard` shows a file with its size and kind, an optional `meta` line,
a `status` and `actions`. Given a `FileRef`, Open shows the bytes in a new
tab. Given a `url`, it links there.

```python live
from pydantic import BaseModel


class Held(BaseModel):
    ref: object = None


def example(s):
    st = state(Held)
    if st.ref is None:
        st.ref = s.files.add("Notes for the pilot.\n", name="notes.txt")
    return ui.Stack(
        ui.FileCard(
            file=st.ref,
            meta="added just now",
            actions=[ui.MenuItem(id="remove", label="Remove", icon="trash-2", destructive=True)],
            on_action=lambda s, a: s.toast(f"{a} requested"),
        ),
        ui.FileCard(
            name="report.pdf", size=482_000, kind="pdf", status="loading", meta="converting"
        ),
        ui.FileCard(
            name="broken.csv", size=12, kind="text", status="error", meta="could not parse"
        ),
        gap=2,
    )
```

## Image and Pdf

`ui.Image` and `ui.Pdf` take a `FileRef` or an outside URL. An image has
a `size` and a `fit`, and a PDF a `page` and a `height`. The browser's own
viewer shows the PDF, so a form or a link inside it looks like part of the
app. Show files the app made or the person uploaded themselves, and keep
documents from strangers out of it.

```python live
import struct, zlib

from pydantic import BaseModel


def png(w=48, h=48, rgb=(10, 126, 164)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class Pic(BaseModel):
    ref: object = None


def example(s):
    st = state(Pic)
    if st.ref is None:
        st.ref = s.files.add(png(), name="square.png")
    return ui.Row(
        ui.Image(src=st.ref, alt="A teal square", size="sm"),
        ui.Image(
            src="https://picsum.photos/seed/millwork/160/96",
            alt="An outside image",
            size="sm",
            fit="cover",
        ),
        gap=4,
    )
```

A PDF the session holds shows the same way, from its bytes.

```python live
from pydantic import BaseModel


def tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 40 120 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 320 180] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out

class Doc(BaseModel):
    ref: object = None

def example(s):
    st = state(Doc)
    if st.ref is None:
        st.ref = s.files.add(tiny_pdf("Hello from millwork"), name="hello.pdf")
    return ui.Pdf(src=st.ref, height="14rem")
```

## Download

`ui.Download` is a button that saves a file. `content` is bytes, text, a
path, a callable that makes any of those on click, or a `FileRef`, which
saves straight away without a round trip. `s.download(filename, content)`
does the same from a handler, without a button.

```python live
def report() -> str:
    return "name,score\nAda,0.92\nGrace,0.88\n"


ui.Row(
    ui.Download("Text", filename="hello.txt", content="Hello from millwork.\n"),
    ui.Download(
        "Made on click", filename="report.csv", content=report, mime="text/csv", variant="primary"
    ),
    ui.Button(
        "From a handler",
        variant="outline",
        icon="download",
        on_click=lambda s, _: s.download("pushed.txt", "Sent by a handler.\n"),
    ),
    gap=2,
    wrap=True,
)
```
