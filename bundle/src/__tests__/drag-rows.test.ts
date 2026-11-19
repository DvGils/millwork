import { describe, expect, it } from "vitest";
import { EDGE, placeAt, scrollBy } from "../components/drag-rows";

describe("the place a held row would land", () => {
  // Three rows of 40, with 8 between them, and a held row of 40.
  const rows = [
    { top: 0, height: 40 },
    { top: 48, height: 40 },
    { top: 96, height: 40 },
  ];
  const at = (middle: number) => placeAt(rows, middle, 40, 8, null);

  it("is the slot whose gap is nearest to the middle of the held row", () => {
    // A gap at place 0 would be from 0 to 40, at place 1 from 48 to 88.
    expect(at(20)).toBe(0);
    expect(at(43)).toBe(0);
    expect(at(45)).toBe(1);
    expect(at(68)).toBe(1);
    expect(at(93)).toBe(2);
    expect(at(500)).toBe(3);
    expect(placeAt([], 10, 40, 8, null)).toBe(0);
  });

  it("is the same with the gap open as without it", () => {
    for (const gapAt of [0, 1, 2, 3]) {
      // The rows from the gap on show 48 lower.
      const open = rows.map((row, i) => ({ ...row, top: row.top + (i >= gapAt ? 48 : 0) }));
      for (const middle of [-10, 20, 43, 45, 68, 93, 120, 500]) {
        expect(placeAt(open, middle, 40, 8, gapAt)).toBe(at(middle));
      }
    }
  });

  it("goes by how high each row is", () => {
    // A tall row is passed when the held row's middle is past half of both.
    const tall = [{ top: 0, height: 200 }];
    expect(placeAt(tall, 119, 40, 0, null)).toBe(0);
    expect(placeAt(tall, 121, 40, 0, null)).toBe(1);
  });
});

describe("scrolling near an edge", () => {
  it("is nothing in the middle and more toward an edge", () => {
    expect(scrollBy(300, 0, 600)).toBe(0);
    expect(scrollBy(EDGE - 1, 0, 600)).toBeLessThan(0);
    expect(scrollBy(600 - EDGE + 1, 0, 600)).toBeGreaterThan(0);
    expect(Math.abs(scrollBy(2, 0, 600))).toBeGreaterThan(Math.abs(scrollBy(40, 0, 600)));
  });
});
