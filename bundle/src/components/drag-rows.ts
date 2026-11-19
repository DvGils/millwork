// The arithmetic of dragging a row through lists of rows: which place the
// pointer means in a list, and what scrolls when the pointer is near an edge.

export interface Span {
  top: number;
  height: number;
}

// The place a held row would land in a list: the slot whose gap would be
// nearest to the row as it is held. `rows` are the other rows of the list,
// measured as the page shows them, `middle` is the height of the held
// row's middle, `held` is how high the row is and `between` the room
// between rows.
//
// The page shows the list with a gap open at `gapAt` when it has one, so a
// row at or after the gap is first counted as that much higher than it
// shows. A place is then the same with the gap as without, and does not
// flip as the gap opens. The gap at place i starts where row i starts, so
// the held row is nearer to place i + 1 once its middle is past the
// middle of that gap and row i taken together.
export function placeAt(rows: Span[], middle: number, held: number, between: number, gapAt: number | null): number {
  let n = 0;
  rows.forEach((row, i) => {
    const top = row.top - (gapAt !== null && i >= gapAt ? held + between : 0);
    if (top + (held + row.height + between) / 2 < middle) n++;
  });
  return n;
}

// How far to scroll this frame, for a pointer at `y` in something that
// shows from `top` to `bottom`: nothing in the middle, and more the
// nearer the pointer is to an edge.
export const EDGE = 48;
export function scrollBy(y: number, top: number, bottom: number): number {
  if (y < top + EDGE) return -Math.ceil(((top + EDGE - y) / EDGE) * 14);
  if (y > bottom - EDGE) return Math.ceil(((y - (bottom - EDGE)) / EDGE) * 14);
  return 0;
}
