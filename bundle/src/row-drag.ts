// The arithmetic of dragging one row among the rows of its own list, each
// of which stays where it is drawn and is shifted for as long as the drag
// goes on.

export interface Span {
  top: number;
  height: number;
}

// Where a row that was carried `by` pixels from its own place is, and the
// place it means. It does not leave the list: `by` comes back held between
// the first row's top and the last row's bottom. Going up, its place is the
// first row whose middle its top edge is above, and going down the last row
// whose middle its bottom edge is below. Its own while it is past neither.
// By its edges and not its middle, so that a row held at the very end of
// the list means the last place.
export function carry(rows: Span[], from: number, by: number): { by: number; to: number } {
  const own = rows[from];
  const first = rows[0];
  const last = rows[rows.length - 1];
  const held = Math.max(first.top - own.top, Math.min(last.top + last.height - (own.top + own.height), by));
  const top = own.top + held;
  const bottom = top + own.height;
  let to = from;
  for (let i = 0; i < from; i++) {
    if (top < rows[i].top + rows[i].height / 2) {
      to = i;
      break;
    }
  }
  for (let i = from + 1; i < rows.length; i++) {
    if (bottom > rows[i].top + rows[i].height / 2) to = i;
  }
  return { by: held, to };
}

// How far row `i` is shifted while the row at `from`, which is `height`
// high, is held over place `to`: the rows it has passed make room for it.
export function shiftOf(i: number, from: number, to: number, height: number): number {
  if (from < i && i <= to) return -height;
  if (to <= i && i < from) return height;
  return 0;
}
