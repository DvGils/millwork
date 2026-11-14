"""A retired spelling works for one minor release and says so, at the app's line."""

import importlib
import logging
import os
import pkgutil
import subprocess
import sys
import textwrap
import tomllib
import warnings
from pathlib import Path
from typing import Any, ClassVar

import pytest

import millwork as mw
from millwork import deprecation
from millwork.deprecation import Deprecation, Renamed

ROOT = Path(__file__).resolve().parents[1]
OLD_WAY = Deprecation("old_way()", since="98.0", removed="99.0", instead="new_way()")
BARE = Deprecation("bare()", since="98.0", removed="99.0")


def line_of(mark: str) -> int:
    """The line of this file that carries a mark, as a comment."""
    lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    return next(n for n, text in enumerate(lines, 1) if text.endswith(f"# {mark}"))


class Shelf(mw.Component):
    type: ClassVar[str] = "shelf"
    depth: int = 1
    load: int
    old_names: ClassVar[dict[str, Renamed]] = {
        "deep": Renamed("depth", since="98.0", removed="99.0"),
        "weight": Renamed("load", since="98.0", removed="99.0"),
    }


class TallShelf(Shelf):
    type: ClassVar[str] = "tall-shelf"


class Tag(mw.Component):
    """A keyword that is also a parameter of the class's own ``__init__``."""

    type: ClassVar[str] = "tag"
    text: str = ""
    old_names: ClassVar[dict[str, Renamed]] = {
        "label": Renamed("text", since="98.0", removed="99.0"),
        # Renamed twice: ``caption`` became ``label``, which became ``text``.
        "caption": Renamed("label", since="97.0", removed="98.0"),
    }

    def __init__(self, text: str = "", **props: Any) -> None:
        super().__init__(text=text, **props)


class LoudTag(Tag):
    type: ClassVar[str] = "loud-tag"

    def __init__(self, text: str = "", **props: Any) -> None:
        super().__init__(text.upper(), **props)


class OldStyleTag(Tag):
    """An app's subclass from before the rename: it names the old keyword."""

    type: ClassVar[str] = "old-style-tag"

    def __init__(self, label: str = "", **props: Any) -> None:
        super().__init__(label=label.upper(), **props)  # passes it on


class PropsTag(Tag):
    """An app's subclass from before the rename that reads the old keyword
    out of what it was passed."""

    type: ClassVar[str] = "props-tag"

    def __init__(self, **props: Any) -> None:
        props["label"] = props.get("label", "none").upper()
        super().__init__(**props)


class Plank(mw.Component):
    """Old names on a class without an ``__init__`` of its own, and on a
    second base."""

    type: ClassVar[str] = "plank"
    length: int = 1
    old_names: ClassVar[dict[str, Renamed]] = {
        "long": Renamed("length", since="98.0", removed="99.0")
    }


class Bench(Plank):
    type: ClassVar[str] = "bench"


class DeepBench(Bench, Shelf):
    type: ClassVar[str] = "deep-bench"


def test_a_deprecation_says_since_when_until_when_and_what_instead() -> None:
    with pytest.warns(mw.MillworkDeprecationWarning) as caught:
        OLD_WAY.warn()  # old way
    assert str(caught[0].message) == (
        "old_way() is deprecated since millwork 98.0 and stops working in 99.0."
        " Use new_way() instead."
    )
    assert (caught[0].filename, caught[0].lineno) == (__file__, line_of("old way"))
    assert issubclass(mw.MillworkDeprecationWarning, DeprecationWarning)
    assert BARE.message() == "bare() is deprecated since millwork 98.0 and stops working in 99.0."


def test_an_old_keyword_still_works_and_warns_at_the_line_that_used_it() -> None:
    with pytest.warns(mw.MillworkDeprecationWarning) as caught:
        shelf = Shelf(deep=3, weight=7)  # two old keywords
    assert (shelf.depth, shelf.load) == (3, 7)
    assert {(w.filename, w.lineno) for w in caught} == {(__file__, line_of("two old keywords"))}
    assert sorted(str(w.message) for w in caught) == [
        "Shelf(deep=) is deprecated since millwork 98.0 and stops working in 99.0."
        " Use depth= instead.",
        "Shelf(weight=) is deprecated since millwork 98.0 and stops working in 99.0."
        " Use load= instead.",
    ]
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"TallShelf\(deep=\)"):
        assert TallShelf(deep=2, load=1).depth == 2


