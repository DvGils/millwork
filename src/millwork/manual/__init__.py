"""The manual: Markdown pages with live examples, served by millwork itself.

A page is a Markdown file under ``pages/``. A fenced block marked ``python live``
is executed and rendered inline as the component it produces, with its source
beneath it, so every example in the manual runs. The same blocks are the
gallery a bundle upgrade is judged against and the coverage the tests check.

The block contract: the code runs with ``mw`` and ``ui`` in scope and imports
the rest, as an app would. It either defines ``example(s)``, a page function
over the session, or ends in an expression that is the component. The manual's
state is composed from the models the blocks define, one field per model
named after the class, so an example holds state in ``s.state.<model>`` the
way an app holds it in a field of its own model.
"""

from __future__ import annotations

import ast
import functools
import logging
import re
import sys
import traceback
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, create_model
from starlette.responses import PlainTextResponse, RedirectResponse

import millwork as mw
from millwork import ui
from millwork.reference import reference
from millwork.search import SMALL, Doc, forms, rank, terms, tokens

log = logging.getLogger("millwork.manual")

PAGES = Path(__file__).parent / "pages"
PUBLIC = Path(__file__).parent / "public"
COMPONENTS = Path(__file__).parent / "components"
HIT_LINK = (
    "block px-2 pt-1.5 pb-0 text-sm font-medium text-primary "
    "hover:bg-transparent hover:text-primary hover:underline"
)
_FENCE = re.compile(r"^```(python live|cards)[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_INLINE = {"Button", "Badge", "Link", "Switch", "Checkbox", "Kbd", "Spinner", "Download"}

# The sidebar, top to bottom: a page at the root by its file name, or a folder
# of pages under a label, folded to the label until it is opened.
NAV: list[tuple[str, str]] = [
    ("index", ""),
    ("quickstart", ""),
    ("pages", "Pages"),
    ("state", "State"),
    ("sign-in", "Sign-in"),
    ("running", "Running"),
    ("theming", ""),
    ("testing", ""),
    ("components", "Components"),
]
GROUPS = {key: label for key, label in NAV if label}

# Where the chapters of earlier releases went; the old addresses answer with a redirect.
MOVED = {
    "/app/pages": "/pages/pages-and-routes",
    "/app/state": "/state/state-and-handlers",
    "/app/auth": "/sign-in/setup",
    "/app/theming": "/theming",
    "/app/testing": "/testing",
    "/app/running": "/running/development",
}


@dataclass
class Live:
    """One executable block: ``body`` runs, then ``example(s)`` or ``tail`` makes the view."""

    id: str
    source: str
    body: Any
    tail: Any  # a compiled expression, or None when the block defines example()


@dataclass
class Cards:
    """A row of cards that each open another page. A line names the page by
    slug, and may give the card its own title and text after ``|``."""

    slugs: list[str]
    titles: dict[str, str] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)


Segment = str | Live | Cards


@dataclass
class Page:
    slug: str
    title: str
    chapter: str
    order: int
    segments: list[Segment] = field(default_factory=list)
    group: str = ""
    description: str = ""
    related: list[str] = field(default_factory=list)
    # Words a section is found by that are not in it, by the section's
    # anchor: what the thing is called elsewhere.
    keywords: dict[str, str] = field(default_factory=dict)


@dataclass
class Section:
    """A heading and what sits under it, for search: the prose and the live
    code, the two in the order they stand in as Markdown, and the words the
    section is found by that are not in it."""

    page: Page
    heading: str
    anchor: str
    text: str
    code: str
    body: str = ""
    keywords: str = ""
    # Which of the sections of its page with this anchor it is, from 1.
    nth: int = 1

    @property
    def address(self) -> str:
        """Where the section is, as a lookup takes it: its page's path and
        its anchor, with a number behind it for a second section of the
        page that is called the same."""
        again = f"-{self.nth}" if self.nth > 1 else ""
        return f"{self.page.slug.strip('/') or 'index'}#{self.anchor}{again}"


@dataclass
class Hit:
    section: Section
    score: int
    snippet: str


def slugify(text: str) -> str:
    """A heading's anchor, the way the tab computes it for the rendered heading."""
    return re.sub(r"-+$|^-+", "", re.sub(r"[^a-z0-9]+", "-", text.lower()))


_HEADING = re.compile(r"^(#{1,3}) +(.+?)\s*$", re.M)
# Code in a page's prose that is shown and not run. A line in it that
# begins with ``#`` is a comment of the code and no heading of the page.
_SHOWN_CODE = re.compile(r"^```.*?^```[ \t]*$", re.M | re.S)


