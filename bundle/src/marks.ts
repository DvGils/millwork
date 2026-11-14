// Highlights: the marks the session holds for this page, as it last gave
// them. The session works out which components they stand for and which
// of them show now. Here they are kept as the session last gave them, for
// the layer in marks-layer.tsx to draw.

import { useSyncExternalStore } from "react";

export interface Mark {
  // Its number in the session, which a mark is said by.
  n: number;
  // The node it is on, and the pointer of a form's field when it is on one.
  id: string;
  field?: string;
  color: string;
  style: "solid" | "pulse" | "trace";
  step?: number;
  label?: string;
  seconds?: number;
  scroll?: boolean;
  // Not shown yet: the steps before it are still there. Its component is
  // watched for a press all the same.
  waits?: boolean;
}

const PRESETS = ["ring", "primary", "red", "orange", "yellow", "green", "blue", "pink"];
const STYLES = ["solid", "pulse", "trace"];
const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

// The list as the server sent it, with nothing in it that is no mark. What
// a mark's color and style are is checked here as well as on the server,
// since both end up in a stylesheet.
export function parseMarks(raw: unknown): Mark[] {
  if (!Array.isArray(raw)) return [];
  const out: Mark[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const m = item as Record<string, unknown>;
    if (typeof m.n !== "number" || typeof m.id !== "string") continue;
    const color = typeof m.color === "string" && (PRESETS.includes(m.color) || HEX.test(m.color)) ? m.color : "ring";
    const style = typeof m.style === "string" && STYLES.includes(m.style) ? (m.style as Mark["style"]) : "solid";
    const mark: Mark = { n: m.n, id: m.id, color, style };
    if (typeof m.field === "string") mark.field = m.field;
    if (typeof m.step === "number") mark.step = m.step;
    if (typeof m.label === "string" && m.label) mark.label = m.label;
    if (typeof m.seconds === "number" && m.seconds > 0) mark.seconds = m.seconds;
    if (m.scroll === true) mark.scroll = true;
    if (m.waits === true) mark.waits = true;
    out.push(mark);
  }
  return out;
}

// A mark's color as CSS: a preset is a color of the theme, by a variable
// an app's stylesheet can set, and a hex code is itself.
export function markColor(color: string): string {
  return HEX.test(color) ? color : `var(--mw-mark-${PRESETS.includes(color) ? color : "ring"})`;
}

// What stands on a mark's badge: its step, or its label.
export function markBadge(mark: Mark): string | null {
  if (mark.step !== undefined) return String(mark.step);
  return mark.label ?? null;
}

// Black or white, whichever reads on a color given as red, green and blue.
export function inkOn(r: number, g: number, b: number): "#000" | "#fff" {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  // White on anything but a light color. By contrast alone black would win
  // on a mid blue or orange, where white is what reads on a small badge.
  return luminance > 0.36 ? "#000" : "#fff";
}

let list: Mark[] = [];
const listeners = new Set<() => void>();

function tell() {
  for (const l of listeners) l();
}

export const marks = {
  get: (): Mark[] => list,
  set(next: Mark[]) {
    if (next.length === 0 && list.length === 0) return;
    list = next;
    tell();
  },
  subscribe(l: () => void): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

export function useMarks(): Mark[] {
  return useSyncExternalStore(marks.subscribe, marks.get);
}
