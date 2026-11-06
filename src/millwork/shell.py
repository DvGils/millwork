"""The HTML page that loads the bundle.

Built from the bundle's Vite manifest so asset names can be hashed and
cached for a year. The theme's CSS variables are rendered here, before the
bundle loads, so there is no flash of the default theme.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from millwork.protocol import PROTOCOL_VERSION
from millwork.theme import Theme, under

_PREFIX = re.compile(r"^(/[A-Za-z0-9._~-]+)*/?$")


def check_prefix(value: str) -> str:
    """A path prefix as the server may be told it: plain path segments, or empty.
    Anything else is refused up front, since the prefix is written into HTML,
    CSS and cookie paths."""
    if not _PREFIX.match(value) or any(seg in (".", "..") for seg in value.split("/")):
        raise ValueError(f"the path prefix must be a plain path such as /sales, got {value!r}")
    return value.rstrip("/")


def root_of(scope: Mapping[str, Any]) -> str:
    """The path prefix the app runs under, from the ASGI scope and nothing else:
    the server is told it (``--root-path``) or a mount sets it. Never a request
    header, which a client could write. Empty at the root, else ``/prefix``."""
    return check_prefix(str(scope.get("root_path") or ""))


TEMPLATE = """<!doctype html>
<html lang="{lang}" data-density="{density}" data-scrollbars="{scrollbars}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{head}
<script{nonce}>window.__mw = {boot};</script>
<script{nonce}>{mode_script}</script>
{styles}
{scripts}
</head>
<body><div id="root"></div></body>
</html>
"""


# Runs before the stylesheet applies: the viewer's stored choice, else the theme's
# mode, decides the dark class, so the first paint is already the right scheme.
MODE_SCRIPT = (
    '(function(){var m=null;try{m=localStorage.getItem("mw:mode")}catch(e){}'
    'm=m||(window.__mw.theme||{}).mode||"system";'
    'if(m==="dark"||(m==="system"&&matchMedia("(prefers-color-scheme: dark)").matches))'
    'document.documentElement.classList.add("dark")})();'
)


PLAIN_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script{nonce}>window.__mw = {{}};</script>
<script{nonce}>{mode_script}</script>
<style{nonce}>{css}</style>
</head>
<body>
<main><h1>{title}</h1><p>{text}</p><p><a href="{home_href}">{home}</a></p></main>
</body>
</html>
"""

# The look of the page above: the theme's surface, ink and font, so even a
# failure before the bundle runs is in the app's colours. The stock tokens
# come first; a theme's own blocks follow and win.
PLAIN_DEFAULTS = (
    ":root{--background:#fff;--foreground:#0a0a0a;--muted-foreground:#737373;--primary:#171717}"
    ".dark{--background:#0a0a0a;--foreground:#fafafa;--muted-foreground:#a1a1a1;--primary:#e5e5e5}"
)
PLAIN_CSS = (
    "html{{background:var(--background);color:var(--foreground);"
    "font-family:var(--font-sans,system-ui,sans-serif)}}"
    "body{{margin:0;min-height:100dvh;display:flex;align-items:center;justify-content:center}}"
    "main{{max-width:24rem;padding:1.5rem}}"
    "h1{{font-size:1.5rem;font-weight:600;letter-spacing:-0.02em;margin:0 0 .5rem}}"
    "p{{margin:0 0 1rem;color:var(--muted-foreground);line-height:1.5}}"
    "a{{color:var(--primary);text-decoration:underline;text-underline-offset:4px}}"
)


def plain(*, title: str, text: str, theme: Theme, nonce: str | None = None, base: str = "") -> str:
    """An HTML page without the bundle, for a failure before it can run: not found
    without a built bundle, an exception in an app's own route."""
    return PLAIN_TEMPLATE.format(
        lang=html.escape(theme.locale),
        title=html.escape(title),
        text=html.escape(text),
        home=html.escape(theme.text("home")),
        home_href=html.escape(f"{base}/"),
        nonce=f' nonce="{html.escape(nonce)}"' if nonce else "",
        mode_script=MODE_SCRIPT,
        css=PLAIN_DEFAULTS + theme.css(base) + PLAIN_CSS.format(),
    )


