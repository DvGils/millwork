"""One thing looked up in the reference and the manual."""

import re

import pytest

from millwork import lookup
from millwork.cli import main
from millwork.manual import _take_keywords, index, load, parse, search, sections
from millwork.reference import ALIASES, NAMED_IN, SESSION_API, entries, reference


def titles(found: str | None) -> list[str]:
    """The parts a lookup printed, by their headings."""
    assert found is not None
    heads = [line[3:] for line in found.splitlines() if line.startswith("## ")]
    return heads[: heads.index("More on this")] if "More on this" in heads else heads


def first(query: str) -> str:
    return titles(lookup.find(query))[0]


def test_a_name_gives_its_entry_and_then_what_the_manual_says_of_it() -> None:
    assert titles(lookup.find("ui.Table"))[:2] == ["ui.Table", "Data"]
    assert titles(lookup.find("ui.Button"))[:2] == ["ui.Button", "Inputs › Button"]
    assert titles(lookup.find("ui.Chat"))[:2] == ["ui.Chat", "Chat"]
    assert titles(lookup.find("tabs"))[:2] == ["ui.Tabs", "Layout › Tabs"]
    assert titles(lookup.find("highlight"))[:2] == ["s.highlight", "Feedback › Highlight"]
    # As it stands in code, and as it is spelled elsewhere.
    for asked in ("`s.toast()`", "s.toast(message)", "Session.toast", "session.toast", "toast"):
        assert first(asked) == "s.toast", asked
    assert first("UI.TABLE") == "ui.Table" and first("@ui.lazy") == "Lazy parts"
    # A call comes with all its docstring says, where the reference has
    # the first of it.
    found = lookup.find("s.highlight", chars=20000)
    assert found is not None and "``scroll=True``" in found
    assert "``scroll=True``" not in reference()
    # A name several things have gives each of them.
    assert titles(lookup.find("outline", chars=20000))[:2] == ["s.outline", "page.outline"]
    # A name a part speaks of in its own words gives that part.
    for asked, part in (("mw.App", "The app"), ("TestApp", "Testing"), ("s.state", "The session")):
        assert first(asked) == part, asked
    assert first("mw.progress") == "Tasks" and first("ui.FormIssues") == "Forms"
    for part, spoken in NAMED_IN.items():
        text = next(e.text for e in entries() if e.name == part)
        for name in spoken:
            assert name in text, (part, name)


def test_what_a_thing_is_called_elsewhere_finds_it() -> None:
    assert titles(lookup.find("modal"))[:3] == ["ui.Dialog", "s.ask", "Feedback › Dialog"]
    assert titles(lookup.find("notification"))[:2] == ["s.toast", "Feedback › Toast"]
    assert "Feedback › Toast" in titles(lookup.find("snackbar"))
    assert titles(lookup.find("background job"))[:2] == ["s.task", "Tasks"]
    assert first("dark mode") == "Theming" and first("log the user out") == "Sign-out and cookies"
    assert "Inputs › Input" in titles(lookup.find("debounce"))
    # By the name it has in another framework.
    for asked, known in (
        ("st.button", "ui.Button"),
        ("st.sidebar", "ui.Sidebar"),
        ("st.dataframe", "ui.Table"),
        ("st.metric", "ui.Stat"),
        ("st.rerun", "s.refresh"),
        ("st.session_state", "State and handlers › One state for the session"),
        ("ui.notify", "s.toast"),
        ("ui.timer", "s.later"),
        ("rx.State", "State and handlers"),
        ("useEffect", "Sessions › Connect"),
    ):
        assert first(asked) == known, asked
    # Every alias is of something the reference has.
    assert set(ALIASES) <= {entry.name for entry in entries()}


def test_a_question_in_words_finds_what_it_is_about() -> None:
    for asked, known in (
        ("shared data between users", "Accessing the session › Data that sessions share"),
        ("how do I deploy with docker?", "Deployment"),
        ("protect a page admin only", "Access rules"),
        ("translate the buttons", "Theming › Strings"),
        ("loading state", "Feedback › Spinner and Skeleton"),
        ("two columns side by side", "Layout › Grid"),
        ("persist data across pages", "State and handlers › One state for the session"),
        ("print the page", "s.print"),
        ("reset a form", "s.reset"),
        ("ask the user for input", "s.ask"),
        ("pagination", "ui.Table"),
    ):
        assert first(asked) == known, asked
    # A word is found in another of its forms, and as a whole word.
    assert first("sharing") == first("shared")
    assert "Files › FileUpload" not in titles(lookup.find("loading", chars=20000))
    assert "ui.Stat" not in titles(lookup.find("state", chars=20000))


