"""The theme: one JSON file per app, rendered into the HTML shell by the server.

Tokens use the shadcn vocabulary in CSS colour syntax,
plus ``success``, ``warning`` and ``info`` for the catalogue's tones. A
token left out keeps the bundle's default. Fonts are self-hosted from
``public/``; a font service URL is accepted and logged once. The few
interface strings the bundle needs are English here; an app in another
language sets them in its theme file.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

log = logging.getLogger("millwork.theme")

Mode = Literal["light", "dark", "system"]
Density = Literal["comfortable", "compact"]
Scrollbars = Literal["auto", "thin"]

COLOUR_TOKENS = (
    "background",
    "foreground",
    "card",
    "card-foreground",
    "popover",
    "popover-foreground",
    "primary",
    "primary-foreground",
    "secondary",
    "secondary-foreground",
    "muted",
    "muted-foreground",
    "accent",
    "accent-foreground",
    "destructive",
    "destructive-foreground",
    "success",
    "success-foreground",
    "warning",
    "warning-foreground",
    "info",
    "info-foreground",
    "border",
    "input",
    "ring",
    "chart-1",
    "chart-2",
    "chart-3",
    "chart-4",
    "chart-5",
    "sidebar",
    "sidebar-foreground",
    "sidebar-primary",
    "sidebar-primary-foreground",
    "sidebar-accent",
    "sidebar-accent-foreground",
    "sidebar-border",
    "sidebar-ring",
)
OTHER_TOKENS = ("radius", "font-sans", "font-mono", "font-heading")
TOKENS = frozenset(COLOUR_TOKENS + OTHER_TOKENS)

# A token value is one CSS value: colours, lengths, font stacks. Nothing that
# could close the declaration or the style element, and no url().
_VALUE = re.compile(r"^[A-Za-z0-9 #%().,'\"/+*_-]+$")
_FORBIDDEN = re.compile(r"url\s*\(|expression\s*\(|@|\\|</", re.IGNORECASE)
_PATH = re.compile(r"^/(?!/)[A-Za-z0-9._~/-]+$")

STRINGS: dict[str, str] = {
    "loading": "Loading…",
    "disconnected": "Disconnected.",
    "reconnecting": "Reconnecting…",
    "other_tab": "This page was opened in another tab.",
    "copied": "Copied",
    "working": "Working",
    "thinking": "Thinking",
    "thought": "Thought",
    "steps": "{n} steps",
    "send": "Send",
    "stop": "Stop",
    "attach": "Attach",
    "remove": "Remove",
    "actions": "Actions",
    "download": "Download",
    "add": "Add",
    "choose": "Choose",
    "search": "Search",
    "no_results": "No results",
    "open": "Open",
    "download_failed": "The download failed.",
    "filter": "Filter",
    "all": "All",
    "min": "Min",
    "max": "Max",
    "clear": "Clear",
    "select_all": "Select all",
    "select_row": "Select row",
    "dismiss": "Dismiss",
    "sign_in": "Sign in",
    "sign_in_hint": "Sign in to continue.",
    "sign_in_failed": "Sign-in failed",
    "username": "Username",
    "password": "Password",
    "continue_with": "Continue with {provider}",
    "no_sign_in": "No sign-in method is configured.",
    "sign_out": "Sign out",
    "theme": "Theme",
    "light": "Light",
    "dark": "Dark",
    "system": "System",
    "menu": "Menu",
}


def _check_path(value: str, what: str) -> str:
    if not _PATH.match(value):
        raise ValueError(
            f"{what} must be a same-origin path such as /public/logo.svg, got {value!r}"
        )
    return value


class Font(BaseModel):
    """One ``@font-face``, or one stylesheet link when ``url`` is a font service."""

    model_config = ConfigDict(extra="forbid")

    family: str
    src: str | None = None
    url: str | None = None
    weights: str = "100 900"
    style: Literal["normal", "italic"] = "normal"

    @model_validator(mode="after")
    def _one_source(self) -> Font:
        if (self.src is None) == (self.url is None):
            raise ValueError("a font takes src (a file under public/) or url (a font service)")
        if self.src is not None:
            _check_path(self.src, "font src")
        if self.url is not None and not self.url.startswith("https://"):
            raise ValueError("a font url must be https")
        if not re.match(r"^[A-Za-z0-9 _-]+$", self.family):
            raise ValueError(f"font family name {self.family!r} has characters CSS cannot take")
        if not re.match(r"^[0-9 ]+$", self.weights):
            raise ValueError("font weights is a number or a range such as '100 900'")
        return self

    def css(self) -> str:
        assert self.src is not None
        fmt = {"woff2": "woff2", "woff": "woff", "ttf": "truetype", "otf": "opentype"}.get(
            self.src.rsplit(".", 1)[-1].lower(), ""
        )
        src = f"url({self.src})" + (f" format('{fmt}')" if fmt else "")
        return (
            f"@font-face{{font-family:'{self.family}';src:{src};"
            f"font-weight:{self.weights};font-style:{self.style};font-display:swap}}"
        )


class Logo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    light: str
    dark: str | None = None

    _light = field_validator("light")(staticmethod(lambda v: _check_path(v, "logo")))
    _dark = field_validator("dark")(staticmethod(lambda v: v and _check_path(v, "logo")))


class Theme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode = "system"
    fonts: list[Font] = Field(default_factory=list)
    tokens: dict[Literal["light", "dark"], dict[str, str]] = Field(default_factory=dict)
    logo: Logo | None = None
    favicon: str | None = None
    login_image: str | None = None
    scrollbars: Scrollbars = "thin"
    density: Density = "comfortable"
    locale: str = "en"
    strings: dict[str, str] = Field(default_factory=dict)

    _favicon = field_validator("favicon")(staticmethod(lambda v: v and _check_path(v, "favicon")))
    _image = field_validator("login_image")(
        staticmethod(lambda v: v and _check_path(v, "login_image"))
    )

    @field_validator("logo", mode="before")
    @classmethod
    def _logo_shorthand(cls, v: Any) -> Any:
        return {"light": v} if isinstance(v, str) else v

    @field_validator("tokens")
    @classmethod
    def _known_tokens(cls, tokens: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        for scheme, values in tokens.items():
            for name, value in values.items():
                if name not in TOKENS:
                    raise ValueError(f"unknown theme token {name!r} in {scheme}")
                if not _VALUE.match(value) or _FORBIDDEN.search(value):
                    raise ValueError(f"theme token {name} has a value CSS cannot take: {value!r}")
        return tokens

    @field_validator("locale")
    @classmethod
    def _locale(cls, v: str) -> str:
        if not re.match(r"^[a-z]{2}(-[A-Za-z]{2,4})?$", v):
            raise ValueError(f"locale must look like 'nl' or 'en-GB', got {v!r}")
        return v

    @field_validator("strings")
    @classmethod
    def _known_strings(cls, strings: dict[str, str]) -> dict[str, str]:
        unknown = set(strings) - set(STRINGS)
        if unknown:
            raise ValueError(f"unknown interface strings: {sorted(unknown)}")
        return strings

    @classmethod
    def load(cls, path: Path) -> Theme:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: not valid JSON ({exc})") from exc
        return cls.model_validate(data)

    # ------------------------------------------------------------- rendering

    def css(self) -> str:
        """The style element's text: font faces, then the two token blocks."""
        parts = [f.css() for f in self.fonts if f.src is not None]
        light = self.tokens.get("light", {})
        dark = self.tokens.get("dark", {})
        for selector, values in ((":root", light), (".dark", dark)):
            if values:
                body = ";".join(f"--{name}:{value}" for name, value in values.items())
                parts.append(f"{selector}{{{body}}}")
        return "".join(parts)

    def head(self) -> str:
        """Stylesheet links for font-service fonts; empty for a self-hosted theme."""
        links = []
        for f in self.fonts:
            if f.url is not None:
                log.warning("theme font %s loads from %s on every page view", f.family, f.url)
                safe = f.url.replace('"', "%22")
                links.append(f'<link rel="stylesheet" href="{safe}">')
        return "".join(links)

    def all_strings(self) -> dict[str, str]:
        return {**STRINGS, **self.strings}

    def boot(self) -> dict[str, Any]:
        """What the bundle reads at start."""
        return {
            "mode": self.mode,
            "logo": self.logo.model_dump() if self.logo else None,
            "login_image": self.login_image,
            "density": self.density,
            "scrollbars": self.scrollbars,
            "locale": self.locale,
            "strings": self.all_strings(),
        }


def find_theme(public_dir: Path | None) -> Theme:
    """``public/theme.json`` when the app has one, the default theme otherwise."""
    if public_dir is not None:
        candidate = public_dir / "theme.json"
        if candidate.is_file():
            theme = Theme.load(candidate)
            log.info("theme loaded from %s", candidate)
            return theme
    return Theme()


__all__ = ["Font", "Logo", "STRINGS", "TOKENS", "Theme", "find_theme"]
