"""The HTML page that loads the bundle.

Built from the bundle's Vite manifest so asset names can be hashed and
cached for a year. The theme's CSS variables are rendered here, before the
bundle loads, so there is no flash of the default theme.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import cast

from millwork.protocol import PROTOCOL_VERSION
from millwork.theme import Theme

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


class Shell:
    def __init__(self, bundle_dir: Path, prefix: str) -> None:
        self.bundle_dir = bundle_dir
        self.prefix = prefix
        self._manifest: dict[str, dict[str, object]] | None = None
        self._load()

    def _load(self) -> None:
        manifest = self.bundle_dir / ".vite" / "manifest.json"
        if manifest.is_file():
            self._manifest = json.loads(manifest.read_text(encoding="utf-8"))
        else:
            self._manifest = None

    @property
    def available(self) -> bool:
        return self._manifest is not None

    def _entry(self) -> dict[str, object]:
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
    ) -> str:
        entry = self._entry()
        if theme is not None:
            theme_css = theme.css() + theme_css
            head = theme.head() + head
            lang = theme.locale
            if theme.favicon:
                head += f'<link rel="icon" href="{html.escape(theme.favicon)}">'
        asset = f"{self.prefix}/assets/"
        scripts = f'<script type="module" src="{asset}{_basename(str(entry["file"]))}"></script>'
        css_files = cast(list[str], entry.get("css", []))
        styles = "".join(
            f'<link rel="stylesheet" href="{asset}{_basename(css)}">' for css in css_files
        )
        # After the bundle's stylesheet: both declare :root tokens and the later wins.
        styles = styles + f'<style id="mw-theme">{theme_css}</style>'
        payload: dict[str, object] = {
            "path": path,
            "protocol": PROTOCOL_VERSION,
            "ws": f"{self.prefix}/ws",
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
