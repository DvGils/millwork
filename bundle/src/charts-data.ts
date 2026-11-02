// The data side of a chart, kept out of React so it can be tested: rows are
// re-keyed to numbered slots (safe as data keys and CSS variable names), series
// get their colours by position, and a diverging chart is split around its
// midpoint.

export interface Series {
  key: string;
  label: string;
}

export type Row = Record<string, unknown>;

export function slot(i: number): string {
  return `s${i}`;
}

// `x` stays; series i lands in slot i. Values that are not numbers become gaps.
export function rekey(rows: Row[], series: Series[]): Row[] {
  return rows.map((row) => {
    const out: Row = { x: row.x };
    series.forEach((s, i) => {
      const v = row[s.key];
      out[slot(i)] = typeof v === "number" && Number.isFinite(v) ? v : null;
    });
    return out;
  });
}

// A series that is not the emphasised one recedes into a grey off the surface.
const DIM = "color-mix(in oklab, var(--muted-foreground) 40%, var(--background))";
export const NEUTRAL = "color-mix(in oklab, var(--muted-foreground) 55%, var(--background))";

export function seriesColors(n: number, emphasis: number | null): string[] {
  return Array.from({ length: n }, (_, i) =>
    emphasis === null || emphasis === i ? `var(--chart-${i + 1})` : DIM,
  );
}

// An ordered scale: one hue to the left of the midpoint, another to the right,
// each fading towards grey as it nears the middle; a middle series is grey.
export function divergingColors(n: number): string[] {
  const mid = (n - 1) / 2;
  return Array.from({ length: n }, (_, i) => {
    const distance = Math.abs(i - mid);
    if (distance === 0) return NEUTRAL;
    const hue = i < mid ? "--chart-2" : "--chart-1";
    const strength = mid === 0 ? 1 : distance / mid;
    return `color-mix(in oklab, var(${hue}) ${Math.round(40 + 60 * strength)}%, var(--background))`;
  });
}

export interface DivergingBar {
  index: number;
  dataKey: string;
}

// Left of the midpoint goes negative under `n<i>`, right stays positive under
// `p<i>`, and a middle series is split half and half. The slots stay as they
// are so a tooltip can read the real values.
export function divergingRows(rows: Row[], n: number): Row[] {
  const mid = (n - 1) / 2;
  return rows.map((row) => {
    const out: Row = { ...row };
    for (let i = 0; i < n; i++) {
      const v = row[slot(i)];
      const value = typeof v === "number" ? v : null;
      if (i < mid) out[`n${i}`] = value === null ? null : -value;
      else if (i > mid) out[`p${i}`] = value;
      else {
        out[`n${i}`] = value === null ? null : -value / 2;
        out[`p${i}`] = value === null ? null : value / 2;
      }
    }
    return out;
  });
}

// Bars in drawing order: each side starts at the midpoint and works outward,
// so the strongest step of the scale sits farthest from zero.
export function divergingBars(n: number): DivergingBar[] {
  const mid = (n - 1) / 2;
  const bars: DivergingBar[] = [];
  if (Number.isInteger(mid)) bars.push({ index: mid, dataKey: `n${mid}` });
  for (let i = Math.ceil(mid) - 1; i >= 0; i--) bars.push({ index: i, dataKey: `n${i}` });
  if (Number.isInteger(mid)) bars.push({ index: mid, dataKey: `p${mid}` });
  for (let i = Math.floor(mid) + 1; i < n; i++) bars.push({ index: i, dataKey: `p${i}` });
  return bars;
}
