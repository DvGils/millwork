// A long table draws the rows in view and a margin around them. The rest stand
// in as two spacers, so the scrollbar is as long as the whole table while the
// page holds a few hundred cells instead of a hundred thousand.

import { type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

// Up to this many rows are simply all drawn.
export const WINDOW_MIN = 200;
// Rows kept drawn past each edge of the view, and the step the window moves
// in, so a scroll redraws now and then instead of on every pixel.
const MARGIN = 30;
const STEP = 20;
// Passes of measuring and choosing again that may follow one another within a
// frame. Two settle a table; past this the next frame carries on.
const PASSES = 6;

export interface RowWindow {
  windowed: boolean;
  first: number;
  last: number;
  // The heights standing in for the rows before and after the window.
  before: number;
  after: number;
}

// The part of the window the rows can show in: the browser's own, cut down by
// every ancestor that scrolls or clips.
function viewOf(el: HTMLElement): { top: number; bottom: number } {
  let top = 0;
  let bottom = window.innerHeight;
  for (let a = el.parentElement; a; a = a.parentElement) {
    const overflow = getComputedStyle(a).overflowY;
    if (overflow === "visible") continue;
    const r = a.getBoundingClientRect();
    top = Math.max(top, r.top);
    bottom = Math.min(bottom, r.bottom);
  }
  return { top, bottom };
}

// The first place whose top is past `y`, less one: the row `y` falls in.
function rowAt(tops: Float64Array, count: number, y: number): number {
  let low = 0;
  let high = count;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (tops[mid + 1] <= y) low = mid + 1;
    else high = mid;
  }
  return low;
}

// `ids` names the rows in the order they are shown. A row's height is kept
// under its name once it has been drawn and measured, and a row not yet drawn
// counts as the average of those that have. Where each row starts is the sum
// of the heights before it, so which rows are in view follows from heights
// that drawing other rows does not change. Rows of different heights, a
// column that wraps, are then as steady as rows of one.
export function useRowWindow(body: RefObject<HTMLTableSectionElement | null>, ids: string[]): RowWindow {
  const count = ids.length;
  const windowed = count > WINDOW_MIN;
  const [range, setRange] = useState<{ first: number; last: number; before: number; after: number }>({
    first: 0,
    last: 3 * MARGIN,
    before: 0,
    after: 0,
  });
  const held = useRef({
    heights: new Map<string, number>(),
    sum: 0,
    width: 0,
    tops: new Float64Array(1),
    // What `tops` was built from: it is built again when either changes.
    ids: null as string[] | null,
    stale: true,
    passes: 0,
    frame: 0,
  });
  const drawn = useRef({ first: 0, last: 0 });
  drawn.current = { first: Math.min(range.first, count), last: Math.min(Math.max(range.last, range.first), count) };

  const look = useCallback(() => {
    const el = body.current;
    const h = held.current;
    if (!el || !windowed) return;
    // Heights measured at another width are another table's.
    const width = el.getBoundingClientRect().width;
    if (Math.abs(width - h.width) > 1) {
      h.heights.clear();
      h.sum = 0;
      h.width = width;
      h.stale = true;
    }
    if (h.heights.size > 4 * count + 1000) {
      h.heights.clear();
      h.sum = 0;
      h.stale = true;
    }
    const rows = el.querySelectorAll(":scope > tr[data-slot=table-row]");
    const { first: from, last: to } = drawn.current;
    if (rows.length === to - from) {
      for (let i = 0; i < rows.length; i++) {
        const height = rows[i].getBoundingClientRect().height;
        if (height <= 0) continue;
        const id = ids[from + i];
        const was = h.heights.get(id);
        if (was !== undefined && Math.abs(was - height) < 0.5) continue;
        h.sum += height - (was ?? 0);
        h.heights.set(id, height);
        h.stale = true;
      }
    }
    if (h.stale || h.ids !== ids) {
      const usual = h.heights.size ? h.sum / h.heights.size : 37;
      const tops = h.tops.length === count + 1 ? h.tops : new Float64Array(count + 1);
      let at = 0;
      for (let i = 0; i < count; i++) {
        tops[i] = at;
        at += h.heights.get(ids[i]) ?? usual;
      }
      tops[count] = at;
      h.tops = tops;
      h.ids = ids;
      h.stale = false;
    }
    const tops = h.tops;
    const view = viewOf(el);
    const top = el.getBoundingClientRect().top;
    const from_ = rowAt(tops, count, view.top - top);
    const to_ = rowAt(tops, count, view.bottom - top) + 1;
    const first = Math.min(count, Math.max(0, Math.floor((from_ - MARGIN) / STEP) * STEP));
    const last = Math.max(first, Math.min(count, Math.ceil((to_ + MARGIN) / STEP) * STEP));
    const before = tops[first];
    const after = tops[count] - tops[last];
    setRange((old) =>
      old.first === first && old.last === last && Math.abs(old.before - before) < 0.5 && Math.abs(old.after - after) < 0.5
        ? old
        : { first, last, before, after },
    );
  }, [body, ids, count, windowed]);

  const soon = useCallback(() => {
    const h = held.current;
    if (h.frame) return;
    h.frame = requestAnimationFrame(() => {
      h.frame = 0;
      h.passes = 0;
      look();
    });
  }, [look]);

  // After every draw: the rows just drawn are measured, and a table that
  // grew, shrank or was sorted may show another stretch of itself. Measuring
  // can move the window once or twice, never round in a circle, since a row's
  // height does not depend on which rows are drawn. The count is a backstop.
  useLayoutEffect(() => {
    const h = held.current;
    if (h.passes < PASSES) {
      h.passes += 1;
      look();
    } else soon();
  });

  useEffect(() => {
    if (!windowed) return;
    const h = held.current;
    // Scrolling does not bubble, so every scroller on the page is heard in the
    // capture phase: the table's own box, a dialog's body, the page.
    window.addEventListener("scroll", soon, { capture: true, passive: true });
    window.addEventListener("resize", soon);
    // A table that was hidden and is shown, or whose box changed, says so here.
    const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(soon);
    if (watch && body.current) watch.observe(body.current);
    return () => {
      window.removeEventListener("scroll", soon, { capture: true });
      window.removeEventListener("resize", soon);
      watch?.disconnect();
      if (h.frame) cancelAnimationFrame(h.frame);
      h.frame = 0;
    };
  }, [body, soon, windowed]);

  if (!windowed) return { windowed, first: 0, last: count, before: 0, after: 0 };
  const { first, last } = drawn.current;
  // A list that changed since the window was chosen is drawn with what its
  // rows are known to be; the pass after this draw puts it right.
  const sure = held.current.ids === ids && first === range.first && last === range.last;
  const usual = held.current.heights.size ? held.current.sum / held.current.heights.size : 37;
  return {
    windowed,
    first,
    last,
    before: sure ? range.before : first * usual,
    after: sure ? range.after : (count - last) * usual,
  };
}

