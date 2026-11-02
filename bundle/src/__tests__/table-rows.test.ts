import { describe, expect, it } from "vitest";
import { emptyFilter, equalsFilter, includesFilter, rangeFilter, sortRows } from "../table-rows";

describe("sorting rows", () => {
  const rows = [
    { n: 10, s: "b", v: null },
    { n: 2, s: "a10", v: "x" },
    { n: 2, s: "a9", v: "" },
    { n: null, s: "B", v: "y" },
  ];
  it("compares numbers by value, text with numeric runs in order, and keeps empties last", () => {
    expect(sortRows(rows, [{ id: "n", desc: false }]).map((r) => r.n)).toEqual([2, 2, 10, null]);
    expect(sortRows(rows, [{ id: "n", desc: true }]).map((r) => r.n)).toEqual([10, 2, 2, null]);
    expect(sortRows(rows, [{ id: "s", desc: false }]).map((r) => r.s)).toEqual(["a9", "a10", "b", "B"]);
    expect(sortRows(rows, [{ id: "v", desc: false }]).map((r) => r.v)).toEqual(["x", "y", null, ""]);
  });
  it("is stable and takes a second key", () => {
    expect(sortRows(rows, [{ id: "n", desc: false }]).map((r) => r.s)).toEqual(["a10", "a9", "b", "B"]);
    expect(sortRows(rows, [{ id: "n", desc: false }, { id: "s", desc: true }]).map((r) => r.s)).toEqual(["a10", "a9", "b", "B"]);
    expect(sortRows(rows, [{ id: "n", desc: false }, { id: "s", desc: false }]).map((r) => r.s)).toEqual(["a9", "a10", "b", "B"]);
    expect(sortRows(rows, [])).toBe(rows);
  });
});

describe("filters", () => {
  it("match text without case, numbers within a range, and choices exactly", () => {
    expect(includesFilter("Hello World", "lo w")).toBe(true);
    expect(includesFilter(42, "4")).toBe(true);
    expect(includesFilter(null, "a")).toBe(false);
    expect(includesFilter(null, "")).toBe(true);
    expect(rangeFilter(5, [1, 10])).toBe(true);
    expect(rangeFilter(5, [6, null])).toBe(false);
    expect(rangeFilter("", [1, 10])).toBe(false);
    expect(rangeFilter("abc", [null, 10])).toBe(false);
    expect(rangeFilter(null, [null, null])).toBe(true);
    expect(equalsFilter(true, "true")).toBe(true);
    expect(equalsFilter("a", "b")).toBe(false);
    expect(equalsFilter(null, "")).toBe(true);
  });
  it("knows an empty filter when it sees one", () => {
    expect(emptyFilter("")).toBe(true);
    expect(emptyFilter([null, ""])).toBe(true);
    expect(emptyFilter([null, 3])).toBe(false);
    expect(emptyFilter("x")).toBe(false);
  });
});
