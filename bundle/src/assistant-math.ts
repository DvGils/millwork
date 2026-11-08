// Where a floating thing goes and how big it is: pure arithmetic on
// rectangles, kept apart from the components so it can be checked on its own.

export type Point = { x: number; y: number };
export type Size = { width: number; height: number };
export type Rect = Point & Size;
export type Edges = { left: boolean; right: boolean; top: boolean; bottom: boolean };

// The least a floating thing keeps from the edge of the viewport.
export const MARGIN = 16;
// The room between a button and the window it opens.
export const GAP = 12;
// A press that moves less than this is a click, not a drag.
export const SLOP = 4;
// How far in from a window's edge a press still takes hold of that edge.
export const GRIP = 8;
// The least a window can be.
export const MIN_SIZE: Size = { width: 280, height: 320 };

export function isClick(from: Point, to: Point): boolean {
  return Math.abs(to.x - from.x) < SLOP && Math.abs(to.y - from.y) < SLOP;
}

// A size that fits the viewport, margins included, and is at least the minimum
// where the viewport allows it.
export function fitSize(size: Size, viewport: Size, min: Size = MIN_SIZE): Size {
  const maxW = Math.max(1, viewport.width - 2 * MARGIN);
  const maxH = Math.max(1, viewport.height - 2 * MARGIN);
  return {
    width: Math.min(Math.max(size.width, Math.min(min.width, maxW)), maxW),
    height: Math.min(Math.max(size.height, Math.min(min.height, maxH)), maxH),
  };
}

// The top-left corner kept inside the viewport, margin included.
export function clampPosition(at: Point, size: Size, viewport: Size): Point {
  const maxX = Math.max(MARGIN, viewport.width - MARGIN - size.width);
  const maxY = Math.max(MARGIN, viewport.height - MARGIN - size.height);
  return { x: Math.min(Math.max(MARGIN, at.x), maxX), y: Math.min(Math.max(MARGIN, at.y), maxY) };
}

// A whole rectangle made to fit: shrunk to the viewport first, then moved inside it.
export function clampRect(rect: Rect, viewport: Size, min: Size = MIN_SIZE): Rect {
  const size = fitSize(rect, viewport, min);
  return { ...clampPosition(rect, size, viewport), ...size };
}

// The corner the button starts in: bottom right, or bottom left.
export function restingPlace(side: "left" | "right", button: Size, viewport: Size): Point {
  const y = viewport.height - MARGIN - 8 - button.height;
  return { x: side === "left" ? MARGIN + 8 : viewport.width - MARGIN - 8 - button.width, y };
}

// The window's size when it first opens: as big as it likes, within the viewport.
export function panelSize(viewport: Size, wanted: Size = { width: 380, height: 600 }): Size {
  return fitSize(wanted, viewport);
}

// Where the window opens from a button: it grows up and inward from the
// button's corner, so the button's place becomes the window's near bottom
// corner, and then it is kept inside the viewport.
export function openFrom(button: Rect, panel: Size, viewport: Size): Rect {
  const onRight = button.x + button.width / 2 > viewport.width / 2;
  const x = onRight ? button.x + button.width - panel.width : button.x;
  const y = button.y + button.height - panel.height;
  return clampRect({ x, y, ...panel }, viewport);
}

// Where the button lands when the window is minimized: the window's bottom
// corner on the side the window is on.
export function minimizeTo(panel: Rect, button: Size, viewport: Size): Point {
  const onRight = panel.x + panel.width / 2 > viewport.width / 2;
  const x = onRight ? panel.x + panel.width - button.width : panel.x;
  return clampPosition({ x, y: panel.y + panel.height - button.height }, button, viewport);
}

// Which edges of a rectangle a point takes hold of, for resizing.
export function edgesAt(at: Point, rect: Rect, grip: number = GRIP): Edges {
  const inside = at.x >= rect.x - grip && at.x <= rect.x + rect.width + grip && at.y >= rect.y - grip && at.y <= rect.y + rect.height + grip;
  if (!inside) return { left: false, right: false, top: false, bottom: false };
  return {
    left: at.x <= rect.x + grip,
    right: at.x >= rect.x + rect.width - grip,
    top: at.y <= rect.y + grip,
    bottom: at.y >= rect.y + rect.height - grip,
  };
}

export function hasEdge(edges: Edges): boolean {
  return edges.left || edges.right || edges.top || edges.bottom;
}

// The CSS cursor for a hold on these edges.
export function cursorFor(edges: Edges): string | undefined {
  const ns = edges.top || edges.bottom;
  const ew = edges.left || edges.right;
  if (ns && ew) return (edges.top && edges.left) || (edges.bottom && edges.right) ? "nwse-resize" : "nesw-resize";
  if (ns) return "ns-resize";
  if (ew) return "ew-resize";
  return undefined;
}

// The rectangle after the held edges moved by (dx, dy). An edge that would
// take the window below its minimum size stays, and the result fits the viewport.
export function resizeRect(from: Rect, edges: Edges, dx: number, dy: number, viewport: Size, min: Size = MIN_SIZE): Rect {
  let { x, y, width, height } = from;
  if (edges.right) width = from.width + dx;
  if (edges.bottom) height = from.height + dy;
  if (edges.left) {
    const w = from.width - dx;
    const applied = Math.max(min.width, w);
    x = from.x + (from.width - applied);
    width = applied;
  }
  if (edges.top) {
    const h = from.height - dy;
    const applied = Math.max(min.height, h);
    y = from.y + (from.height - applied);
    height = applied;
  }
  return clampRect({ x, y, width: Math.max(min.width, width), height: Math.max(min.height, height) }, viewport, min);
}