class Shell:
    def __init__(self, bundle_dir: Path, prefix: str) -> None:
        self.bundle_dir = bundle_dir
        self.prefix = prefix
        self._manifest: dict[str, dict[str, object]] | None = None
        self._stamp = 0.0
        self._load()

    def _load(self) -> None:
        # Re-read when the file changes: a bundle rebuilt under a running process
        # has new hashed names, and a page must name the files that exist now.
        manifest = self.bundle_dir / ".vite" / "manifest.json"
        try:
            stamp = manifest.stat().st_mtime
        except OSError:
            self._manifest, self._stamp = None, 0.0
            return
        if stamp != self._stamp or self._manifest is None:
            self._manifest = json.loads(manifest.read_text(encoding="utf-8"))
            self._stamp = stamp

    @property
    def available(self) -> bool:
        self._load()
        return self._manifest is not None

    def _entry(self) -> dict[str, object]:
        self._load()
        assert self._manifest is not None
        for item in self._manifest.values():
            if item.get("isEntry"):
                return item
        raise RuntimeError("the bundle manifest has no entry")

    def render(
        self,
        *,
        title: str,
        path: str,
        lang: str = "en",
        theme_css: str = "",
        head: str = "",
        login: dict[str, object] | None = None,
        theme: Theme | None = None,
        user: dict[str, object] | None = None,
        nonce: str | None = None,
        keep_alive: bool = False,
        components: dict[str, str] | None = None,
        base: str = "",
    ) -> str:
        """``base`` is the path prefix the app runs under: every URL the page
        carries is under it, while ``path`` stays the app's own."""
        entry = self._entry()
        if theme is not None:
            theme_css = theme.css(base) + theme_css
            head = theme.head() + head
            lang = theme.locale
            # Always a link: without one the browser asks the host's root for
            # /favicon.ico, which an app under a prefix never sees.
            icon = under(base, theme.favicon) if theme.favicon else f"{base}/favicon.ico"
            head += f'<link rel="icon" href="{html.escape(icon or "")}">'
        asset = html.escape(f"{base}{self.prefix}/assets/")
        scripts = f'<script type="module" src="{asset}{_basename(str(entry["file"]))}"></script>'
        css_files = cast(list[str], entry.get("css", []))
        styles = "".join(
            f'<link rel="stylesheet" href="{asset}{_basename(css)}">' for css in css_files
        )
        # After the bundle's stylesheet: both declare :root tokens and the later wins.
        styles = styles + f'<style id="mw-theme">{theme_css}</style>'
        if theme is not None and theme.stylesheet:
            # Last, so the app's rules win over the theme's where they meet.
            href = html.escape(under(base, theme.stylesheet) or "")
            styles += f'<link rel="stylesheet" id="mw-stylesheet" href="{href}">'
        payload: dict[str, object] = {
            "path": path,
            "base": base,
            "protocol": PROTOCOL_VERSION,
            "ws": f"{base}{self.prefix}/ws",
        }
        if keep_alive:
            payload["keep_alive"] = True
        if components:
            payload["components"] = components
        if theme is not None:
            payload["theme"] = theme.boot()
        if user is not None:
            payload["user"] = user
        if login is not None:
            payload["login"] = login
        boot = _script_safe(json.dumps(payload))
        return TEMPLATE.format(
            lang=html.escape(lang),
            density=theme.density if theme else "comfortable",
            scrollbars=theme.scrollbars if theme else "thin",
            title=html.escape(title),
            head=head,
            boot=boot,
            nonce=f' nonce="{html.escape(nonce)}"' if nonce else "",
            mode_script=MODE_SCRIPT,
            styles=styles,
            scripts=scripts,
        )


def _basename(file: str) -> str:
    return file.split("/")[-1]


def _script_safe(text: str) -> str:
    """JSON inside a <script>: nothing in it may close the element or open a comment."""
    return (
        text.replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
