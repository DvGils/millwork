// The data side of a chart, kept out of React so it can be tested: rows are
// re-keyed to numbered slots (safe as data keys and CSS variable names), series
// get their colours by position, and a diverging chart is split around its
// midpoint.

export interface Series {
  key: string;
  label: string;
  color?: number; // the theme's chart slot, 1 to 5; position when absent
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

// The value axis: where the data reaches, and ticks at round steps.
export function valueExtent(rows: Row[], n: number, stacked: boolean): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const row of rows) {
    let up = 0;
    let down = 0;
    for (let i = 0; i < n; i++) {
      const v = row[slot(i)];
      if (typeof v !== "number") continue;
      if (stacked) {
        if (v >= 0) up += v;
        else down += v;
      } else {
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    if (stacked) {
      lo = Math.min(lo, down);
      hi = Math.max(hi, up);
    }
  }
  return lo <= hi ? [lo, hi] : null;
}

// Ticks at a round step (1, 2 or 5 times a power of ten), about `count` of
// them, from the first at or below `lo` to the first at or above `hi`.
// Which reads 10, 20, 30 where an even split would read 13, 26, 39.
export function niceTicks(lo: number, hi: number, count = 5, whole = false): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi < lo) [lo, hi] = [hi, lo];
  if (hi === lo) {
    if (lo === 0) return [0, 1];
    const pad = Math.abs(lo) / 10;
    lo -= pad;
    hi += pad;
  }
  const rough = (hi - lo) / Math.max(1, count - 1);
  const power = 10 ** Math.floor(Math.log10(rough));
  const unit = rough / power;
  const round = (unit < 1.5 ? 1 : unit < 3 ? 2 : unit < 7 ? 5 : 10) * power;
  // Labels that show no decimals step by one at the least, or a few small
  // counts would read 0, 0, 0, 1, 1, 1 up the axis.
  const step = whole ? Math.max(1, round) : round;
  const first = Math.floor(lo / step + 1e-9) * step;
  const last = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = first; v <= last + step / 2; v += step) ticks.push(Number(v.toFixed(12)));
  return ticks;
}

// The axis a chart draws: the app's range where it gave one, the data's
// reach where it did not, a baseline at zero for bars, all at round ticks.
export function valueAxis(
  extent: [number, number] | null,
  range: [number | null, number | null] | null,
  fromZero: boolean,
  whole = false,
): { domain: [number, number]; ticks: number[] } {
  let [lo, hi] = extent ?? [0, 1];
  if (fromZero) {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  }
  const given = range ?? [null, null];
  const fixedLo = given[0] !== null;
  const fixedHi = given[1] !== null;
  if (fixedLo) lo = given[0] as number;
  if (fixedHi) hi = given[1] as number;
  // Data that falls outside the end the app fixed does not pull the open
  // end past it: the axis still runs from low to high.
  if (!fixedHi) hi = Math.max(hi, lo);
  if (!fixedLo) lo = Math.min(lo, hi);
  const ticks = niceTicks(lo, hi, 5, whole);
  // A bound the app set is kept as it is; one the data gave is rounded out.
  const domain: [number, number] = [
    fixedLo ? lo : Math.min(ticks[0] ?? lo, lo),
    fixedHi ? hi : Math.max(ticks[ticks.length - 1] ?? hi, hi),
  ];
  return { domain, ticks: ticks.filter((t) => t >= domain[0] - 1e-9 && t <= domain[1] + 1e-9) };
}

// A series that is not the emphasised one recedes into a grey off the surface.
const DIM = "color-mix(in oklab, var(--muted-foreground) 40%, var(--background))";
export const NEUTRAL = "color-mix(in oklab, var(--muted-foreground) 55%, var(--background))";

export function chartSlot(series: { color?: number }, i: number): string {
  return `var(--chart-${series.color ?? i + 1})`;
}

export function seriesColors(series: { color?: number }[], emphasis: number | null): string[] {
  return series.map((s, i) => (emphasis === null || emphasis === i ? chartSlot(s, i) : DIM));
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
