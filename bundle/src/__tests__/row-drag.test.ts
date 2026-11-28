import { describe, expect, it } from "vitest";
import { carry, shiftOf } from "../row-drag";

// Five rows of 30 pixels, the first at 100.
const rows = [0, 1, 2, 3, 4].map((i) => ({ top: 100 + i * 30, height: 30 }));

describe("a row carried among the rows of its list", () => {
  it("keeps its place until its edge has passed the middle of a neighbor", () => {
    expect(carry(rows, 2, 0)).toEqual({ by: 0, to: 2 });
    expect(carry(rows, 2, 14)).toEqual({ by: 14, to: 2 });
    expect(carry(rows, 2, 16)).toEqual({ by: 16, to: 3 });
    expect(carry(rows, 2, -14)).toEqual({ by: -14, to: 2 });
    expect(carry(rows, 2, -16)).toEqual({ by: -16, to: 1 });
  });

  it("means the furthest row it has passed", () => {
    expect(carry(rows, 0, 95)).toEqual({ by: 95, to: 3 });
    expect(carry(rows, 4, -95)).toEqual({ by: -95, to: 1 });
  });

  it("does not leave the list, and means its ends when held there", () => {
    expect(carry(rows, 1, 500)).toEqual({ by: 90, to: 4 });
    expect(carry(rows, 3, -500)).toEqual({ by: -90, to: 0 });
    expect(carry(rows.slice(0, 1), 0, 40)).toEqual({ by: 0, to: 0 });
  });

  it("takes rows of other heights as they are", () => {
    const mixed = [
      { top: 0, height: 20 },
      { top: 20, height: 80 },
      { top: 100, height: 20 },
    ];
    // The first row ends at 20, and the tall row's middle is at 60.
    expect(carry(mixed, 0, 39)).toEqual({ by: 39, to: 0 });
    expect(carry(mixed, 0, 41)).toEqual({ by: 41, to: 1 });
    // The tall row starts at 20, and the first row's middle is at 10.
    expect(carry(mixed, 1, -9)).toEqual({ by: -9, to: 1 });
    expect(carry(mixed, 1, -11)).toEqual({ by: -11, to: 0 });
  });
});

describe("the rows it has passed", () => {
  it("make room where it came from and where it is going", () => {
    // Held row 1 over place 3: rows 2 and 3 move up by its height.
    expect([0, 1, 2, 3, 4].map((i) => shiftOf(i, 1, 3, 30))).toEqual([0, 0, -30, -30, 0]);
    // Held row 3 over place 0: rows 0 to 2 move down.
    expect([0, 1, 2, 3, 4].map((i) => shiftOf(i, 3, 0, 30))).toEqual([30, 30, 30, 0, 0]);
    expect([0, 1, 2].map((i) => shiftOf(i, 1, 1, 30))).toEqual([0, 0, 0]);
  });
});