def test_a_class_with_its_own_init_takes_the_old_keyword_too() -> None:
    """The old name is moved before the class's ``__init__`` runs, so one that
    names the keyword as a parameter receives it."""
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"Tag\(label=\)") as caught:
        tag = Tag(label="new")  # a parameter
    assert tag.text == "new"
    assert (caught[0].filename, caught[0].lineno) == (__file__, line_of("a parameter"))
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"LoudTag\(label=\)") as caught:
        assert LoudTag(label="new").text == "NEW"
    assert len(caught) == 1


def test_a_subclass_written_to_the_old_name_keeps_working() -> None:
    """Its ``__init__`` receives the keyword as it was written, and what it
    passes on is moved where the renamed class takes over."""
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"OldStyleTag\(label=\)") as caught:
        assert OldStyleTag(label="go").text == "GO"
        assert OldStyleTag("go").text == "GO"
        assert OldStyleTag.model_validate({"label": "go"}).text == "GO"
    assert {w.lineno for w in caught} == {line_of("passes it on")}
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"PropsTag\(label=\)"):
        assert PropsTag(label="go").text == "GO"
        assert PropsTag().text == "NONE"


def test_old_names_reach_every_subclass_and_come_from_every_base() -> None:
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"Bench\(long=\)"):
        assert Bench(long=3).length == 3
    with pytest.warns(mw.MillworkDeprecationWarning) as caught:
        bench = DeepBench(long=3, deep=2, weight=1)
    assert (bench.length, bench.depth, bench.load) == (3, 2, 1)
    assert len(caught) == 3


def test_a_field_declared_under_an_old_name_is_told_so_where_it_is_declared() -> None:
    with pytest.warns(mw.MillworkDeprecationWarning) as caught:

        class Labelled(Tag):  # declares the old name
            type: ClassVar[str] = "labelled"
            label: str = "Save"

        class Further(Labelled):
            type: ClassVar[str] = "further"

    assert [str(w.message) for w in caught] == [
        "Labelled declares a field label, which is text since millwork 98.0."
        " The two are separate fields now. Declare text instead."
    ]
    assert (caught[0].filename, caught[0].lineno) == (__file__, line_of("declares the old name"))


def test_old_names_that_lead_nowhere_are_refused_when_the_class_is_made() -> None:
    before = list(deprecation.DECLARED)
    with pytest.raises(TypeError, match="goes in a circle"):

        class Round(mw.Component):
            type: ClassVar[str] = "round"
            a: int = 1
            old_names: ClassVar[dict[str, Renamed]] = {
                "b": Renamed("c", since="98.0", removed="99.0"),
                "c": Renamed("b", since="98.0", removed="99.0"),
            }

    with pytest.raises(TypeError, match="'b' is now 'c', which is no field"):

        class Lost(mw.Component):
            type: ClassVar[str] = "lost"
            a: int = 1
            old_names: ClassVar[dict[str, Renamed]] = {
                "b": Renamed("c", since="98.0", removed="99.0")
            }

    del deprecation.DECLARED[len(before) :]


def test_a_component_built_from_a_mapping_takes_the_old_keyword_as_well() -> None:
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"Shelf\(deep=\)") as caught:
        shelf = Shelf.model_validate({"deep": 4, "load": 1})  # from a mapping
    assert shelf.depth == 4
    assert (caught[0].filename, caught[0].lineno) == (__file__, line_of("from a mapping"))


def test_a_keyword_renamed_twice_goes_to_the_name_it_has_now() -> None:
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"Tag\(caption=\)") as caught:
        assert Tag(caption="old").text == "old"
    assert len(caught) == 1


def test_the_new_keyword_does_not_warn_and_both_at_once_is_refused() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert Shelf(depth=2, load=1).depth == 2
        assert Tag("plain").text == "plain"
    with pytest.raises(TypeError, match="deep= and depth=, which are one keyword"):
        Shelf(deep=1, depth=2, load=1)


def test_only_an_init_that_names_the_new_keyword_is_wrapped() -> None:
    from millwork import ui

    assert ui.Card.__init__ is mw.Component.__init__
    assert ui.Card.renames == {}
    assert Shelf.__init__ is mw.Component.__init__
    assert Tag.__init__.__wrapped__ is not None
    assert LoudTag.__init__.__wrapped__ is not None
    assert not hasattr(OldStyleTag.__init__, "__wrapped__")
    assert not hasattr(PropsTag.__init__, "__wrapped__")


def test_code_without_a_module_name_warns_like_any_other() -> None:
    """What ``exec`` runs in a bare namespace has no ``__name__``."""
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"Shelf\(deep=\)") as caught:
        exec("Shelf(deep=1, load=1)", {"Shelf": Shelf})
    assert caught[0].filename == "<string>"