def _in_prose(pattern: re.Pattern[str], text: str) -> list[re.Match[str]]:
    """Where a pattern is found in a page's prose, outside the code in it."""
    code = [m.span() for m in _SHOWN_CODE.finditer(text)]
    return [m for m in pattern.finditer(text) if not any(a <= m.start() < b for a, b in code)]


# Under a heading, in a page's source: the words its section is found by
# that it does not use itself. They are no part of the page as it is shown.
_KEYWORDS = re.compile(r"^[ \t]*<!-- *keywords: *(.*?) *-->[ \t]*\n?", re.M | re.I)


def _take_keywords(segments: list[Segment]) -> tuple[list[Segment], dict[str, str]]:
    """A page's segments without their keyword lines, and those words by the
    anchor of the heading each line stands under."""
    found: dict[str, str] = {}
    kept: list[Segment] = []
    anchor = ""
    for seg in segments:
        if not isinstance(seg, str):
            kept.append(seg)
            continue
        lines = _in_prose(_KEYWORDS, seg)
        marks = sorted(
            [(m.start(), "heading", m) for m in _in_prose(_HEADING, seg)]
            + [(m.start(), "keywords", m) for m in lines]
        )
        for _, kind, m in marks:
            if kind == "heading":
                anchor = slugify(m.group(2))
            else:
                found[anchor] = ", ".join(w for w in (found.get(anchor, ""), m.group(1)) if w)
        text = seg
        for m in reversed(lines):
            text = text[: m.start()] + text[m.end() :]
        if text.strip():
            kept.append(text)
    return kept, found


def index(pages: list[Page]) -> list[Section]:
    """Every heading of every page with its prose and code, in page order."""
    sections: list[Section] = []
    for page in pages:
        current: Section | None = None
        for seg in page.segments:
            if not isinstance(seg, str):
                if isinstance(seg, Live) and current is not None:
                    current.code += "\n" + seg.source
                    current.body += f"\n\n```python\n{seg.source}\n```\n"
                continue
            pos = 0
            for m in _in_prose(_HEADING, seg):
                if current is not None:
                    current.text += "\n" + seg[pos : m.start()]
                    current.body += "\n" + seg[pos : m.start()]
                heading = m.group(2)
                anchor = slugify(heading)
                nth = 1 + sum(1 for s in sections if s.page is page and s.anchor == anchor)
                current = Section(
                    page, heading, anchor, "", "", keywords=page.keywords.get(anchor, ""), nth=nth
                )
                sections.append(current)
                pos = m.end()
            if current is not None:
                current.text += "\n" + seg[pos:]
                current.body += "\n" + seg[pos:]
    return sections


@functools.lru_cache(maxsize=1)
def sections() -> list[Section]:
    """The manual's sections, read once, for an example that searches them."""
    return index(load())


def docs(sections: list[Section]) -> list[Doc]:
    """The sections as something to search: a word in the heading or among
    the section's keywords counts most, in the page's title next, then in
    the prose, and in the code last."""
    return [
        Doc(
            section,
            (
                (4.0, section.heading),
                (4.0, [words.strip() for words in section.keywords.split(",")]),
                (3.0, section.page.title),
                (2.0, section.text),
                (1.0, section.code),
            ),
        )
        for section in sections
    ]


# The lists of sections that were searched, each with what was made of it.
_DOCS: dict[int, tuple[list[Section], list[Doc]]] = {}


def _docs_for(sections: list[Section]) -> list[Doc]:
    kept = _DOCS.get(id(sections))
    if kept is None or kept[0] is not sections or len(kept[1]) != len(sections):
        if len(_DOCS) > 4:
            _DOCS.clear()
        kept = _DOCS[id(sections)] = (sections, docs(sections))
    return kept[1]


def search(sections: list[Section], query: str, limit: int = 10) -> list[Hit]:
    """Sections that have every word of the query, best first, for the
    search box. A word is found as a whole word, in the form it was asked
    in or another, and among the words a section is known by elsewhere.
    The last word is found while it is still being typed, a name made of
    several as it stands: ``FileUp``, ``clear_on_sub``."""
    typed = query.split()
    asked = terms(" ".join(typed[:-1]))
    if typed:
        # What is being typed is one word, begun: of a dotted name its
        # last part.
        last = "".join(re.findall(r"[a-z0-9_]+", typed[-1].lower().rpartition(".")[2]))
        if last and (last not in SMALL or not asked):
            asked = [term for term in asked if term != last] + [last]
    found = rank(_docs_for(sections), asked, every=True, typing=True)
    return [Hit(f.what, round(f.score), _snippet(f.what.text, asked)) for f in found[:limit]]


