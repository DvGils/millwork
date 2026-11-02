"""Theme: the file validated, rendered into the shell, strings by locale, Header in the tree."""

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import millwork as mw
from millwork import ui
from millwork.nodes import build
from millwork.shell import Shell
from millwork.theme import STRINGS, Font, Theme


def test_tokens_are_checked_by_name_and_value() -> None:
    with pytest.raises(ValueError, match="unknown theme token"):
        Theme(tokens={"light": {"brand": "#fff"}})
    with pytest.raises(ValueError, match="CSS cannot take"):
        Theme(tokens={"light": {"primary": "red;}</style>"}})
    with pytest.raises(ValueError, match="CSS cannot take"):
        Theme(tokens={"light": {"primary": "url(https://x)"}})
    with pytest.raises(ValueError, match="src .* or url"):
        Font(family="X", src="/public/x.woff2", url="https://fonts.example/x")
    with pytest.raises(ValueError, match="same-origin path"):
        Theme(logo="//evil.example/logo.svg")
    with pytest.raises(ValueError, match="unknown interface strings"):
        Theme(strings={"hello": "hi"})
    with pytest.raises(ValueError, match="locale"):
        Theme(locale="nl_NL; x")


def test_css_head_and_strings() -> None:
    theme = Theme(
        fonts=[
            Font(family="Montserrat", src="/public/fonts/montserrat.woff2"),
            Font(family="Inter", url="https://fonts.example/inter.css"),
        ],
        tokens={
            "light": {"primary": "oklch(0.52 0.17 150)", "radius": "0.5rem"},
            "dark": {"primary": "#9fd"},
        },
        locale="nl",
        strings={"send": "Stuur"},
        logo="/public/logo.svg",
    )
    css = theme.css()
    assert css.startswith(
        "@font-face{font-family:'Montserrat';src:url(/public/fonts/montserrat.woff2)"
    )
    assert "format('woff2')" in css
    assert ":root{--primary:oklch(0.52 0.17 150);--radius:0.5rem}" in css
    assert ".dark{--primary:#9fd}" in css
    assert theme.head() == '<link rel="stylesheet" href="https://fonts.example/inter.css">'
    strings = theme.all_strings()
    assert strings["send"] == "Stuur" and strings["sign_in"] == "Sign in"
    assert set(strings) == set(STRINGS)
    assert theme.boot()["logo"] == {"light": "/public/logo.svg", "dark": None}


def test_shell_renders_theme_mode_script_and_boot(tmp_path: Path) -> None:
    (tmp_path / ".vite").mkdir()
    (tmp_path / ".vite" / "manifest.json").write_text(
        json.dumps(
            {"src/main.tsx": {"file": "main-abc.js", "isEntry": True, "css": ["main-abc.css"]}}
        )
    )
    shell = Shell(tmp_path, prefix="/_mw")
    theme = Theme(
        tokens={"light": {"primary": "#123"}},
        density="compact",
        scrollbars="thin",
        locale="nl",
        favicon="/public/favicon.svg",
        mode="dark",
    )
    html = shell.render(title="T", path="/", theme=theme, user={"id": "u", "name": "U"})
    assert '<html lang="nl" data-density="compact" data-scrollbars="thin">' in html
    assert '<style id="mw-theme">:root{--primary:#123}</style>' in html
    assert '<link rel="icon" href="/public/favicon.svg">' in html
    assert 'localStorage.getItem("mw:mode")' in html
    boot = json.loads(html.split("window.__mw = ")[1].split(";</script>")[0])
    assert boot["theme"]["mode"] == "dark" and boot["theme"]["strings"]["sign_in"] == "Sign in"
    assert boot["user"] == {"id": "u", "name": "U"}
    # Without a theme the shell still carries the style element the dev push targets.
    plain = shell.render(title="T", path="/")
    assert '<style id="mw-theme"></style>' in plain and 'data-density="comfortable"' in plain


def test_app_picks_up_public_theme_and_serves_the_favicon(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "theme.json").write_text(
        json.dumps({"favicon": "/public/favicon.png", "density": "compact", "locale": "nl"})
    )
    app = mw.App("t", public=public, bundle_dir=tmp_path)

    @app.page("/")
    def home(s: mw.Session) -> ui.Component:
        return ui.Page(ui.Text("hi", key="t"))

    assert app.theme.density == "compact" and app.theme.locale == "nl"
    with TestClient(app.asgi) as client:
        r = client.get("/favicon.ico", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/public/favicon.png"
    with pytest.raises(ValueError, match="not valid JSON"):
        (public / "theme.json").write_text("{nope")
        mw.App("t", public=public, bundle_dir=tmp_path)


def test_header_links_become_slots() -> None:
    page = ui.Page(
        ui.Text("body", key="b"),
        header=ui.Header(
            title="App",
            links=[ui.Link(label="Docs", href="/docs", key="docs"), ui.Link(label="x", href="/x")],
            user_menu=False,
        ),
    )
    tree = build(page, "root")
    header = tree.nodes["root/@header"]
    assert header.type == "Header" and header.props["title"] == "App"
    assert header.props["links"] == [
        {"$node": "root/@header/@links.docs"},
        {"$node": "root/@header/@links.1"},
    ]
    assert tree.nodes["root/@header/@links.docs"].props["href"] == "/docs"
    assert header.props["user_menu"] is False
    assert tree.nodes["root"].props["header"] == {"$node": "root/@header"}


def test_shell_picks_up_a_rebuilt_bundle(tmp_path: Path) -> None:
    """A rebuild under a running process has new hashed names; the next page names them."""
    import json
    import os

    from millwork.shell import Shell

    (tmp_path / ".vite").mkdir()
    manifest = tmp_path / ".vite" / "manifest.json"

    def write(name: str, stamp: float) -> None:
        manifest.write_text(json.dumps({"src/main.tsx": {"file": name, "isEntry": True}}))
        os.utime(manifest, (stamp, stamp))

    write("main-old.js", 1_000)
    shell = Shell(tmp_path, prefix="/_mw")
    assert "main-old.js" in shell.render(title="t", path="/")
    write("main-new.js", 2_000)
    html = shell.render(title="t", path="/")
    assert "main-new.js" in html and "main-old.js" not in html


def test_currency_is_an_iso_code_and_reaches_the_boot() -> None:
    import pytest

    from millwork.theme import Theme

    assert Theme().boot()["currency"] == "EUR"
    assert Theme(currency="USD").boot()["currency"] == "USD"
    with pytest.raises(ValueError, match="ISO 4217"):
        Theme(currency="euro")
