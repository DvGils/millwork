import { describe, expect, it } from "vitest";
import { fieldText, neighbor, same, typed } from "../cell-edit";

describe("what a cell's field starts with", () => {
  it("is the value as it would be typed", () => {
    expect(fieldText("Ada", "text", "en-US")).toBe("Ada");
    expect(fieldText(null, "number", "en-US")).toBe("");
    expect(fieldText(1234.5, "number", "en-US")).toBe("1234.5");
    expect(fieldText(1234.5, "currency", "nl-NL")).toBe("1234,5");
    expect(fieldText(12, "integer", "de-DE")).toBe("12");
  });

  it("is the percent that is shown, with the digits it was typed with", () => {
    expect(fieldText(0.25, "percent", "en-US")).toBe("25");
    expect(fieldText(0.07, "percent", "en-US")).toBe("7");
    expect(fieldText(0.125, "percent", "nl-NL")).toBe("12,5");
  });
});

describe("what was typed into a cell", () => {
  it("is a text with its ends trimmed", () => {
    expect(typed("  Ada  ", "text", "en-US")).toEqual({ ok: true, value: "Ada" });
    expect(typed("", "text", "en-US")).toEqual({ ok: true, value: "" });
    expect(typed("12", "text", "en-US")).toEqual({ ok: true, value: "12" });
  });

  it("is a number as the locale writes one", () => {
    expect(typed("1234.5", "number", "en-US")).toEqual({ ok: true, value: 1234.5 });
    expect(typed("1,234.5", "number", "en-US")).toEqual({ ok: true, value: 1234.5 });
    expect(typed("1234,5", "number", "nl-NL")).toEqual({ ok: true, value: 1234.5 });
    expect(typed("1.234,5", "currency", "nl-NL")).toEqual({ ok: true, value: 1234.5 });
    expect(typed("-3", "number", "en-US")).toEqual({ ok: true, value: -3 });
    expect(typed(".5", "number", "en-US")).toEqual({ ok: true, value: 0.5 });
    expect(typed("1 234,5", "number", "fr-FR")).toEqual({ ok: true, value: 1234.5 });
  });

  it("is nothing when a number is emptied", () => {
    expect(typed("  ", "number", "en-US")).toEqual({ ok: true, value: null });
  });

  it("is refused when it is no number, or a point where the comma is the mark", () => {
    expect(typed("twelve", "number", "en-US")).toEqual({ ok: false });
    expect(typed("1.2.3", "number", "en-US")).toEqual({ ok: false });
    expect(typed("12abc", "number", "en-US")).toEqual({ ok: false });
    expect(typed("-", "number", "en-US")).toEqual({ ok: false });
    expect(typed("Infinity", "number", "en-US")).toEqual({ ok: false });
    expect(typed("1e5", "number", "en-US")).toEqual({ ok: false });
    // A point where the point stands between thousands, and not before three digits.
    expect(typed("1.5", "number", "nl-NL")).toEqual({ ok: false });
    expect(typed("1.234", "number", "nl-NL")).toEqual({ ok: true, value: 1234 });
    expect(typed("1,5", "number", "en-US")).toEqual({ ok: false });
    expect(typed("12,34,567", "number", "en-US")).toEqual({ ok: false });
  });

  it("is a whole number in a column of them", () => {
    expect(typed("12", "integer", "en-US")).toEqual({ ok: true, value: 12 });
    expect(typed("12.5", "integer", "en-US")).toEqual({ ok: false });
    expect(typed("12.0", "integer", "en-US")).toEqual({ ok: true, value: 12 });
  });

  it("is the fraction a percent stands for", () => {
    expect(typed("25", "percent", "en-US")).toEqual({ ok: true, value: 0.25 });
    expect(typed("7", "percent", "en-US")).toEqual({ ok: true, value: 0.07 });
    expect(typed("12,5%", "percent", "nl-NL")).toEqual({ ok: true, value: 0.125 });
  });
});

describe("a number as its field shows it", () => {
  it("is read back as the number it was, in any locale", () => {
    const locales = ["en-US", "nl-NL", "de-DE", "de-CH", "fr-FR", "sv-SE", "fi-FI", "nb-NO", "en-IN", "ar-EG", "hi-IN", "fa-IR", "he-IL"];
    for (const locale of locales) {
      for (const value of [0, 7, -5, 1234.5, -1234567.25, 0.001]) {
        expect([locale, value, typed(fieldText(value, "number", locale), "number", locale)]).toEqual([locale, value, { ok: true, value }]);
      }
      for (const value of [0.25, -0.07, 1.5]) {
        expect([locale, value, typed(fieldText(value, "percent", locale), "percent", locale)]).toEqual([locale, value, { ok: true, value }]);
      }
    }
  });

  it("takes the minus and the apostrophe a locale writes as well as the ones on the keys", () => {
    expect(typed("\u22125", "number", "en-US")).toEqual({ ok: true, value: -5 });
    expect(typed("1\u2019234.5", "number", "de-CH")).toEqual({ ok: true, value: 1234.5 });
    expect(typed("1'234.5", "number", "de-CH")).toEqual({ ok: true, value: 1234.5 });
  });

  it("is not two numbers with a space between them", () => {
    expect(typed("1 5", "number", "en-US")).toEqual({ ok: false });
    expect(typed(" 15 ", "number", "en-US")).toEqual({ ok: true, value: 15 });
  });
});

describe("what a cell already holds", () => {
  it("is not said again", () => {
    expect(same("a", "a")).toBe(true);
    expect(same(null, "")).toBe(true);
    expect(same(undefined, null)).toBe(true);
    expect(same(0, null)).toBe(false);
    expect(same("a", "b")).toBe(false);
    expect(same(false, null)).toBe(false);
  });
});

describe("the cell a key goes to", () => {
  it("is beside or over or under, and nothing past an edge", () => {
    expect(neighbor(3, 2, 1, 0, "right")).toEqual([1, 1]);
    expect(neighbor(3, 2, 1, 1, "right")).toBeNull();
    expect(neighbor(3, 2, 1, 1, "left")).toEqual([1, 0]);
    expect(neighbor(3, 2, 0, 1, "up")).toBeNull();
    expect(neighbor(3, 2, 2, 1, "down")).toBeNull();
    expect(neighbor(3, 2, 1, 1, "down")).toEqual([2, 1]);
  });

  it("goes on to the next row with Tab and back with Shift and Tab", () => {
    expect(neighbor(3, 2, 0, 0, "next")).toEqual([0, 1]);
    expect(neighbor(3, 2, 0, 1, "next")).toEqual([1, 0]);
    expect(neighbor(3, 2, 2, 1, "next")).toBeNull();
    expect(neighbor(3, 2, 1, 0, "prev")).toEqual([0, 1]);
    expect(neighbor(3, 2, 0, 0, "prev")).toBeNull();
    expect(neighbor(3, 2, -1, 0, "next")).toBeNull();
  });
});
