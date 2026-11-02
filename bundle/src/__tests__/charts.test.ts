import { describe, expect, it } from "vitest";
import { divergingBars, divergingColors, divergingRows, rekey, seriesColors, slot } from "../charts-data";

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
