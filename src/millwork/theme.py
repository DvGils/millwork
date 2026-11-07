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
    "reconnecting": "Reconnecting…",
    "session_ended": "This session has ended.",
    "reload": "Reload",
    "other_tab": "This page was opened in another tab.",
    "copied": "Copied",
    "working": "Working",
    "thinking": "Thinking",
    "thought": "Thought",
    "steps": "{n} steps",
    "one_step": "1 step",
    "send": "Send",
    "stop": "Stop",
    "attach": "Attach",
    "remove": "Remove",
    "copy": "Copy",
    "you": "You",
    "assistant": "Assistant",
    "messages": "Messages",
    "scroll_to_end": "Scroll to end",
    "good_response": "Good response",
    "bad_response": "Bad response",
    "feedback_prompt": "What could be better?",
    "skip": "Skip",
    "regenerate": "Regenerate",
    "edit": "Edit",
    "save": "Save",
    "cancel": "Cancel",
    "ok": "OK",
    "other": "Other",
    "type": "Type",
    "one_row": "1 row",
    "rows": "{n} rows",
    "rows_of": "{shown} of {n} rows",
    "type_message": "Type a message",
    "drop_file": "Drop a file or click to choose",
    "drop_files": "Drop files or click to choose",
    # Why an upload was refused. The tab puts the file's name and a colon in
    # front, so these start in lower case and end without a full stop.
    "file_too_large": "the file is larger than {mb} MB",
    "file_empty": "the file is empty",
    "file_not_valid": "the file is not a valid .{ext}",
    "file_not_text": "the file is not UTF-8 text",
    "file_not_accepted": "this type of file is not accepted; expected {expected}",
    "file_failed": "the upload failed",
    "file_interrupted": "the upload was interrupted",
    "disconnected": "the connection was lost",
    "file_quota": "the session's file quota is used up",
    "file_space": "the server's file space is used up",
    "issue_required": "This is required.",
    "issue_too_short": "At least {n} characters.",
    "issue_too_long": "At most {n} characters.",
    "issue_too_long_one": "At most 1 character.",
    "issue_too_few": "The minimum is {n}.",
    "issue_too_many": "The maximum is {n}.",
    "issue_above": "More than {n}.",
    "issue_min": "At least {n}.",
    "issue_below": "Less than {n}.",
    "issue_max": "At most {n}.",
    "issue_whole_number": "Enter a whole number.",
    "issue_number": "Enter a number.",
    "issue_choice": "Choose one of the options.",
    "issue_format": "This is not in the expected format.",
    "issue_date": "Enter a date.",
    "issue_datetime": "Enter a date and a time.",
    "issue_time": "Enter a time.",
    "issue_url": "Enter a web address.",
    "canceled": "Canceled",
    "failed": "Failed",
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
    "close": "Close",
    "toggle_sidebar": "Toggle sidebar",
    "previous": "Previous",
    "next": "Next",
    "wait_for_reply": "Wait for the current reply to finish.",
    "message_too_long": "The message is too long.",
    "reply_failed": "The reply failed.",
    "something_went_wrong": "Something went wrong.",
    "no_page": "No page at {path}.",
    "not_found_title": "Page not found",
    "not_found_text": "There is nothing at {path}.",
    "forbidden_title": "No access",
    "forbidden_text": "You may not open this page.",
    "home": "Home",
    "try_again": "Try again in a moment.",
    "page_failed": "The page failed to start.",
    "render_failed": "The page failed to render.",
    "too_many_sessions": "Too many open sessions.",
    "too_many_actions": "Too many actions at once; wait a moment.",
    "signed_out": "Signed out.",
    "made_room": "This session made room for a newer one.",
    "sign_in": "Sign in",
    "sign_in_hint": "Sign in to continue.",
    "sign_in_failed": "Sign-in failed",
    "username": "Username",
    "password": "Password",
    "show_password": "Show password",
    "continue_with": "Continue with {provider}",
    "or": "or",
    "no_sign_in": "No sign-in method is configured.",
    "proxy_sign_in": "Sign-in happens before this app, and this request carried no identity.",
    "proxy_denied": "You are signed in, but this app does not admit you.",
    "sign_out": "Sign out",
    "theme": "Theme",
    "light": "Light",
    "dark": "Dark",
    "system": "System",
    "menu": "Menu",
}


def under(base: str, path: str | None) -> str | None:
    """A same-origin path as the browser must ask for it: under the app's prefix
    when the app runs under one. Anything that is not a path is left alone."""
    if base and path and path.startswith("/"):
        return base + path
    return path


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

    def css(self, base: str = "") -> str:
        assert self.src is not None
        fmt = {"woff2": "woff2", "woff": "woff", "ttf": "truetype", "otf": "opentype"}.get(
            self.src.rsplit(".", 1)[-1].lower(), ""
        )
        src = f"url({under(base, self.src)})" + (f" format('{fmt}')" if fmt else "")
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
    currency: str = "EUR"
    strings: dict[str, str] = Field(default_factory=dict)
    # The app's own stylesheet, a file under public/, loaded after the theme.
    stylesheet: str | None = None

    _stylesheet = field_validator("stylesheet")(
        staticmethod(lambda v: v and _check_path(v, "stylesheet"))
    )
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

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError(f"currency is an ISO 4217 code such as 'EUR' or 'USD', got {v!r}")
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

    def css(self, base: str = "") -> str:
        """The style element's text: font faces, then the two token blocks. ``base``
        is the path prefix the app runs under, for the font files."""
        parts = [f.css(base) for f in self.fonts if f.src is not None]
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

    def text(self, key: str, **vars: Any) -> str:
        """A message the server sends to a person, in the theme's words."""
        s = self.all_strings()[key]
        for name, value in vars.items():
            s = s.replace("{" + name + "}", str(value))
        return s

    def boot(self) -> dict[str, Any]:
        """What the bundle reads at start. Image paths are the app's own: the
        bundle puts every same-origin path under the prefix when it renders it."""
        return {
            "mode": self.mode,
            "logo": self.logo.model_dump() if self.logo else None,
            "login_image": self.login_image,
            "stylesheet": self.stylesheet,
            "density": self.density,
            "scrollbars": self.scrollbars,
            "locale": self.locale,
            "currency": self.currency,
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