def test_python_prints_one_place_once_when_asked_for_its_default() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        for _ in range(3):
            OLD_WAY.warn()
    assert len(caught) == 1


def test_a_test_suite_can_refuse_them_every_time() -> None:
    """An error filter raises at every use, not at the first one of a line."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", mw.MillworkDeprecationWarning)
        for _ in range(2):
            with pytest.raises(mw.MillworkDeprecationWarning):
                Shelf(deep=1, load=1)


LIBRARY = """
from typing import ClassVar
from pydantic import field_validator
import millwork as mw
from millwork.deprecation import Deprecation, Renamed

WIDE = Deprecation('size="wide"', since="98.0", removed="99.0")

class Crate(mw.Component):
    type: ClassVar[str] = "crate"
    size: str = "narrow"
    slats: int = 1
    old_names: ClassVar[dict[str, Renamed]] = {
        "boards": Renamed("slats", since="98.0", removed="99.0")
    }

    @field_validator("size")
    @classmethod
    def _size(cls, size: str) -> str:
        if size == "wide":
            WIDE.warn()
        return size

def crates(n):
    return [Crate(boards=i) for i in range(n)]

BOX = Deprecation("Box", since="98.0", removed="99.0", instead="Crate")

def __getattr__(name):
    if name == "Box":
        BOX.warn()
        return Crate
    raise AttributeError(name)
"""


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A module whose frames are not the app's, as millwork's own are."""
    folder = tmp_path / "crates"
    folder.mkdir()
    (folder / "crate_lib.py").write_text(LIBRARY, encoding="utf-8")
    monkeypatch.syspath_prepend(str(folder))
    monkeypatch.setattr(
        deprecation,
        "_NOT_THE_APP",
        (*deprecation._NOT_THE_APP, os.path.normcase(str(folder) + os.sep)),
    )
    yield importlib.import_module("crate_lib")
    sys.modules.pop("crate_lib", None)


def test_a_warning_from_inside_the_framework_names_the_apps_line(library: Any) -> None:
    """Through a validator that pydantic runs, and through a helper that
    builds the component for the app."""
    with pytest.warns(mw.MillworkDeprecationWarning, match='size="wide"') as caught:
        library.Crate(size="wide")  # through a validator
    assert (caught[0].filename, caught[0].lineno) == (__file__, line_of("through a validator"))
    with pytest.warns(mw.MillworkDeprecationWarning, match=r"Crate\(boards=\)") as caught:
        library.crates(2)  # through a helper
    assert {(w.filename, w.lineno) for w in caught} == {(__file__, line_of("through a helper"))}


def test_a_retired_name_of_a_module_warns_where_it_is_imported(library: Any) -> None:
    with pytest.warns(mw.MillworkDeprecationWarning, match="Box is deprecated") as caught:
        from crate_lib import Box  # an old name
    assert Box is library.Crate
    assert (caught[0].filename, caught[0].lineno) == (__file__, line_of("an old name"))


def handler(s: Any) -> None:  # the handler
    """Something of the app's that a deprecation can be about."""


def test_what_is_noticed_while_no_app_code_runs_names_the_function_it_is_about() -> None:
    import functools

    class Callable_:
        def __call__(self, s: Any) -> None:  # the call
            """An instance that is a handler."""

    class Holder:
        def method(self, s: Any) -> None:  # the method
            """A bound method that is a handler."""

    cases = {
        handler: "the handler",
        functools.partial(handler, 1): "the handler",
        functools.wraps(handler)(lambda s: None): "the handler",
        Holder().method: "the method",
        functools.partial(Holder().method): "the method",
        Callable_(): "the call",
    }
    for about, mark in cases.items():
        with pytest.warns(mw.MillworkDeprecationWarning) as caught:
            OLD_WAY.warn(at=about)
        assert (caught[0].filename, caught[0].lineno) == (__file__, line_of(mark)), about
    # What has no code of its own to point at falls back on the line that runs.
    for about in (len, Holder, "text"):
        with pytest.warns(mw.MillworkDeprecationWarning) as caught:
            OLD_WAY.warn(at=about)  # falls back
        assert caught[0].lineno == line_of("falls back")


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deprecation, "_shown", True)
    monkeypatch.setattr(deprecation, "_logged", set())