def _snippet(text: str, terms: list[str], width: int = 110) -> str:
    """The first line of a section that has one of the words, or its first
    line when it was found by a keyword."""
    first = ""
    for line in text.splitlines():
        plain = line.strip()
        if not plain or plain.startswith(("#", "```")):
            continue
        first = first or plain
        said = {form for word in tokens(plain) for form in forms(word)}
        if any(not forms(term).isdisjoint(said) for term in terms):
            first = plain
            break
    return first if len(first) <= width else first[: width - 1] + "…"


def parse(text: str, slug: str) -> tuple[dict[str, str], list[Segment]]:
    """Front matter and the body split into prose, live blocks and card rows."""
    meta: dict[str, str] = {}
    m = _FRONT.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end() :]
    segments: list[Segment] = []
    pos = 0
    for n, block in enumerate(_FENCE.finditer(text)):
        prose = text[pos : block.start()].strip("\n")
        if prose.strip():
            segments.append(prose)
        if block.group(1) == "cards":
            cards = Cards([])
            for line in block.group(2).splitlines():
                if not line.strip():
                    continue
                target, *given = [part.strip() for part in line.split("|")]
                cards.slugs.append(target)
                if given and given[0]:
                    cards.titles[target] = given[0]
                if len(given) > 1 and given[1]:
                    cards.texts[target] = given[1]
            segments.append(cards)
        else:
            segments.append(_compile(block.group(2), f"{slug}#{n}"))
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
        segments, keywords = _take_keywords(segments)
        group = parts[0] if len(parts) > 1 else ""
        related = [r.strip() for r in meta.get("related", "").split(",") if r.strip()]
        pages.append(
            Page(
                slug=slug,
                title=meta.get("title", rel.name.replace("-", " ").title()),
                chapter=GROUPS.get(group, group.replace("-", " ").title()),
                order=int(meta.get("order", "100")),
                segments=segments,
                group=group,
                description=meta.get("description", ""),
                related=related,
                keywords=keywords,
            )
        )
    keys = [key for key, _ in NAV]

    def place(page: Page) -> int:
        key = page.group or page.slug.strip("/") or "index"
        return keys.index(key) if key in keys else len(keys)

    pages.sort(key=lambda p: (place(p), p.order, p.slug))
    for page in pages:
        for slug in page.related:
            if not any(p.slug == slug for p in pages):
                raise ValueError(f"{page.slug} relates to {slug}, which is not a page")
        for seg in page.segments:
            if isinstance(seg, Cards):
                for slug in seg.slugs:
                    if not any(p.slug == slug for p in pages):
                        raise ValueError(f"{page.slug} has a card for {slug}, which is not a page")
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
            if not isinstance(seg, Live):
                continue
            try:
                exec(seg.body, ns)
            except Exception:  # noqa: BLE001  the page shows the failure where the block is
                log.exception("live block %s failed at load", seg.id)
                continue
            for name, value in list(ns.items()):
                if not (isinstance(value, type) and issubclass(value, BaseModel)):
                    continue
                if value is BaseModel or value.__module__ != ns["__name__"]:
                    continue
                if name in models and models[name][0] is value:
                    continue
                try:
                    value()
                except Exception:  # noqa: BLE001  a model that needs arguments, or cannot be made
                    continue
                if name in models and set(models[name][0].model_fields) != set(value.model_fields):
                    raise ValueError(
                        f"{name} is defined with different fields in {models[name][1]} and "
                        f"{seg.id}; the manual's state holds one {name}"
                    )
                models.setdefault(name, (value, seg.id))
        sys.modules.pop(ns["__name__"], None)
    fields: dict[str, Any] = {
        field_name(name): (cls, Field(default_factory=cls)) for name, (cls, _) in models.items()
    }
    for own in ("query", "groups"):
        if own in fields:
            raise ValueError(
                f"an example model may not be named {own.title()}; "
                "the manual's own state holds that field"
            )
    return create_model(
        "State", query=(str, ""), groups=(dict[str, bool], Field(default_factory=dict)), **fields
    )


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
            cls="overflow-x-auto rounded-t-lg border border-b-0 bg-muted/40 px-6 py-6",
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

    def moved(request: Any) -> RedirectResponse:
        root = request.scope.get("root_path", "")
        return RedirectResponse(root + MOVED[request.url.path.removeprefix(root)], 301)

    for old_slug in MOVED:
        app.route(old_slug, moved)

    by_slug = {p.slug: p for p in pages}

    def go(slug: str) -> Any:
        return lambda s, _: s.navigate(slug)

    def cards(
        slugs: list[str], titles: dict[str, str] | None = None, texts: dict[str, str] | None = None
    ) -> ui.Component:
        """Cards that each open a page, with the page's title and its one line
        unless the block gave the card its own."""
        titles, texts = titles or {}, texts or {}
        return ui.Grid(
            *(
                ui.Card(
                    ui.Text(texts.get(slug, by_slug[slug].description), variant="muted"),
                    title=titles.get(slug, by_slug[slug].title),
                    on_click=go(slug),
                    cls="transition-colors hover:bg-muted/40",
                )
                for slug in slugs
            ),
            cols={"sm": 1, "md": 2},
            gap=4,
        )

    def footer(page: Page) -> list[ui.Component]:
        """The way on from a page: the next page of its group, and related pages."""
        parts: list[ui.Component] = [ui.Separator(cls="mt-4")]
        if page.group in GROUPS:
            siblings = [p for p in pages if p.group == page.group]
            at = siblings.index(page)
            before = siblings[at - 1] if at > 0 else None
            after = siblings[at + 1] if at + 1 < len(siblings) else None
            parts.append(
                ui.Row(
                    ui.Link(label=before.title, href=before.slug, icon="arrow-left")
                    if before
                    else ui.Text(""),
                    ui.Link(label=after.title, href=after.slug, icon="arrow-right")
                    if after
                    else ui.Text(""),
                    justify="between",
                    wrap=True,
                )
            )
        if page.related:
            parts.append(ui.Text("Related", variant="label", cls="mt-2"))
            parts.append(cards(page.related))
        return parts

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

    def nav(current: Page, query: str, opened: dict[str, bool]) -> ui.Sidebar:
        box = ui.Input(
            value=query,
            kind="search",
            prefix_icon="search",
            placeholder="Search the manual",
            clearable=True,
            max_length=200,
            debounce_ms=200,
            on_change=lambda s, v: setattr(s.state, "query", v or ""),
            on_submit=first_hit,
            cls="mb-2",
        )
        if query.strip():
            return ui.Sidebar(box, *results(query), title="Manual")
        items: list[ui.Component] = [box]
        for key, label in NAV:
            if not label:
                at = "/" if key == "index" else f"/{key}"
                page = next((p for p in pages if p.slug == at), None)
                if page is not None:
                    items.append(ui.Link(label=page.title, href=page.slug, active=page is current))
                continue
            links = [
                ui.Link(label=p.title, href=p.slug, active=p is current)
                for p in pages
                if p.group == key
            ]
            if links:
                items.append(
                    ui.SidebarGroup(
                        *links,
                        label=label,
                        open=opened.get(key, key == current.group),
                        on_toggle=lambda s, open, g=key: s.state.groups.__setitem__(g, open),
                        key=key,
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

        def open_group(s: mw.Session[Any]) -> None:
            if page.group in GROUPS:
                s.state.groups[page.group] = True

        @app.page(page.slug, title=f"{page.title} · millwork")
        def view(s: mw.Session[Any]) -> ui.Component:
            body: list[ui.Component] = []
            ns = page_namespace(page.slug, s.id)
            for seg in page.segments:
                if isinstance(seg, str):
                    body.append(ui.Markdown(seg))
                elif isinstance(seg, Cards):
                    body.append(cards(seg.slugs, seg.titles, seg.texts))
                else:
                    body.append(specimen(render_block(s, seg, ns), seg.source))
            body.extend(footer(page))
            return ui.Page(
                nav(page, s.state.query, s.state.groups),
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
                    # Which millwork this manual describes, and what changed in it.
                    links=[
                        ui.Link(
                            label=mw.__version__,
                            href=f"https://github.com/DvGils/millwork/releases/tag/v{mw.__version__}",
                            target="_blank",
                            cls="text-muted-foreground hover:text-foreground",
                        )
                    ],
                ),
            )

        view.connect(open_group)
        view.close(drop_namespace)

    for page in pages:
        register(page)
    return app


app = make_app()

__all__ = [
    "Cards",
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
    "sections",
    "state_model",
    "Section",
    "index",
    "slugify",
]
