"""The manual: Markdown pages with live examples, served by millwork itself.

A page is a Markdown file under ``pages/``. A fenced block marked ``python live``
is executed and rendered inline as the component it produces, with its source
beneath it, so every example in the manual runs. The same blocks are the
gallery a bundle upgrade is judged against and the coverage the tests check.

The block contract: the code runs with ``mw`` and ``ui`` in scope and imports
the rest, as an app would. It either defines ``example(s)``, a page function over the session,
or ends in an expression that is the component. ``state(Model)`` returns an
instance of ``Model`` kept for this block on the session, so an example can
hold state across events.
"""

from __future__ import annotations

import ast
import logging
import re
import sys
import traceback
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, create_model
from starlette.responses import PlainTextResponse

import millwork as mw
from millwork import ui
from millwork.reference import reference

log = logging.getLogger("millwork.manual")

PAGES = Path(__file__).parent / "pages"
PUBLIC = Path(__file__).parent / "public"
COMPONENTS = Path(__file__).parent / "components"
HIT_LINK = "block px-2 pt-1.5 text-sm font-medium no-underline hover:underline"
NAV_LINK = (
    "block rounded-md px-2 py-1.5 text-sm text-muted-foreground no-underline "
    "hover:bg-sidebar-accent hover:text-foreground hover:no-underline"
)
_FENCE = re.compile(r"^```python live[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_INLINE = {"Button", "Badge", "Link", "Switch", "Checkbox", "Kbd", "Spinner", "Download"}


@dataclass
class Live:
    """One executable block: ``body`` runs, then ``example(s)`` or ``tail`` makes the view."""

    id: str
    source: str
    body: Any
    tail: Any  # a compiled expression, or None when the block defines example()


@dataclass
class Page:
    slug: str
    title: str
    chapter: str
    order: int
    segments: list[str | Live] = field(default_factory=list)


@dataclass
class Section:
    """A heading and what sits under it, for search: the prose and the live code."""

    page: Page
    heading: str
    anchor: str
    text: str
    code: str


@dataclass
class Hit:
    section: Section
    score: int
    snippet: str


def slugify(text: str) -> str:
    """A heading's anchor, the way the tab computes it for the rendered heading."""
    return re.sub(r"-+$|^-+", "", re.sub(r"[^a-z0-9]+", "-", text.lower()))


_HEADING = re.compile(r"^(#{1,3}) +(.+?)\s*$", re.M)


def index(pages: list[Page]) -> list[Section]:
    """Every heading of every page with its prose and code, in page order."""
    sections: list[Section] = []
    for page in pages:
        current: Section | None = None
        for seg in page.segments:
            if isinstance(seg, Live):
                if current is not None:
                    current.code += "\n" + seg.source
                continue
            pos = 0
            for m in _HEADING.finditer(seg):
                if current is not None:
                    current.text += "\n" + seg[pos : m.start()]
                heading = m.group(2)
                current = Section(page, heading, slugify(heading), "", "")
                sections.append(current)
                pos = m.end()
            if current is not None:
                current.text += "\n" + seg[pos:]
    return sections


def search(sections: list[Section], query: str, limit: int = 10) -> list[Hit]:
    """Sections where every word of the query appears, best first. A word in the
    heading or the page title counts most, in the prose next, in the code last."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    hits: list[Hit] = []
    for sec in sections:
        heading, title = sec.heading.lower(), sec.page.title.lower()
        text, code = sec.text.lower(), sec.code.lower()
        score = 0
        for term in terms:
            where = (
                (4 if term in heading else 0)
                + (3 if term in title else 0)
                + (2 if term in text else 0)
                + (1 if term in code else 0)
            )
            if where == 0:
                score = 0
                break
            score += where
        if score:
            hits.append(Hit(sec, score, _snippet(sec.text, terms)))
    hits.sort(key=lambda h: -h.score)
    return hits[:limit]


def _snippet(text: str, terms: list[str], width: int = 110) -> str:
    for line in text.splitlines():
        plain = line.strip()
        if plain and not plain.startswith("#") and any(t in plain.lower() for t in terms):
            return plain if len(plain) <= width else plain[: width - 1] + "…"
    return ""


def parse(text: str, slug: str) -> tuple[dict[str, str], list[str | Live]]:
    """Front matter and the body split into prose and live blocks."""
    meta: dict[str, str] = {}
    m = _FRONT.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end() :]
    segments: list[str | Live] = []
    pos = 0
    for n, block in enumerate(_FENCE.finditer(text)):
        prose = text[pos : block.start()].strip("\n")
        if prose.strip():
            segments.append(prose)
        segments.append(_compile(block.group(1), f"{slug}#{n}"))
        pos = block.end()
    rest = text[pos:].strip("\n")
    if rest.strip():
        segments.append(rest)
    return meta, segments


def _compile(source: str, block_id: str) -> Live:
    tree = ast.parse(source, filename=block_id)
    defines_example = any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "example"
        for node in tree.body
    )
    tail = None
    if not defines_example and tree.body and isinstance(tree.body[-1], ast.Expr):
        last = tree.body.pop()
        assert isinstance(last, ast.Expr)
        tail = compile(ast.Expression(last.value), block_id, "eval")
    elif not defines_example:
        raise ValueError(f"live block {block_id} neither defines example() nor ends in a view")
    body = compile(tree, block_id, "exec")
    return Live(id=block_id, source=source.rstrip("\n"), body=body, tail=tail)


def load(root: Path = PAGES) -> list[Page]:
    pages: list[Page] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).with_suffix("")
        parts = list(rel.parts)
        slug = "/" if parts == ["index"] else "/" + "/".join(parts)
        meta, segments = parse(path.read_text(encoding="utf-8"), slug)
        chapter = parts[0].replace("-", " ").title() if len(parts) > 1 else ""
        pages.append(
            Page(
                slug=slug,
                title=meta.get("title", rel.name.replace("-", " ").title()),
                chapter=chapter,
                order=int(meta.get("order", "100")),
                segments=segments,
            )
        )
    pages.sort(key=lambda p: (p.chapter != "", p.chapter, p.order, p.slug))
    return pages


def live_module_name(slug: str, session_id: str) -> str:
    return "millwork.manual.live" + slug.replace("/", ".") + "." + session_id


def page_namespace(slug: str = "", session_id: str = "") -> dict[str, Any]:
    """What every live block sees. Blocks on a page run in order and share it,
    so a later block may use what an earlier one defined.

    The namespace is a real module's, registered under a name, so a Pydantic
    model defined in a block can resolve its annotations the way it would in a
    file. One per session and page: a handler keeps what its own session
    defined, and the module goes when the session closes.
    """
    name = live_module_name(slug, session_id)
    module = sys.modules.get(name)
    if module is None:
        module = sys.modules[name] = types.ModuleType(name)
    ns = module.__dict__
    ns.clear()
    ns.update({"__name__": name, "mw": mw, "ui": ui})
    return ns


def field_name(model: str) -> str:
    """The state field a model lands in: ``Counter`` is ``s.state.counter``,
    ``EditorState`` is ``s.state.editor_state``."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", model).lower()