def test_a_program_that_asked_gets_one_log_line_for_each_place(
    shown: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Once, whatever happens to Python's warning filters in between, which
    forget what they printed whenever a library changes them."""
    caplog.set_level(logging.WARNING, logger="millwork.deprecation")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(3):
            OLD_WAY.warn()  # logged once
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
        (BARE.warn(), BARE.warn("barer()"))  # two on one line
    lines = [r.getMessage() for r in caplog.records]
    assert lines == [
        f"{__file__}:{line_of('logged once')}: {OLD_WAY.message()}",
        f"{__file__}:{line_of('two on one line')}: {BARE.message()}",
        f"{__file__}:{line_of('two on one line')}: {BARE.message('barer()')}",
    ]


def test_the_log_line_is_written_even_when_the_warning_is_an_error(
    shown: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="millwork.deprecation")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(mw.MillworkDeprecationWarning):
            OLD_WAY.warn()
    assert len(caplog.records) == 1


def test_the_log_stops_taking_places_before_it_weighs_anything(
    shown: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deprecation, "_PLACES", 3)
    caplog.set_level(logging.WARNING, logger="millwork.deprecation")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for n in range(10):
            BARE.warn(f"made_as_it_runs_{n}()")
    assert len(caplog.records) == 3
    assert len(deprecation._logged) == 3


def test_nothing_is_logged_for_a_program_that_did_not_ask(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(deprecation, "_shown", False)
    caplog.set_level(logging.WARNING, logger="millwork.deprecation")
    with pytest.warns(mw.MillworkDeprecationWarning):
        OLD_WAY.warn()
    assert caplog.records == []


def test_a_declaration_names_two_minor_releases_in_order() -> None:
    before = list(deprecation.DECLARED)
    for version in ("1.2.3", "01.2", "v1.2", "1"):
        with pytest.raises(ValueError, match="not a minor release"):
            Deprecation("x", since=version, removed="2.0")
    with pytest.raises(ValueError, match="no later than"):
        Deprecation("x", since="1.3", removed="1.3")
    assert deprecation.DECLARED == before


def test_what_is_overdue_is_what_the_version_has_reached() -> None:
    assert OLD_WAY not in deprecation.overdue("98.4.1")
    for version in ("99.0.0rc1", "99.0.0.dev1", "99.0.0", "99.1.0", "100.0.0"):
        assert OLD_WAY in deprecation.overdue(version)
    renamed = Shelf.old_names["deep"]
    assert renamed in deprecation.overdue("99.0.0")
    assert renamed.message().startswith("Shelf(deep=) is deprecated")


def test_nothing_in_millwork_is_overdue_and_every_old_name_has_a_field() -> None:
    """The rule a release is held to: once the version reaches a deprecation's
    ``removed``, the old spelling is gone from the code. The version is the
    one the source says it is, whatever is installed."""
    for module in pkgutil.walk_packages(mw.__path__, "millwork."):
        if ".manual.pages" not in module.name:
            importlib.import_module(module.name)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    late = deprecation.overdue(project["project"]["version"])
    assert late == [], [d.message() for d in late]
    # millwork's own tests refuse millwork's own retired spellings.
    assert (
        "error::millwork.MillworkDeprecationWarning"
        in (project["tool"]["pytest"]["ini_options"]["filterwarnings"])
    )

    def subclasses(cls: type) -> list[type]:
        return [cls] + [s for c in cls.__subclasses__() for s in subclasses(c)]

    # No class of millwork's own still has a field under an old name.
    for cls in subclasses(mw.Component):
        if cls.__module__.startswith("millwork."):
            assert not deprecation.old_names_of(cls).keys() & cls.model_fields.keys(), cls


APP = """
import warnings
import millwork as mw
from millwork.deprecation import Deprecation

OLD = Deprecation("old_way()", since="98.0", removed="99.0")
app = mw.App("Shop")
OLD.warn()

def page():
    OLD.warn()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
"""


def run(tmp_path: Path, script: str, **env: str) -> str:
    (tmp_path / "shop.py").write_text(APP, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=tmp_path,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stderr


def test_a_served_app_logs_a_deprecation_once_for_each_line(tmp_path: Path) -> None:
    """As ``millwork run --reload`` starts its server, with a warning option
    in the environment that is about something else."""
    printed = run(
        tmp_path,
        """
        import os, sys
        from millwork import cli
        os.environ["MILLWORK_TARGET"] = "shop.py"
        cli.asgi_factory()
        shop = sys.modules["shop"]
        for _ in range(3):
            shop.page()
        """,
        PYTHONWARNINGS="ignore::ResourceWarning",
    )
    lines = [ln for ln in printed.split("\n") if "old_way() is deprecated" in ln]
    assert len(lines) == 2, printed
    assert lines[0].startswith("WARNING millwork.deprecation: ")
    assert "shop.py:8: " in lines[0]
    assert "shop.py:11: " in lines[1]


def test_every_command_that_loads_an_app_says_so(tmp_path: Path) -> None:
    printed = run(
        tmp_path,
        """
        import sys
        from millwork import cli
        sys.exit(cli.main(["routes", "shop.py"]))
        """,
    )
    assert printed.count("old_way() is deprecated") == 1
    assert "shop.py:8: " in printed


def signatures(source: str) -> dict[str, list[str]]:
    import ast

    sys.path.insert(0, str(ROOT / "scripts"))
    import typed_inits

    classes = {
        node.name: typed_inits.Klass(node, Path("shelf.py"))
        for node in ast.parse(textwrap.dedent(source)).body
        if isinstance(node, ast.ClassDef)
    }
    typed_inits.ACCEPTS["Shelf.load"] = "int | str"
    out = {}
    for name, klass in classes.items():
        if name != "Component":
            out[name] = typed_inits.signature(klass, classes)
            ast.parse("class X:\n" + "\n".join(out[name][1:]))  # well-formed
    return out


def test_the_typed_signature_takes_every_call_the_runtime_takes() -> None:
    """The old name with the new one's type, and the new one optional while
    the old one may stand in for it."""
    written = signatures("""
        class Component: ...

        class Shelf(Component):
            depth: int | None = None
            load: int
            old_names: ClassVar[dict[str, Renamed]] = {
                "deep": Renamed("depth", since="1.1", removed="1.2"),
                "weight": Renamed("load", since="1.1", removed="1.2"),
                "mass": Renamed("weight", since="1.0", removed="1.1"),
            }

        class TallShelf(Shelf):
            height: int = 2

        class Glyph(Component):
            name: str
            size: int
            old_names = {"icon": Renamed("name", since="1.1", removed="1.2")}

            def __init__(self, name: str, size: int, **props: Any) -> None:
                super().__init__(name=name, size=size, **props)

        class Picker(Component):
            choices: list[Option]
            old_names: ClassVar[dict[str, Renamed]] = {
                "options": Renamed("choices", since="1.1", removed="1.2")
            }
    """)
    for name in ("Shelf", "TallShelf"):
        lines = written[name]
        assert "            depth: int | None = None," in lines
        assert "            deep: int | None = ...,  # the old name of depth" in lines
    # A plain assignment is read as well.
    assert "            icon: str = ...,  # the old name of name" in written["Glyph"]
    # What a call may pass was written down for ``load`` on Shelf, and for
    # ``options`` wherever a field is called that: a renamed field keeps it.
    assert "            load: int | str = ...," in written["Shelf"]
    assert "            weight: int | str = ...,  # the old name of load" in written["Shelf"]
    assert "            mass: int | str = ...,  # the old name of load" in written["Shelf"]
    assert "            load: int = ...," in written["TallShelf"]
    choices = "Sequence[Option | str | tuple[str, str] | Mapping[str, Any]]"
    assert f"            choices: {choices} = ...," in written["Picker"]
    assert f"            options: {choices} = ...,  # the old name of choices" in written["Picker"]
    for name in ("Shelf", "TallShelf"):
        lines = written[name]
        assert not any(line.lstrip().startswith("old_names") for line in lines)
    glyph = written["Glyph"]
    assert "            name: str = ...," in glyph
    assert "            size: int = ...," in glyph
    assert glyph.index("            name: str = ...,") < glyph.index("            *children: Any,")
    assert "            icon: str = ...,  # the old name of name" in glyph


def test_the_generator_refuses_old_names_it_cannot_read() -> None:
    for body, said in {
        "old_names = dict(deep=Renamed('depth', since='1.1', removed='1.2'))": "written out",
        "old_names = OLD": "written out",
        "old_names = {'deep': Renamed(new='depth', since='1.1', removed='1.2')}": "written out",
        "old_names = {'deep': Renamed('wide', since='1.1', removed='1.2')}": "is no field",
        "old_names = {'a': Renamed('b', since='1.1', removed='1.2'),"
        " 'b': Renamed('a', since='1.1', removed='1.2')}": "in a circle",
    }.items():
        source = (
            f"class Component: ...\n\nclass Shelf(Component):\n    depth: int = 1\n    {body}\n"
        )
        with pytest.raises(SystemExit, match=said):
            signatures(source)
