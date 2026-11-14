"""One thing looked up: what the reference and the manual say of it.

``millwork reference`` prints the whole catalogue, which is a lot to read
for one question. With words behind it, it prints the few parts that are
about them: an entry of the reference, the sections of the manual that
explain it, each whole, up to a size. What else matched is named under
them, each with the command that gives it.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from millwork import manual
from millwork.manual import PAGES, Section, sections
from millwork.reference import OPENING, Entry, entries
from millwork.search import Doc, close, rank, terms

__all__ = ["find", "names"]

# How much is printed for one question when nothing else is asked for, and
# the least that can be asked for.
CHARS = 4000
LEAST = 500
# The least room in which a part that does not fit whole is still begun.
ROOM = 1200
# How much less than the best a part may have to do with the question.
NEAR = 4
# What a word counts for at the least where a part is called by it.
STRONG = 4.0


@dataclass(frozen=True)
class _Part:
    """A part of the reference or of the manual, as it is printed."""

    title: str
    # What `millwork reference` takes to give this part alone.
    address: str
    where: str
    text: str


def _of(what: Entry | Section) -> _Part:
    if isinstance(what, Entry):
        where = "reference" if what.name == what.part else f"reference, {what.part}"
        return _Part(what.name, what.name, where, what.text)
    page = what.page
    opens = what.heading == page.title and what.nth == 1
    title = page.title if opens else f"{page.title} › {what.heading}"
    path = what.address.partition("#")[0]
    return _Part(title, what.address, f"manual, {path}.md", what.body.strip())


_PROP = re.compile(r"^- `(\w+)", re.M)


@functools.lru_cache(maxsize=1)
def _corpus() -> list[Doc]:
    """The reference's entries and the manual's sections, to be searched
    as one. An entry is found best by its name, then by what the thing is
    called elsewhere and by the name of one of its props, and last by what
    is said of it."""
    found = [
        Doc(
            entry,
            (
                (5.0, entry.name),
                (4.0, [words.strip() for words in entry.aliases.split(",")]),
                (3.0, " ".join(entry.names)),
                (4.0, " ".join(_PROP.findall(entry.text)) if entry.name != entry.part else ""),
                (1.0, entry.text),
            ),
        )
        for entry in entries()
    ]
    return found + manual.docs(sections())


def _name(asked: str) -> list[str]:
    """A name as it may be asked for: without what stands around it in
    code, and by its last part alone."""
    name = asked.strip().strip("`").lstrip("@").partition("(")[0].lower()
    return list(dict.fromkeys((name, name.rpartition(".")[2])))


def _named(asked: str) -> tuple[list[Entry | Section], bool]:
    """What a query names, and whether it asked for it by its address: a
    section as ``components/feedback#toast``, a page as
    ``components/feedback.md``, a section by its title, or an entry of the
    reference by its name."""
    place = asked.strip().strip("/").lower()
    # A page is asked for as a path: one word is a word to look for.
    paged = place.removesuffix(".md") if "/" in place or place.endswith(".md") else ""
    title = " › ".join(part.strip() for part in asked.lower().replace(">", "›").split("›"))
    at = [
        s
        for s in sections()
        if place == s.address
        or paged == s.address.partition("#")[0]
        or ("›" in title and _of(s).title.lower() == title)
    ]
    if at:
        return list(at), True
    known = entries()
    for name in _name(asked):
        if not name:
            continue
        # By its own name before a name its part speaks of, and such a
        # one in full: ``s.state`` is the session's, ``state`` is a word.
        found = [e for e in known if name in (e.name.lower(), e.name.lower().rpartition(".")[2])]
        found = found or [e for e in known if name in (n.lower() for n in e.names)]
        if found:
            return list(found), False
    return [], False


def _closed(text: str) -> str:
    """A text that was cut, with the code it was cut in closed."""
    fences = sum(1 for line in text.splitlines() if line.startswith("```"))
    return text + ("\n```" if fences % 2 else "")


def find(query: str, chars: int | None = None) -> str | None:
    """What there is on a query, as Markdown. What it names comes first:
    by its address or its title that part alone, and by its name the entry
    and then what a search finds. Each part is whole for as long as it
    fits in ``chars``, and the rest is named with the command that gives
    it. Without ``chars`` a search prints a few thousand characters and an
    address all there is at it. None when nothing matches."""
    named, addressed = _named(query)
    room = max(chars, LEAST) if chars is not None else (None if addressed else CHARS)
    out = [f"# millwork: {query.strip()}", "", f"The manual's pages are in {PAGES}.", ""]
    near: list[Entry | Section] = []
    if not addressed:
        corpus = _corpus()
        asked = terms(query)
        # A word nothing has may be one that was mistyped.
        for n, term in enumerate(asked):
            if not any(doc.has(term) for doc in corpus):
                meant = close(term, corpus)
                if meant is not None:
                    asked[n] = meant
                    out += [f"(`{term}` is read as `{meant}`.)", ""]
        found = rank(corpus, asked)
        best = found[0].score if found else 0.0
        kept = [f for f in found if f.score * NEAR >= best]
        near = [f.what for f in kept]
        if named:
            # Behind an entry that was asked for by name comes what the
            # manual says of it, before the entries that are named alike.
            explained = next((what for what in near if isinstance(what, Section)), None)
            near.sort(key=lambda what: what is not explained)
        elif kept:
            # The word of the question that the fewest parts have is the one
            # it is about. When no part is called by it, or by what it is
            # called elsewhere, millwork has nothing by that name.
            had = [sum(1 for f in found if f.weights[n]) for n in range(len(asked))]
            about = min(range(len(asked)), key=lambda n: had[n] or len(found) + 1)
            if not any(f.weights[about] >= STRONG for f in kept):
                out += ["Nothing in millwork is named this. These parts have the words.", ""]
    parts = list(dict.fromkeys(map(_of, [*named, *near])))
    if not parts:
        return None
    more: list[_Part] = []
    for n, part in enumerate(parts):
        block = f"## {part.title}\n\n({part.where})\n\n{part.text}\n"
        if more or (room is not None and len(block) > room and n and room < ROOM):
            more.append(part)
            continue
        if room is not None and len(block) > room:
            # Begun, and cut where the room ends: the first part whatever
            # its size, and a later one that has room enough to say something.
            block = _closed(block[:room].rsplit("\n", 1)[0])
            block += f"\n\n(cut here: `millwork reference {part.address}` gives all of it)\n"
            room = 0
        out.append(block)
        if room is not None:
            room -= len(block)
            if room <= 0:
                more.extend(parts[n + 1 :])
                break
    if more:
        out += ["## More on this", ""]
        out += [f"- {part.title}: `millwork reference {part.address}`" for part in more[:12]]
        if len(more) > 12:
            out.append(f"- and {len(more) - 12} more")
    return "\n".join(out).rstrip() + "\n"


def names() -> str:
    """Every name there is to look up, without what is said of it: the
    reference's entries by part, and the manual's pages with their
    sections."""
    out = ["# millwork: what there is", ""]
    parts: dict[str, list[str]] = {}
    for entry in entries():
        listed = parts.setdefault(entry.part, [])
        if entry.name != entry.part:
            listed.append(entry.name)
        listed.extend(entry.names)
    for part, listed in parts.items():
        if listed:
            out += [f"## {part}", "", ", ".join(listed), ""]
    out += ["## Parts of the reference", "", ", ".join(p for p in parts if p != OPENING), ""]
    out += ["## The manual", ""]
    pages: dict[str, tuple[str, list[str]]] = {}
    for section in sections():
        path = section.address.partition("#")[0]
        heads = pages.setdefault(path, (section.page.title, []))[1]
        if section.heading != section.page.title:
            heads.append(section.heading)
    for path, (title, heads) in pages.items():
        out.append(f"- {title} ({path}.md)" + (": " + " · ".join(heads) if heads else ""))
    out += [
        "",
        "`millwork reference <name>` gives what is said of one of them, and",
        "`millwork reference <path>.md` a page of the manual whole.",
    ]
    return "\n".join(out) + "\n"
