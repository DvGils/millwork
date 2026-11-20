import { describe, expect, it } from "vitest";
import { parseHex, placed, toHex, toHsv } from "../color";

describe("a hex code as it is typed", () => {
  it("is six digits, with or without the sign and in either case", () => {
    expect(parseHex("#3B82F6")).toBe("#3b82f6");
    expect(parseHex(" 3b82f6 ")).toBe("#3b82f6");
    expect(parseHex("#3b82f")).toBeNull();
    expect(parseHex("#3b82f6a")).toBeNull();
    expect(parseHex("#gggggg")).toBeNull();
    expect(parseHex("")).toBeNull();
  });

  it("is three digits only where those are taken", () => {
    expect(parseHex("#abc")).toBeNull();
    expect(parseHex("#abc", true)).toBe("#aabbcc");
    expect(parseHex("F00", true)).toBe("#ff0000");
  });
});

describe("a color between its code and its place in the picker", () => {
  it("comes back as the code it was", () => {
    for (const hex of ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff", "#3b82f6", "#ec4899", "#808080", "#010203"]) {
      expect(toHex(toHsv(hex))).toBe(hex);
    }
  });

  it("is where the square and the strip show it", () => {
    expect(toHsv("#ff0000")).toEqual({ h: 0, s: 1, v: 1 });
    expect(toHsv("#00ff00")).toEqual({ h: 120, s: 1, v: 1 });
    expect(toHsv("#0000ff")).toEqual({ h: 240, s: 1, v: 1 });
    expect(toHex({ h: 300, s: 1, v: 1 })).toBe("#ff00ff");
    expect(toHex({ h: 359.9, s: 1, v: 1 })).toBe("#ff0000");
    expect(toHex({ h: 210, s: 0, v: 0.5 })).toBe("#808080");
  });

  it("keeps the hue of a gray and the saturation of black from where it was", () => {
    const was = { h: 210, s: 0.6, v: 0.9 };
    expect(toHsv("#808080", was)).toEqual({ h: 210, s: 0, v: 128 / 255 });
    expect(toHsv("#000000", was)).toEqual({ h: 210, s: 0.6, v: 0 });
    expect(toHsv("#808080")).toEqual({ h: 0, s: 0, v: 128 / 255 });
  });
});

describe("where the picker is for the color the page has", () => {
  it("stays where it was left when that is the page's color", () => {
    // Black is every place along the bottom of the square.
    const left = { h: 210, s: 0.4, v: 0 };
    expect(placed("#000000", left)).toBe(left);
    expect(placed(null, left)).toBe(left);
  });

  it("goes to another color the page gives", () => {
    const next = placed("#ff0000", { h: 210, s: 0.4, v: 0.5 });
    expect(next).toEqual({ h: 0, s: 1, v: 1 });
  });
});
