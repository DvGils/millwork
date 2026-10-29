// The arithmetic of dragging one item through a wrapped row: which slot the
// pointer means, and the list with an item moved there.

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

// The slot a pointer at (x, y) means among boxes laid out in reading order:
// how many boxes come before it. A box is before the pointer when its row is
// above, or when it shares the row and its centre is to the left.
export function slotAt(boxes: Box[], x: number, y: number): number {
  let n = 0;
  for (const b of boxes) {
    const cy = b.top + b.height / 2;
    const cx = b.left + b.width / 2;
    if (cy < y - b.height / 2) n++;
    else if (Math.abs(cy - y) <= b.height / 2 && cx < x) n++;
  }
  return n;
}

export function moved<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || from >= list.length) return list;
  const next = list.slice();
  const [item] = next.splice(from, 1);
  next.splice(Math.max(0, Math.min(to, next.length)), 0, item);
  return next;
}