// With only some rows drawn, a column would be as wide as the rows in view and
// change as they scroll. Each column that does not wrap instead keeps room for
// the widest content it has shown, which is what the whole table drawn at once
// would give it, so the table settles and then holds still. The width held is
// what the content needs, not what the column happened to get, so a table that
// fits its box keeps fitting. New columns start over.
export function useSteadyColumns(
  head: RefObject<HTMLTableRowElement | null>,
  body: RefObject<HTMLTableSectionElement | null>,
  on: boolean,
  columns: unknown,
  rows: unknown,
) {
  const held = useRef<{ widths: number[]; columns: unknown; rows: unknown }>({ widths: [], columns: null, rows: null });
  useLayoutEffect(() => {
    const row = head.current;
    const section = body.current;
    if (!row || !section) return;
    const heads = Array.from(row.children) as HTMLElement[];
    const state = held.current;
    if (!on || columns !== state.columns || heads.length !== state.widths.length) {
      if (state.widths.length) for (const c of heads) c.style.minWidth = "";
      held.current = { widths: on ? heads.map(() => 0) : [], columns, rows: null };
      if (!on) return;
    }
    if (held.current.rows === rows) return;
    held.current.rows = rows;
    const widths = held.current.widths;
    const lines = section.querySelectorAll(":scope > tr[data-slot=table-row]");
    if (!lines.length) return;
    // Per column, from the first row: the padding around the content, or that
    // the column wraps and so takes what is left instead of holding a width.
    const sample = Array.from(lines[0].children) as HTMLElement[];
    if (sample.length !== heads.length) return;
    const around = sample.map((cell) => {
      const style = getComputedStyle(cell);
      if (style.whiteSpace !== "nowrap") return -1;
      return parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    });
    const need = widths.map(() => 0);
    const range = document.createRange();
    for (let n = 0; n < lines.length; n++) {
      const cells = lines[n].children;
      for (let i = 0; i < cells.length && i < need.length; i++) {
        if (around[i] < 0) continue;
        range.selectNodeContents(cells[i]);
        const w = range.getBoundingClientRect().width;
        if (w > need[i]) need[i] = w;
      }
    }
    heads.forEach((c, i) => {
      if (around[i] < 0) return;
      const w = Math.ceil(need[i] + around[i]);
      if (w > widths[i]) {
        widths[i] = w;
        c.style.minWidth = `${w}px`;
      }
    });
  });
}
