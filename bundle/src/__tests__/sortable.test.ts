import { describe, expect, it } from "vitest";
import { moved, slotAt } from "../sortable";

const row = (n: number, top = 0) => Array.from({ length: n }, (_, i) => ({ left: i * 50, top, width: 40, height: 20 }));

describe("slotAt", () => {
  it("counts the boxes left of the pointer in its row", () => {
    const boxes = row(3);
    expect(slotAt(boxes, 0, 10)).toBe(0);
    expect(slotAt(boxes, 45, 10)).toBe(1);
    expect(slotAt(boxes, 125, 10)).toBe(3);
  });
  it("counts every box in the rows above", () => {
    const boxes = [...row(3, 0), ...row(2, 30)];
    expect(slotAt(boxes, 0, 40)).toBe(3);
    expect(slotAt(boxes, 60, 40)).toBe(4);
    expect(slotAt(boxes, 10, -30)).toBe(0);
  });
});

describe("moved", () => {
  it("moves an item and leaves the rest in order", () => {
    expect(moved(["a", "b", "c", "d"], 0, 2)).toEqual(["b", "c", "a", "d"]);
    expect(moved(["a", "b", "c", "d"], 3, 0)).toEqual(["d", "a", "b", "c"]);
    expect(moved(["a", "b"], 1, 1)).toEqual(["a", "b"]);
  });
  it("clamps the target", () => {
    expect(moved(["a", "b", "c"], 0, 9)).toEqual(["b", "c", "a"]);
    expect(moved(["a", "b", "c"], 2, -1)).toEqual(["c", "a", "b"]);
  });
});
