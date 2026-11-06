// The theme at runtime: the mode (light, dark, system) the viewer chose,
// kept in the browser; the strings the bundle's own controls need, in the
// app's language; density and scrollbars as attributes on <html>.
// The token CSS itself is in the shell before this code runs.

import { useEffect, useState } from "react";
import { safeUrl } from "./lib";

export type Mode = "light" | "dark" | "system";

export interface ThemeBoot {
  mode: Mode;
  logo: { light: string; dark?: string | null } | null;
  login_image?: string | null;
  stylesheet?: string | null;
  density: "comfortable" | "compact";
  scrollbars: "auto" | "thin";
  locale: string;
  currency?: string;
  strings: Record<string, string>;
}

const FALLBACK: ThemeBoot = {
  mode: "system",
  logo: null,
  density: "comfortable",
  scrollbars: "thin",
  locale: "en",
  strings: {},
};

const STORAGE = "mw:mode";

function boot(): ThemeBoot {
  const w = window as unknown as { __mw?: { theme?: ThemeBoot } };
  return w.__mw?.theme ?? FALLBACK;
}

export function theme(): ThemeBoot {
  return boot();
}

// A string by key, with {name} placeholders filled in.
export function t(key: string, vars?: Record<string, string | number>): string {
  let s = boot().strings[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
  return s;
}

export function locale(): string {
  return boot().locale;
}

export function currency(): string {
  return boot().currency ?? "EUR";
}

export function getMode(): Mode {
  try {
    const stored = localStorage.getItem(STORAGE);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // storage may be unavailable
  }
  return boot().mode;
}

function isDark(mode: Mode): boolean {
  return mode === "dark" || (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
}

const listeners = new Set<() => void>();

export function applyMode(mode: Mode = getMode()) {
  document.documentElement.classList.toggle("dark", isDark(mode));
  for (const l of listeners) l();
}

export function setMode(mode: Mode) {
  try {
    if (mode === boot().mode) localStorage.removeItem(STORAGE);
    else localStorage.setItem(STORAGE, mode);
  } catch {
    // storage may be unavailable; the choice lasts for this page
  }
  applyMode(mode);
}

// The resolved scheme, re-rendering on changes of the choice or of the system.
export function useScheme(): "light" | "dark" {
  const [scheme, setScheme] = useState<"light" | "dark">(() => (isDark(getMode()) ? "dark" : "light"));
  useEffect(() => {
    const update = () => setScheme(isDark(getMode()) ? "dark" : "light");
    listeners.add(update);
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onMedia = () => {
      if (getMode() === "system") applyMode("system");
    };
    media.addEventListener("change", onMedia);
    return () => {
      listeners.delete(update);
      media.removeEventListener("change", onMedia);
    };
  }, []);
  return scheme;
}

export function useMode(): [Mode, (m: Mode) => void] {
  const [mode, set] = useState<Mode>(getMode);
  useEffect(() => {
    const update = () => set(getMode());
    listeners.add(update);
    return () => void listeners.delete(update);
  }, []);
  return [mode, setMode];
}

export function isCompact(): boolean {
  return boot().density === "compact";
}

// The app's own stylesheet, which the shell links at start. A pushed theme
// may name another one or none, and the file itself may have changed, so it is
// fetched again under a new query.
function linkStylesheet(path: string | null | undefined) {
  const current = document.getElementById("mw-stylesheet");
  if (!path) {
    current?.remove();
    return;
  }
  const link = (current as HTMLLinkElement | null) ?? document.createElement("link");
  link.id = "mw-stylesheet";
  link.rel = "stylesheet";
  link.href = `${safeUrl(path)}?v=${Date.now()}`;
  if (!current) document.head.appendChild(link);
}

// Paper is light: a page printed from the dark scheme would put pale text on
// white, so the scheme steps aside while the browser prints.
export function printInLight() {
  window.addEventListener("beforeprint", () => document.documentElement.classList.remove("dark"));
  window.addEventListener("afterprint", () => applyMode());
}

// Applied once at start and again when the server pushes a changed theme.
export function applyTheme(next?: { css?: string; boot?: ThemeBoot }) {
  if (next?.boot) {
    const w = window as unknown as { __mw: { theme?: ThemeBoot } };
    w.__mw.theme = next.boot;
  }
  if (typeof next?.css === "string") {
    const el = document.getElementById("mw-theme");
    if (el) el.textContent = next.css;
  }
  if (next?.boot) linkStylesheet(next.boot.stylesheet);
  const b = boot();
  document.documentElement.dataset.density = b.density;
  document.documentElement.dataset.scrollbars = b.scrollbars;
  document.documentElement.lang = b.locale;
  applyMode();
}
