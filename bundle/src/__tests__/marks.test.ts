import { describe, expect, it } from "vitest";
import { inkOn, markBadge, markColor, parseMarks } from "../marks";
import { around, common } from "../pointing";
import { stillTold, TOLD_FOR } from "../marks-layer";

describe("parseMarks", () => {
  it("takes a mark as the server sends it", () => {
    const sent = [
      { n: 1, id: "root/new", color: "blue", style: "pulse", step: 1 },
      { n: 2, id: "root/dlg/order", field: "/amount", color: "#0a7d5c", style: "trace", step: 2, waits: true },
      { n: 3, id: "root/export", color: "ring", style: "solid", label: "Here", seconds: 10, scroll: true },
    ];
    expect(parseMarks(sent)).toEqual(sent);
  });

  it("leaves out what is no mark, and what is no color or style", () => {
    expect(parseMarks("nope")).toEqual([]);
    expect(parseMarks([null, 3, { id: "a" }, { n: "1", id: "a" }, { n: 1 }])).toEqual([]);
    expect(parseMarks([{ n: 1, id: "a", color: "red; background: url(x)", style: "glow", seconds: -1, label: "" }])).toEqual([
      { n: 1, id: "a", color: "ring", style: "solid" },
    ]);
    expect(parseMarks([{ n: 1, id: "a", color: "crimson", style: "solid", waits: "yes", scroll: 1 }])[0]).toEqual({
      n: 1,
      id: "a",
      color: "ring",
      style: "solid",
    });
  });
});

describe("markColor", () => {
  it("is a color of the theme for a name, and itself for a hex code", () => {
    expect(markColor("blue")).toBe("var(--mw-mark-blue)");
    expect(markColor("ring")).toBe("var(--mw-mark-ring)");
    expect(markColor("#0A7D5C")).toBe("#0A7D5C");
    expect(markColor("#abc")).toBe("#abc");
    expect(markColor("crimson")).toBe("var(--mw-mark-ring)");
    expect(markColor("#12")).toBe("var(--mw-mark-ring)");
  });
});

describe("markBadge", () => {
  it("is the step, or the label, or nothing", () => {
    expect(markBadge({ n: 1, id: "a", color: "ring", style: "solid", step: 2, label: "A" })).toBe("2");
    expect(markBadge({ n: 1, id: "a", color: "ring", style: "solid", label: "A" })).toBe("A");
    expect(markBadge({ n: 1, id: "a", color: "ring", style: "solid" })).toBeNull();
  });
});

describe("inkOn", () => {
  it("is the one of black and white that reads", () => {
    expect(inkOn(255, 255, 255)).toBe("#000");
    expect(inkOn(0, 0, 0)).toBe("#fff");
    expect(inkOn(237, 161, 0)).toBe("#000");
    expect(inkOn(42, 120, 214)).toBe("#fff");
    expect(inkOn(10, 125, 92)).toBe("#fff");
  });
});

describe("stillTold", () => {
  it("holds for as long as the session has to answer, and not after", () => {
    expect(stillTold(0, 5000)).toBe(false);
    expect(stillTold(1000, 1000)).toBe(true);
    expect(stillTold(1000, 1000 + TOLD_FOR - 1)).toBe(true);
    expect(stillTold(1000, 1000 + TOLD_FOR)).toBe(false);
  });
});

describe("around and common", () => {
  const box = (left: number, top: number, right: number, bottom: number) => ({ left, top, right, bottom });

  it("is the box around what takes room", () => {
    expect(around([])).toBeNull();
    expect(around([box(5, 5, 5, 9)])).toBeNull();
    expect(around([box(10, 20, 30, 40), box(0, 0, 0, 0), box(25, 10, 50, 30)])).toEqual(box(10, 10, 50, 40));
  });

  it("is what two boxes share, or nothing", () => {
    expect(common(box(0, 0, 10, 10), box(5, 5, 20, 20))).toEqual(box(5, 5, 10, 10));
    expect(common(box(0, 0, 10, 10), box(10, 0, 20, 10))).toBeNull();
    expect(common(box(0, 0, 10, 10), box(20, 20, 30, 30))).toBeNull();
  });
});
