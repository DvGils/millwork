// Finding a component on the page by the id of its node, for what the
// server asks of one: the keyboard put in it, a highlight drawn over it.
//
// The wrapper every node is drawn in carries the node's id. It takes no
// room on the page itself, so what is acted on is inside it. A part that
// its parent draws itself, a tab's trigger or an accordion's item, carries
// the id on its own element. A field of a form carries its pointer.

// What the keyboard can be in.
export const FOCUSABLE = "input, textarea, select, button, a[href], [tabindex]:not([tabindex='-1'])";

// The elements a node is on the page as, or a field of a form in it. None
// for a node that is hidden or not on the page.
export function elementsOf(id: string, field?: string): HTMLElement[] {
  const out: HTMLElement[] = [];
  for (const holder of Array.from(document.querySelectorAll<HTMLElement>(`[data-node="${CSS.escape(id)}"]`))) {
    if (holder.style.display === "none") continue;
    if (field !== undefined) {
      const inside = holder.querySelector<HTMLElement>(`[data-field="${CSS.escape(field)}"]`);
      if (inside) out.push(inside);
    } else if (holder.style.display === "contents") {
      for (const child of Array.from(holder.children)) if (child instanceof HTMLElement) out.push(child);
    } else {
      out.push(holder);
    }
  }
  return out;
}

// Put the keyboard in a node, or in a field of a form in it: in the first
// thing inside that takes it. One that is disabled or not on the screen is
// passed over for the next, so a card whose first field cannot be typed in
// gives it to the second. False when nothing took it.
export function focusNode(id: string, field?: string): boolean {
  for (const holder of elementsOf(id, field)) {
    const inside = [...(holder.matches(FOCUSABLE) ? [holder] : []), ...Array.from(holder.querySelectorAll<HTMLElement>(FOCUSABLE))];
    for (const element of inside) {
      if (element.matches(":disabled") || element.getClientRects().length === 0) continue;
      element.focus();
      if (document.activeElement === element) return true;
    }
  }
  return false;
}

export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

// The box around some rectangles, without the ones that take no room.
export function around(rects: Box[]): Box | null {
  let box: Box | null = null;
  for (const r of rects) {
    if (r.right - r.left <= 0 || r.bottom - r.top <= 0) continue;
    box = box
      ? { left: Math.min(box.left, r.left), top: Math.min(box.top, r.top), right: Math.max(box.right, r.right), bottom: Math.max(box.bottom, r.bottom) }
      : { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
  }
  return box;
}

// What two boxes have in common, or null when that is nothing.
export function common(a: Box, b: Box): Box | null {
  const box = { left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) };
  return box.right - box.left > 0 && box.bottom - box.top > 0 ? box : null;
}
