// A cell that is typed over: the text its field starts with, and what the
// text typed into it comes to. A number is typed the way the theme's
// locale writes one, 1,5 where the comma is the decimal mark, and a
// percent as the number shown, 25 for the 0.25 the row holds.

const NUMBERS = new Set(["number", "integer", "percent", "currency"]);

export function isNumber(format: string): boolean {
  return NUMBERS.has(format);
}

function marks(locale: string): { decimal: string; group: string } {
  const parts = new Intl.NumberFormat(locale, { numberingSystem: "latn" }).formatToParts(12345.6);
  return {
    decimal: parts.find((p) => p.type === "decimal")?.value ?? ".",
    group: parts.find((p) => p.type === "group")?.value ?? "",
  };
}

// What the field holds when it opens: the value as it would be typed, a
// number without the marks between its thousands or a sign of its money.
export function fieldText(value: unknown, format: string, locale: string): string {
  if (value === null || value === undefined) return "";
  if (!isNumber(format) || typeof value !== "number" || !Number.isFinite(value)) return String(value);
  // A fraction times a hundred is taken back to the digits it was typed
  // with: 0.07 is 7 and not 7.000000000000001.
  const shown = format === "percent" ? Number((value * 100).toPrecision(12)) : value;
  // In the digits a keyboard types and with the minus on its keys, which
  // is what `typed` reads: some locales write another minus, and some
  // other digits.
  const written = new Intl.NumberFormat(locale, { useGrouping: false, maximumFractionDigits: 20, numberingSystem: "latn" }).format(shown);
  return written.replace(MARKS, "").replace(/[\u2212\u2013]/g, "-");
}

// The marks a locale that reads from right to left puts beside a number,
// which say which way it runs and are no part of it.
const MARKS = /[\u200e\u200f\u061c]/g;

export type Typed = { ok: true; value: unknown } | { ok: false };

// What a text typed into a cell comes to in the column's format. A text is
// itself, its ends trimmed. A number that is emptied is nothing, and one
// that is no number, or no whole one in a column of them, is refused.
export function typed(text: string, format: string, locale: string): Typed {
  const said = text.trim();
  if (!isNumber(format)) return { ok: true, value: said };
  if (said === "") return { ok: true, value: null };
  const { decimal, group } = marks(locale);
  // The marks between thousands are spaces in some locales, of more than
  // one kind, and a person types the plain one. Such a mark stands before
  // three digits and nowhere else: 1.5 where the point is that mark is not
  // taken for 15, which is not what was meant by it.
  const spaced = group !== "" && group.trim() === "";
  // The minus a locale writes and the one on the keys are one, and so are
  // the two apostrophes where an apostrophe is the mark.
  let digits = said.replace(MARKS, "").replace(/%$/, "").trim().replace(/[\u2212\u2013]/g, "-");
  if (group === "'" || group === "\u2019") digits = digits.replace(/['\u2019]/g, group);
  if (spaced) digits = digits.replace(/[\s\u00a0\u202f]/g, " ");
  else if (/\s/.test(digits)) return { ok: false };
  const mark = spaced ? " " : group;
  if (mark) {
    const [whole, ...rest] = digits.split(decimal);
    const parts = whole.split(mark);
    if (parts.length > 1 && !(/^[+-]?\d{1,3}$/.test(parts[0]) && parts.slice(1).every((p) => /^\d{3}$/.test(p)))) return { ok: false };
    digits = [parts.join(""), ...rest].join(decimal);
  }
  if (decimal !== ".") {
    if (digits.includes(".")) return { ok: false };
    digits = digits.replace(decimal, ".");
  }
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(digits)) return { ok: false };
  const n = Number(digits);
  if (!Number.isFinite(n)) return { ok: false };
  if (format === "integer" && !Number.isInteger(n)) return { ok: false };
  return { ok: true, value: format === "percent" ? Number((n / 100).toPrecision(12)) : n };
}

// Whether what was typed is what the cell already holds, so nothing is said.
export function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  const empty = (v: unknown) => v === null || v === undefined || v === "";
  return empty(a) && empty(b);
}

// The cell a key goes to from one cell, among the columns that are typed
// over and the rows of the page. `next` and `prev` are Tab and Shift+Tab,
// which go on to the row after or before at the end of a row. Nothing
// when there is no such cell.
export type Way = "left" | "right" | "up" | "down" | "next" | "prev";
export function neighbor(rows: number, columns: number, row: number, column: number, way: Way): [number, number] | null {
  if (row < 0 || column < 0) return null;
  switch (way) {
    case "left":
      return column > 0 ? [row, column - 1] : null;
    case "right":
      return column < columns - 1 ? [row, column + 1] : null;
    case "up":
      return row > 0 ? [row - 1, column] : null;
    case "down":
      return row < rows - 1 ? [row + 1, column] : null;
    case "next":
      return column < columns - 1 ? [row, column + 1] : row < rows - 1 ? [row + 1, 0] : null;
    case "prev":
      return column > 0 ? [row, column - 1] : row > 0 ? [row - 1, columns - 1] : null;
  }
}