def state_model(pages: list[Page]) -> type[BaseModel]:
    """The manual's state, composed from the models its examples define, the way
    an app composes its own: one field per model, named after the class, made
    fresh for every session. A model that needs arguments to construct is a form
    model, not state, and gets no field. Two pages may define a model of one
    name only with the same fields, since the session keeps one instance.
    """
    models: dict[str, tuple[type[BaseModel], str]] = {}
    for page in pages:
        ns = page_namespace(page.slug, "load")
        for seg in page.segments:
            if isinstance(seg, Live):
                exec(seg.body, ns)
        for name, value in list(ns.items()):
            if not (isinstance(value, type) and issubclass(value, BaseModel)):
                continue
            if value is BaseModel or value.__module__ != ns["__name__"]:
                continue
            try:
                value()
            except ValidationError:
                continue
            if name in models and set(models[name][0].model_fields) != set(value.model_fields):
                raise ValueError(
                    f"{name} is defined with different fields on {models[name][1]} and "
                    f"{page.slug}; the manual's state holds one {name}"
                )
            models.setdefault(name, (value, page.slug))
        sys.modules.pop(ns["__name__"], None)
    fields: dict[str, Any] = {
        field_name(name): (cls, Field(default_factory=cls)) for name, (cls, _) in models.items()
    }
    return create_model("State", query=(str, ""), **fields)


def render_block(s: mw.Session[Any], live: Live, ns: dict[str, Any]) -> ui.Component:
    """Run a live block for this session; a failure shows as an alert, never a dead page."""
    try:
        exec(live.body, ns)
        view = eval(live.tail, ns) if live.tail is not None else ns["example"](s)
        if not isinstance(view, ui.Component):
            raise TypeError(f"the block produced a {type(view).__name__}, not a component")
        if view.wire_type() in _INLINE:
            # A lone button or badge keeps its natural width instead of stretching
            # across the card, which is how it sits in a real page too.
            return ui.Row(view, wrap=True)
        return view
    except Exception:
        log.exception("live block %s failed", live.id)
        return ui.Alert(
            title="This example failed",
            description=traceback.format_exc(limit=3),
            tone="destructive",
        )


