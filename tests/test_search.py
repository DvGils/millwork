"""Finding a text by the words of a question."""

import pytest

from millwork.search import Doc, close, forms, rank, terms, tokens


def test_a_text_is_its_words_and_a_name_also_its_parts() -> None:
    assert tokens("Call ui.FileUpload(clear_on_submit=True), twice!") == [
        *("call", "ui", "fileupload", "file", "upload"),
        *("clear_on_submit", "clear", "on", "submit", "true", "twice"),
    ]
    assert tokens("") == [] and tokens("§ … ?") == []


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("shared", "share"),
        ("sharing", "share"),
        ("confirmation", "confirm"),
        ("confirmations", "confirm"),
        ("sortable", "sort"),
        ("selection", "select"),
        ("redirection", "redirect"),
        ("hidden", "hide"),
        ("stopped", "stop"),
        ("tables", "table"),
        ("boxes", "box"),
        ("queries", "query"),
        ("used", "use"),
        ("loading", "load"),
        ("pages", "page"),
        ("copied", "copy"),
        ("translation", "translate"),
        ("navigation", "navigate"),
        ("written", "write"),
        ("running", "run"),
        ("ids", "id"),
    ],
)
def test_a_word_is_found_in_another_of_its_forms(one: str, other: str) -> None:
    assert not forms(one).isdisjoint(forms(other)), (forms(one), forms(other))


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("state", "stat"),
        ("states", "stat"),
        ("tabs", "table"),
        ("form", "format"),
        ("pages", "pagination"),
        ("uses", "users"),
        ("load", "upload"),
        ("theme", "them"),
        ("things", "the"),
        ("then", "the"),
        ("listen", "list"),
        ("filled", "file"),
        ("version", "verse"),
        ("station", "state"),
    ],
)
def test_a_word_is_not_found_in_one_that_only_begins_or_ends_alike(one: str, other: str) -> None:
    assert forms(one).isdisjoint(forms(other)), (forms(one), forms(other))


def test_a_question_is_the_words_that_say_what_it_is_about() -> None:
    assert terms("How do I share the data?") == ["share", "data"]
    assert terms("st.button") == ["button"] and terms("ui.Table") == ["table"]
    assert terms("s.toast(message)") == ["toast", "message"]
    assert terms("clear_on_submit") == ["clear_on_submit", "clear", "submit"]
    # What a name stands in is not looked for, whatever its length, and a
    # short word that stands alone is.
    assert terms("dcc.Interval") == ["interval"] and terms("Session.toast") == ["toast"]
    assert terms("auth.Auth") == ["auth"] and terms("db connection") == ["db", "connection"]
    assert terms("I want to show some numbers") == ["show", "numbers"]
    # One that is made of small words alone is looked for as it is.
    assert terms("how to") == ["how", "to"] and terms("ui") == ["ui"]
    assert terms("  ") == []


def doc(name: str, keys: str = "", said: str = "") -> Doc:
    return Doc(name, ((5.0, name), (4.0, [k.strip() for k in keys.split(",")]), (1.0, said)))


def names(found: list) -> list[str]:  # type: ignore[type-arg]
    return [f.what for f in found]


def test_a_word_counts_for_where_it_is_and_for_how_few_have_it() -> None:
    docs = [
        doc("Dialog", "modal, popup", "A window over the page."),
        doc("Sheet", "drawer", "A panel from the side of the page, like a dialog."),
        doc("Page", "", "The page of an app."),
        doc("Print", "", "Print the page."),
    ]
    # By its name before what only speaks of it, and by a keyword.
    assert names(rank(docs, ["dialog"])) == ["Dialog", "Sheet"]
    assert names(rank(docs, ["modal"])) == ["Dialog"]
    # The word few have decides: every one of these has "page".
    assert names(rank(docs, ["print", "page"]))[0] == "Print"
    # One that has all the words stands before one that has a word of them.
    assert names(rank(docs, ["panel", "side"]))[0] == "Sheet"
    found = rank(docs, ["dialog"])
    assert found[0].named and not found[1].named and found[0].matched == 1
    assert rank(docs, []) == [] and rank(docs, ["nothing"]) == []


def test_a_document_called_what_was_asked_stands_first() -> None:
    docs = [doc("One tab, one session"), doc("Tabs"), doc("Tab strip of a table")]
    assert names(rank(docs, ["tabs"]))[0] == "Tabs"
    assert docs[1].is_called(["tabs"]) and not docs[0].is_called(["tabs"])
    # What a name stands in does not count, and a name made of several
    # words is called by them.
    assert doc("ui.Table").is_called(["table"]) and doc("s.toast").is_called(["toasts"])
    assert doc("ui.FileUpload").is_called(["file", "upload"])
    assert not doc("ui.FileUpload").is_called(["file"])


def test_a_word_of_a_phrase_counts_in_full_with_the_whole_phrase() -> None:
    docs = [doc("Empty", "no data, blank slate"), doc("Data", "", "data"), doc("Other")]
    assert docs[0].weights(["data"]) == [2.0] and docs[0].weights(["no", "data"]) == [4.0, 4.0]
    assert docs[0].weights(["blank"]) == [2.0] and docs[0].weights(["slate", "blank"]) == [4.0, 4.0]
    # So a thing is not found first by one common word of what it is
    # called elsewhere.
    assert names(rank(docs, ["data"]))[0] == "Data"
    assert names(rank(docs, ["no", "data"]))[0] == "Empty"


def test_every_word_or_the_most_of_them() -> None:
    docs = [doc("Toast", "notification", "With an action."), doc("Table", "", "Rows.")]
    assert names(rank(docs, ["toast", "rows"])) == ["Toast", "Table"]
    assert rank(docs, ["toast", "rows"], every=True) == []
    assert names(rank(docs, ["toast", "action"], every=True)) == ["Toast"]


def test_a_word_that_is_being_typed_is_found_by_its_beginning() -> None:
    docs = [doc("Dialog"), doc("Download")]
    assert rank(docs, ["dia"]) == []
    assert names(rank(docs, ["dia"], typing=True)) == ["Dialog"]
    assert names(rank(docs, ["d"], typing=True)) == ["Dialog", "Download"]
    # Only the last word is: the ones before it are whole.
    assert names(rank(docs, ["dia", "download"], typing=True)) == ["Download"]
    assert rank(docs, ["dia", "download"], typing=True, every=True) == []
    # By its beginning, and not by what stands inside it.
    assert rank(docs, ["load"], typing=True) == [] and rank(docs, ["alog"], typing=True) == []


def test_a_mistyped_word_is_read_as_the_one_it_is_close_to() -> None:
    docs = [doc("Dialog", "modal"), doc("Sidebar", "", "mentions a sidecar")]
    assert close("dialgo", docs) == "dialog"
    assert close("sidbar", docs) == "sidebar" and close("sidebra", docs) == "sidebar"
    # Only by a word that stands where it counts, and only when close.
    assert close("sidecr", docs) is None and close("xyzzy", docs) is None
    # A short word is not guessed at, nor one that begins otherwise, nor a
    # name that holds a known word whole.
    docs = [doc("form"), doc("graph"), doc("uvicorn"), doc("context"), doc("sure")]
    for unknown in ("orm", "mui", "gunicorn", "graphql", "usecontext", "survey"):
        assert close(unknown, docs) is None, unknown
    assert close("contxet", docs) == "context"
