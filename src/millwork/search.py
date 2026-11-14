"""Finding a text by the words of a question.

What is searched is a list of documents, each with a few fields that
count for more or less: a name, some keywords, the prose. A question is
taken apart into words. A word is found in a field as a whole word, in the
form it was asked in or another, so that ``shared`` finds ``share`` and
``tabs`` does not find ``table``. A word that few documents have counts
for more than one that most of them have.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Doc", "Found", "close", "forms", "rank", "terms", "tokens"]

_WORD = re.compile(r"[A-Za-z0-9_]+")
_HUMP = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# What a name stands in, as ``ui`` in ``ui.Table``: asked for by that name,
# the thing is meant and not where it lives.
_HOME = re.compile(r"([A-Za-z_]\w*)\.(?=[A-Za-z_])")
# Words of a question that say nothing of what it is about.
SMALL = frozenset(
    "a all also an and any are as at be between but by can do does for from get has have here"
    " how i if in into is it just like make me my need not of on or should so some than that"
    " the then there this to use using want way we what when will with would you your".split()
)
# The endings a word is found without, longest first, each with the least
# that has to be left of the word.
_ENDINGS = (
    *(("ations", 3), ("ation", 3), ("ables", 3), ("able", 3), ("ibles", 3), ("ible", 3)),
    *(("ings", 3), ("ing", 3), ("ied", 2), ("ies", 2), ("ed", 2), ("es", 3), ("s", 2)),
)
# What a word ends in when its plural is made with ``es``.
_HISSING = ("s", "x", "z", "ch", "sh")
# Letters that stand doubled at the end of a word of their own: fill, pass.
_DOUBLED = "lsfz"


def _parts(word: str) -> list[str]:
    """A name as the words it is made of: ``FileUpload``, ``clear_on_submit``."""
    return [p.lower() for chunk in word.split("_") for p in _HUMP.split(chunk) if p]


def tokens(text: str) -> list[str]:
    """The words of a text, in lower case. A name made of several, as
    ``FileUpload`` or ``clear_on_submit``, is there whole and as its parts."""
    out: list[str] = []
    for word in _WORD.findall(text):
        parts = _parts(word)
        out.append(word.lower())
        if len(parts) > 1:
            out.extend(parts)
    return out


@functools.cache
def forms(word: str) -> frozenset[str]:
    """A word and what it may be a form of: ``shared`` is ``share``,
    ``confirmation`` is ``confirm``, ``hidden`` is ``hide``. Two words are
    the same word when they share one of these."""
    out = {word}
    for ending, least in _ENDINGS:
        base = word[: -len(ending)]
        if not word.endswith(ending) or len(base) < least:
            continue
        if ending in ("ied", "ies"):
            out.add(base + "y")
            continue
        if ending in ("ation", "ations"):
            # translation, navigation: by the word for doing it.
            out.add(base + "ate")
        if ending != "es" or base.endswith(_HISSING):
            out.add(base)
        if ending != "s" and (len(base) > 2 or ending == "ed"):
            out.add(base + "e")
        if len(base) > 3 and base[-1] == base[-2] and base[-1] not in _DOUBLED:
            # A letter doubled before the ending: stopped, running.
            out.update((base[:-1], base[:-1] + "e"))
    if word.endswith(("ction", "ctions")):
        # selection, redirection: what is done, by the word for doing it.
        out.add(word[: word.rindex("ion")])
    if len(word) > 5 and word.endswith("en") and word[-3] == word[-4]:
        # hidden, written.
        out.update((word[:-3], word[:-3] + "e"))
    return frozenset(out)


def terms(question: str) -> list[str]:
    """A question as the words that are looked for: without the small ones
    and without what a name stands in, ``ui`` in ``ui.Table`` or ``st`` in
    ``st.button``, unless it has no others."""
    found = list(dict.fromkeys(tokens(question)))
    homes = {home.lower() for home in _HOME.findall(question)}
    named = {name.lower() for name in _WORD.findall(_HOME.sub("", question))}
    kept = [t for t in found if t not in SMALL and (t not in homes or t in named)]
    return kept or [t for t in found if t not in SMALL] or found


def _same(asked: frozenset[str], known: frozenset[str]) -> bool:
    return not asked.isdisjoint(known)


@dataclass
class Doc:
    """Something that can be found: what it is, and its fields, each with
    how much a word in it counts for. The first field is its name. A field
    given as a list is one of phrases, ``no data`` or ``dark mode``: a word
    of a phrase counts in full when the question has the whole phrase, and
    for half when it has that word alone."""

    what: Any
    fields: Sequence[tuple[float, str | Sequence[str]]]
    # For each field its weight and its phrases, a phrase being the forms
    # of each of its words. A field of prose is one phrase of one word,
    # with the forms of all its words.
    _fields: list[tuple[float, list[list[frozenset[str]]], frozenset[str]]] = field(
        default_factory=list
    )
    # The words of its name, a name made of several by its parts.
    _name: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for n, (weight, text) in enumerate(self.fields):
            if isinstance(text, str):
                words = frozenset(tokens(text))
                phrases = [[frozenset(form for word in words for form in forms(word))]]
            else:
                words = frozenset(word for phrase in text for word in tokens(phrase))
                phrases = [[forms(word) for word in tokens(phrase)] for phrase in text]
            self._fields.append((weight, [p for p in phrases if p], words))
            if n == 0 and isinstance(text, str):
                self._name = [part for word in _WORD.findall(text) for part in _parts(word)]

    def weights(self, asked: Sequence[str], typing: bool = False) -> list[float]:
        """How much each word of a question counts for in this document:
        the weight of the best field that has it, or nothing. With
        ``typing`` the last word is found where a word begins with it."""
        every = [forms(term) for term in asked]
        out = [0.0] * len(asked)
        for weight, phrases, words in self._fields:
            for phrase in phrases:
                whole = all(any(_same(a, known) for a in every) for known in phrase)
                worth = weight if whole else weight / 2
                for n, a in enumerate(every):
                    if worth > out[n] and any(_same(a, known) for known in phrase):
                        out[n] = worth
            if typing and asked and weight > out[-1]:
                if any(word.startswith(asked[-1]) for word in words):
                    out[-1] = weight
        return out

    def has(self, term: str) -> bool:
        return self.weights([term])[0] > 0

    def is_called(self, asked: Sequence[str]) -> bool:
        """Whether the question is its name: the words of the one are the
        words of the other. ``Tabs`` for ``tabs`` and ``ui.Table`` for
        ``table``, and not ``One tab, one session``, nor ``ui.Button`` for
        ``translate the buttons``. What a name stands in does not count."""
        words = [word for word in self._name if len(word) > 2] or self._name
        said = frozenset(form for term in asked for form in forms(term))
        known = frozenset(form for word in words for form in forms(word))
        return (
            bool(words)
            and all(_same(forms(word), said) for word in words)
            and all(_same(forms(term), known) for term in asked)
        )

    def strong_words(self, strong: float) -> set[str]:
        return {word for weight, _, words in self._fields if weight >= strong for word in words}


@dataclass
class Found:
    what: Any
    # How much it has to do with the question.
    score: float
    # How many of the question's words it has, and whether it has one of
    # them where it counts: in its name, and not only in what is said of it.
    matched: int
    named: bool
    # How much each word of the question counts for in it.
    weights: Sequence[float] = ()


def rank(
    docs: Sequence[Doc],
    asked: Sequence[str],
    *,
    every: bool = False,
    typing: bool = False,
    strong: float = 4.0,
) -> list[Found]:
    """The documents that have words of a question, best first. A word
    counts for where a document has it and for how few documents have it.
    A document counts for more when it has all of the words, and when the
    words are its name. With ``every``, only the ones that have every word.
    With ``typing``, the last word is found where a word begins with it,
    for a question that is still being typed."""
    if not asked:
        return []
    weights = [doc.weights(asked, typing) for doc in docs]
    rare = [
        math.log(1 + len(docs) / (1 + sum(1 for row in weights if row[n])))
        for n in range(len(asked))
    ]
    found: list[Found] = []
    for doc, row in zip(docs, weights, strict=True):
        matched = sum(1 for weight in row if weight)
        if not matched or (every and matched < len(asked)):
            continue
        score = sum(weight * rare[n] for n, weight in enumerate(row))
        # One strong word outweighs several that are only mentioned, and
        # having them all still counts.
        score *= 0.5 + 0.5 * matched / len(asked)
        if doc.is_called(asked):
            score *= 1.5
        found.append(Found(doc.what, score, matched, any(w >= strong for w in row), row))
    found.sort(key=lambda f: -f.score)
    return found


def _apart(a: str, b: str) -> int:
    """How many letters two words are apart: one for a letter that is
    missing, one too many or another, and one for two that changed places."""
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i]
        for j in range(1, len(b) + 1):
            best = min(rows[-1][j] + 1, row[-1] + 1, rows[-1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                best = min(best, rows[-2][j - 2] + 1)
            row.append(best)
        rows.append(row)
    return rows[-1][-1]


def close(term: str, docs: Iterable[Doc], strong: float = 4.0) -> str | None:
    """The word a mistyped one was probably meant to be: one that stands
    where it counts in some document, begins with the same letter and is a
    letter apart, or two for a long word. A short word is not guessed at,
    and neither is one that holds a known word whole, which is a name made
    of several and no slip of the hand."""
    if len(term) < 5:
        return None
    known = {word for doc in docs for word in doc.strong_words(strong)}
    near = [
        word
        for word in known
        if len(word) > 3
        and word[0] == term[0]
        and word not in SMALL
        and word not in term
        and term not in word
        and _apart(term, word) <= (2 if len(term) >= 8 else 1)
    ]
    return min(near, key=lambda word: (_apart(term, word), word)) if near else None