def test_a_mistyped_word_and_a_thing_there_is_not() -> None:
    found = lookup.find("dialgo")
    assert found is not None and "(`dialgo` is read as `dialog`.)" in found
    assert titles(found)[0] in ("ui.Dialog", "Feedback › Dialog")
    assert first("tabel") == "ui.Table" and first("sidbar") in ("ui.Sidebar", "Layout › Sidebar")
    # What millwork has nothing by the name of says so, above what has the words.
    email = lookup.find("send an email")
    assert email is not None
    assert "Nothing in millwork is named this. These parts have the words." in email
    assert "Nothing in millwork is named this" not in str(lookup.find("modal"))
    assert lookup.find("xyzzy quux") is None and lookup.find("") is None


def test_a_lookup_is_no_longer_than_asked_and_names_the_rest() -> None:
    found = lookup.find("table", chars=1500)
    assert found is not None
    printed = found.split("## More on this")[0]
    assert len(printed) < 1500 + 300
    assert titles(found) == ["ui.Table"] and "## More on this" in found
    assert "(cut here: `millwork reference ui.Table` gives all of it)" in found
    whole = lookup.find("table", chars=100000)
    assert whole is not None and "cut here" not in whole and len(whole) > 6000
    # By default a lookup is a few thousand characters, and what is asked
    # for is never less than a little.
    for asked in ("form", "chat", "sign in", "table", "session", "tasks", "testing"):
        found = lookup.find(asked)
        assert found is not None and len(found) < lookup.CHARS + 2000, asked
    assert lookup.find("table", chars=0) == lookup.find("table", chars=lookup.LEAST)
    assert lookup.find("table", chars=-5) == lookup.find("table", chars=lookup.LEAST)
    # A part that does not fit is begun when there is room to say something.
    assert len(titles(lookup.find("modal", chars=3000))) > len(
        titles(lookup.find("modal", chars=900))
    )


def test_a_part_that_is_cut_leaves_no_code_open() -> None:
    for asked in ("chat", "tasks", "testing", "modal", "sign in", "theming", "form", "state"):
        for chars in (800, 1500, 4000, 8000):
            found = lookup.find(asked, chars=chars)
            assert found is not None
            fences = [line for line in found.splitlines() if line.startswith("```")]
            assert len(fences) % 2 == 0, (asked, chars)
    # And what the manual's examples are made of is in it.
    toast = lookup.find("components/feedback#toast")
    assert toast is not None and "```python\nui.Row(" in toast and "s.toast(" in toast


def test_every_part_that_is_named_is_given_by_the_command_beside_it() -> None:
    # What a lookup leaves out it names with the command that gives it,
    # and that command gives that part, whole and first.
    asked = set()
    for query in ("table", "form", "state", "chat", "sign in", "page", "session", "tabs"):
        found = lookup.find(query, chars=600)
        assert found is not None
        more = found.partition("## More on this")[2]
        asked |= set(re.findall(r"^- (.+?): `millwork reference (.+)`$", more, re.M))
    assert len(asked) > 40
    for title, address in sorted(asked):
        assert titles(lookup.find(address, chars=600))[0] == title, address
    # A section by its address and by its title, a page by its path.
    for section in sections():
        part = lookup.find(section.address)
        assert part is not None and len(titles(part)) == 1, section.address
        assert "cut here" not in part
    # A section that is called what its page is called has an address of
    # its own.
    addresses = [s.address for s in sections()]
    assert len(addresses) == len(set(addresses))
    assert titles(lookup.find("components/text#text")) == ["Text"]
    assert titles(lookup.find("components/text#text-2")) == ["Text › Text"]
    # Asked for by its address a part is whole, unless a size is asked for.
    page = lookup.find("components/feedback.md")
    cut = lookup.find("components/feedback.md", chars=600)
    assert page is not None and cut is not None and len(page) > 8000 and len(cut) < 1500
    assert "- Feedback › Toast: `millwork reference components/feedback#toast`" in cut
    assert titles(lookup.find("Feedback › Toast")) == ["Feedback › Toast"]
    assert titles(lookup.find("feedback > toast")) == ["Feedback › Toast"]
    page = titles(lookup.find("components/feedback"))
    assert page[:3] == ["Feedback", "Feedback › Alert", "Feedback › Toast"] and len(page) == 10
    assert titles(lookup.find("components/feedback.md")) == page
    assert len(titles(lookup.find("testing.md"))) > 5
    # One word is a word to look for, though a page is called that.
    assert len(str(lookup.find("testing"))) < lookup.CHARS + 2000


