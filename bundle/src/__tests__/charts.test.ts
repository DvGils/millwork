import { describe, expect, it } from "vitest";
import {
  divergingBars,
  divergingColors,
  divergingRows,
  niceTicks,
  rekey,
  seriesColors,
  slot,
  valueAxis,
  valueExtent,
} from "../charts-data";

const series = [
  { key: "sales", label: "Sales" },
  { key: "costs", label: "Costs" },
];

describe("rekey", () => {
  it("moves series into slots and turns non-numbers into gaps", () => {
    const rows = rekey([{ x: "Jan", sales: 3, costs: "7" }, { x: "Feb", sales: null, costs: 2 }], series);
    expect(rows).toEqual([
      { x: "Jan", s0: 3, s1: null },
      { x: "Feb", s0: null, s1: 2 },
    ]);
    expect(slot(4)).toBe("s4");
  });
});

describe("colours", () => {
  it("assigns tokens by position and dims the rest under emphasis", () => {
    const three = [{}, {}, {}];
    expect(seriesColors(three, null)).toEqual(["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"]);
    expect(seriesColors([{ color: 4 }, {}], null)).toEqual(["var(--chart-4)", "var(--chart-2)"]);
    const c = seriesColors(three, 1);
    expect(c[1]).toBe("var(--chart-2)");
    expect(c[0]).toBe(c[2]);
    expect(c[0]).toContain("muted-foreground");
  });

  it("fades a diverging scale into grey at the middle", () => {
    const five = divergingColors(5);
    expect(five[2]).toContain("muted-foreground");
    expect(five[0]).toContain("--chart-2) 100%");
    expect(five[1]).toContain("--chart-2) 70%");
    expect(five[3]).toContain("--chart-1) 70%");
    expect(five[4]).toContain("--chart-1) 100%");
    const two = divergingColors(2);
    expect(two[0]).toContain("--chart-2) 100%");
    expect(two[1]).toContain("--chart-1) 100%");
  });
});

describe("diverging", () => {
  it("splits an odd scale around its middle series", () => {
    const rows = divergingRows([{ x: "Q1", s0: 10, s1: 20, s2: 30 }], 3);
    expect(rows[0]).toMatchObject({ s0: 10, s1: 20, s2: 30, n0: -10, n1: -10, p1: 10, p2: 30 });
    expect(divergingBars(3)).toEqual([
      { index: 1, dataKey: "n1" },
      { index: 0, dataKey: "n0" },
      { index: 1, dataKey: "p1" },
      { index: 2, dataKey: "p2" },
    ]);
  });

  it("puts an even scale on two sides, nearest the middle first", () => {
    const rows = divergingRows([{ x: "Q1", s0: 1, s1: 2, s2: 3, s3: null }], 4);
    expect(rows[0]).toMatchObject({ n0: -1, n1: -2, p2: 3, p3: null });
    expect(divergingBars(4).map((b) => b.dataKey)).toEqual(["n1", "n0", "p2", "p3"]);
  });
});

describe("the value axis", () => {
  it("puts ticks at round steps, not at an even split of the data", () => {
    expect(niceTicks(0, 0.39)).toEqual([0, 0.1, 0.2, 0.3, 0.4]);
    expect(niceTicks(0, 39)).toEqual([0, 10, 20, 30, 40]);
    expect(niceTicks(0, 7)).toEqual([0, 2, 4, 6, 8]);
    expect(niceTicks(-12, 30)).toEqual([-20, -10, 0, 10, 20, 30]);
    expect(niceTicks(0.95, 1.05)).toEqual([0.94, 0.96, 0.98, 1, 1.02, 1.04, 1.06]);
    expect(niceTicks(5, 5)).toEqual([4.4, 4.6, 4.8, 5, 5.2, 5.4, 5.6]);
  });

  it("steps by whole numbers where the labels are whole", () => {
    // Three bars of one vote each: an axis of 0 and 1, not 0, 0, 0, 1, 1, 1.
    expect(niceTicks(0, 1, 5, true)).toEqual([0, 1]);
    expect(niceTicks(0, 2, 5, true)).toEqual([0, 1, 2]);
    expect(niceTicks(0, 3, 5, true)).toEqual([0, 1, 2, 3]);
    expect(niceTicks(1, 1, 5, true)).toEqual([0, 1, 2]);
    expect(niceTicks(0, 0.4, 5, true)).toEqual([0, 1]);
    // Where the steps are whole anyway, nothing changes.
    expect(niceTicks(0, 39, 5, true)).toEqual(niceTicks(0, 39));
    expect(niceTicks(0, 7, 5, true)).toEqual(niceTicks(0, 7));
    expect(valueAxis([1, 1], null, true, true)).toEqual({ domain: [0, 1], ticks: [0, 1] });
    expect(valueAxis([1, 1], null, true).ticks.length).toBeGreaterThan(2);
  });

  it("reads the data's reach, stacked or not", () => {
    const rows = [
      { x: "a", s0: 3, s1: -1 },
      { x: "b", s0: 5, s1: null },
    ];
    expect(valueExtent(rows, 2, false)).toEqual([-1, 5]);
    expect(valueExtent(rows, 2, true)).toEqual([-1, 5]);
    expect(valueExtent([], 2, false)).toBeNull();
  });

  it("keeps a bar chart on a zero baseline and lets a line sit where its data is", () => {
    expect(valueAxis([0.98, 1.04], null, true).domain).toEqual([0, 1.2]);
    expect(valueAxis([0.98, 1.04], null, false).domain).toEqual([0.98, 1.04]);
    expect(valueAxis([0.98, 1.04], null, false).ticks).toEqual([0.98, 1, 1.02, 1.04]);
  });

  it("holds the range the app gave, rounding only the end it left open", () => {
    const fixed = valueAxis([0.3, 0.9], [0, 1], false);
    expect(fixed.domain).toEqual([0, 1]);
    expect(fixed.ticks).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
    const half = valueAxis([0.3, 0.93], [0, null], false);
    expect(half.domain).toEqual([0, 1]);
  });

  it("still runs from low to high when the data misses the end the app fixed", () => {
    expect(valueAxis([0.5, 0.6], [0.9, null], false).domain).toEqual([0.9, 1]);
    expect(valueAxis([5, 6], [null, 1], false).domain).toEqual([0.9, 1]);
    expect(valueAxis(null, [100, null], false).domain).toEqual([100, 110]);
    expect(valueAxis([-50, -10], null, true).domain).toEqual([-50, 0]);
    expect(valueAxis([-50, -10], null, false).domain).toEqual([-50, -10]);
  });
});