def specimen(view: ui.Component, source: str) -> ui.Component:
    """A live example: the component on a soft panel, its source beneath, one frame."""
    return ui.Stack(
        ui.Stack(
            view,
            cls="rounded-t-lg border border-b-0 bg-muted/40 px-6 py-6",
        ),
        ui.Code(
            content=source,
            language="python",
            max_height="24rem",
            cls="rounded-t-none border border-border [&_pre]:rounded-t-none",
        ),
        gap=0,
        cls="min-w-0",
    )


def make_app(theme: Any = None) -> mw.App:
    """The manual as an app, one page per Markdown file."""
    pages = load()
    sections = index(pages)
    State = state_model(pages)  # noqa: N806
    # The manual's own look: the mainlines colours, Inter and the mark, from the
    # package's public folder. A theme passed in replaces it.
    # The manual is public: live sessions are capped, and the uploads its
    # examples take are bounded per session and in all.
    app = mw.App(
        "millwork manual",
        state=State,
        public=PUBLIC,
        components=COMPONENTS,
        theme=theme,
        max_sessions=300,
        files=mw.Files(max_session_mb=10, default_max_mb=10, max_total_mb=200),
    )

    def llms(request: Any) -> PlainTextResponse:
        return PlainTextResponse(reference())

    app.route("/llms.txt", llms)

    def results(query: str) -> list[ui.Component]:
        found = search(sections, query)
        if not found:
            return [ui.Text("Nothing matches.", variant="muted", cls="px-2 py-1.5 text-sm")]
        items: list[ui.Component] = []
        for hit in found:
            sec = hit.section
            items.append(
                ui.Stack(
                    ui.Link(label=sec.heading, href=f"{sec.page.slug}#{sec.anchor}", cls=HIT_LINK),
                    ui.Text(
                        sec.page.title + (f" · {hit.snippet}" if hit.snippet else ""),
                        variant="caption",
                        cls="px-2 text-muted-foreground",
                        truncate=True,
                    ),
                    gap=0,
                    cls="min-w-0",
                )
            )
        return items

    def nav(current: Page, query: str) -> ui.Sidebar:
        box = ui.Input(
            value=query,
            kind="search",
            prefix_icon="search",
            placeholder="Search the manual",
            clearable=True,
            debounce_ms=200,
            on_change=lambda s, v: setattr(s.state, "query", v or ""),
            on_submit=first_hit,
            cls="mb-2",
        )
        if query.strip():
            return ui.Sidebar(box, *results(query), title="Manual")
        items: list[ui.Component] = [box]
        chapter = None
        for p in pages:
            if p.chapter != chapter:
                chapter = p.chapter
                if chapter:
                    items.append(
                        ui.Text(
                            chapter.upper(),
                            variant="caption",
                            cls="mt-5 mb-1 px-2 tracking-wider text-muted-foreground",
                        )
                    )
            if p is current:
                items.append(
                    ui.Text(
                        p.title,
                        cls="rounded-md bg-sidebar-accent px-2 py-1.5 text-sm font-medium",
                    )
                )
            else:
                items.append(
                    ui.Link(
                        label=p.title,
                        href=p.slug,
                        cls=NAV_LINK,
                    )
                )
        return ui.Sidebar(*items, title="Manual")

    async def first_hit(s: mw.Session[Any], query: str) -> None:
        """Enter in the search box opens the best match."""
        s.state.query = query or ""
        found = search(sections, query)
        if found:
            s.navigate(f"{found[0].section.page.slug}#{found[0].section.anchor}")

    def register(page: Page) -> None:
        def drop_namespace(s: mw.Session[Any]) -> None:
            sys.modules.pop(live_module_name(page.slug, s.id), None)

        @app.page(page.slug, title=f"{page.title} · millwork")
        def view(s: mw.Session[Any]) -> ui.Component:
            body: list[ui.Component] = []
            ns = page_namespace(page.slug, s.id)
            for seg in page.segments:
                if isinstance(seg, str):
                    body.append(ui.Markdown(seg))
                else:
                    body.append(specimen(render_block(s, seg, ns), seg.source))
            return ui.Page(
                nav(page, s.state.query),
                ui.Stack(*body, gap=6, cls="mx-auto w-full min-w-0 max-w-3xl py-6"),
                header=ui.Header(
                    ui.Link(
                        label="GitHub",
                        href="https://github.com/DvGils/millwork",
                        target="_blank",
                        icon="external-link",
                        cls="text-sm text-muted-foreground hover:text-foreground",
                    ),
                    title="millwork",
                ),
            )

        view.close(drop_namespace)

    for page in pages:
        register(page)
    return app


app = make_app()

__all__ = [
    "Hit",
    "Live",
    "Page",
    "app",
    "field_name",
    "load",
    "make_app",
    "page_namespace",
    "parse",
    "render_block",
    "search",
    "state_model",
    "Section",
    "index",
    "slugify",
]