def test_the_index_names_everything_and_says_nothing_of_it() -> None:
    index_ = lookup.names()
    assert len(index_) < 9000
    for name in ("ui.Table", "s.highlight", "mw.Signal", "app.page", "page.touch", "auth.Auth"):
        assert name in index_, name
    for name in ("mw.App", "TestApp", "mw.progress", "ui.lazy", "ui.FormIssues", "s.state"):
        assert name in index_, name
    for part in ("Signing in", "The theme", "Icons", "Formats", "Form widgets", "Lazy parts"):
        assert part in index_.split("## Parts of the reference")[1].split("##")[0], part
    assert "- Feedback (components/feedback.md): Alert · Toast · Highlight · Dialog" in index_
    assert "= `" not in index_ and "handler `(session" not in index_
    for name in SESSION_API:
        assert any(entry.name == f"s.{name}" for entry in entries()), name
    # Every line of the reference is in some entry, and no name twice.
    said = "\n".join(entry.text for entry in entries())
    for line in reference().splitlines():
        if line.startswith(("- `on_", "`ui.")) or "tailwind" in line.lower():
            assert line in said, line
    named = [entry.name for entry in entries()]
    assert len(named) == len(set(named))


def test_the_words_a_section_is_found_by_are_no_part_of_the_page() -> None:
    kept, found = _take_keywords(
        [
            "# Title\n<!-- keywords: first, of the page -->\n\nProse.\n\n## One\n"
            "<!-- Keywords: modal, popup -->\n  <!-- keywords: overlay -->\n\nMore prose.",
            "## Two\n\nNo words.\n\n```python\n# no heading\n<!-- keywords: in code -->\n```",
        ]
    )
    assert found == {"title": "first, of the page", "one": "modal, popup, overlay"}
    assert kept[0] == "# Title\n\nProse.\n\n## One\n\nMore prose."
    # What stands in code that is shown is the code's.
    assert "<!-- keywords: in code -->" in str(kept[1])
    for page in load():
        for seg in page.segments:
            assert not isinstance(seg, str) or "keywords:" not in seg.lower(), page.slug
        # Each line of them stands under a heading of its page.
        anchors = {s.anchor for s in sections() if s.page.slug == page.slug}
        assert set(page.keywords) <= anchors, page.slug
    toast = next(s for s in sections() if s.heading == "Toast")
    assert "snackbar" in toast.keywords and "snackbar" not in toast.text


def test_a_comment_in_code_that_is_shown_is_no_heading() -> None:
    _, segments = parse(
        "# Page\n\nProse.\n\n```python\n# reports/state.py\nx = 1\n```\n\n## Real\n", "/t"
    )
    heads = [s.heading for s in sections() if s.page.slug == "/state/organizing"]
    assert heads == ["Organizing your app", "A reusable piece"]
    assert not any(".py" in s.heading or "oauth2-proxy in front" in s.heading for s in sections())
    assert len(segments) == 1 and "# reports/state.py" in str(segments[0])
    pages = load()
    assert len(index(pages)) == len(sections()) > 180


def test_the_manuals_search_box_finds_by_these_too() -> None:
    toast = next(s for s in sections() if s.heading == "Toast")
    assert search(sections(), "snackbar")[0].section is toast
    assert search(sections(), "snackbar")[0].snippet.startswith("A toast is a command")
    assert search(sections(), "toast action")[0].section is toast
    # It asks for every word, so a word that is nowhere finds nothing.
    assert search(sections(), "toast xyzzy") == [] and search(sections(), "xyzzy") == []
    # The last word is found while it is still being typed.
    dialog = next(s for s in sections() if s.heading == "Dialog")
    for typed in ("dia", "dialo", "dialog", "modal", "moda"):
        assert search(sections(), typed)[0].section is dialog, typed
    assert search(sections(), "sign in")[0].section.page.slug.startswith("/sign-in")


def test_the_command_looks_one_thing_up_or_prints_it_all(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["reference", "modal"]) == 0
    assert capsys.readouterr().out.startswith("# millwork: modal\n")
    assert main(["reference", "shared", "data", "--chars", "900"]) == 0
    assert len(capsys.readouterr().out.split("## More on this")[0]) < 1300
    assert main(["reference", "--index"]) == 0
    assert capsys.readouterr().out.startswith("# millwork: what there is\n")
    assert main(["reference"]) == 0
    whole = capsys.readouterr().out
    assert whole.startswith("# millwork ") and "`millwork reference <words>`" in whole
    assert main(["reference", "xyzzy"]) == 1
    said = capsys.readouterr()
    assert said.out == "" and "nothing in the reference or the manual is about 'xyzzy'" in said.err
    # What cannot be meant is refused.
    for wrong in (["--index", "modal"], ["table", "--chars", "0"], ["--chars", "2000"]):
        with pytest.raises(SystemExit) as stopped:
            main(["reference", *wrong])
        assert stopped.value.code == 2, wrong
        capsys.readouterr()
