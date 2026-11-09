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

// How big an assistant's window likes to be until the reader resizes it.
export const PANEL_SIZE: Size = { width: 380, height: 600 };

// The window's size when it opens: as big as it likes, within the viewport.
export function panelSize(viewport: Size, wanted: Size = PANEL_SIZE): Size {
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

// Whether a thing sits in the right half of the viewport, which decides the
// side a window opens toward and the corner a button minimizes to. A window
// in the right half puts its button in the right half and one in the left
// half in the left, so opening from that button gives the same window.
export function onRightHalf(rect: Rect, viewport: Size): boolean {
  return rect.x + rect.width / 2 > viewport.width / 2;
}

// Where the button lands when the window is minimized: the window's bottom
// corner on the half of the screen the window is in.
export function minimizeTo(panel: Rect, button: Size, viewport: Size): Point {
  const x = onRightHalf(panel, viewport) ? panel.x + panel.width - button.width : panel.x;
  return clampPosition({ x, y: panel.y + panel.height - button.height }, button, viewport);
}

const NO_EDGES: Edges = { left: false, right: false, top: false, bottom: false };

// Which edges of a rectangle a point takes hold of, for resizing. A thing
// too small to have a middle has no edges to take: it is moved, not resized.
export function edgesAt(at: Point, rect: Rect, grip: number = GRIP): Edges {
  if (rect.width < 4 * grip || rect.height < 4 * grip) return NO_EDGES;
  const inside = at.x >= rect.x - grip && at.x <= rect.x + rect.width + grip && at.y >= rect.y - grip && at.y <= rect.y + rect.height + grip;
  if (!inside) return NO_EDGES;
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

// The rectangle after the held edges moved by (dx, dy). An edge stops at the
// minimum size and at the viewport's margin; the edges not held stay where
// they are.
export function resizeRect(from: Rect, edges: Edges, dx: number, dy: number, viewport: Size, min: Size = MIN_SIZE): Rect {
  let { x, y, width, height } = from;
  const right = from.x + from.width;
  const bottom = from.y + from.height;
  if (edges.right) width = Math.min(Math.max(min.width, from.width + dx), viewport.width - MARGIN - from.x);
  if (edges.bottom) height = Math.min(Math.max(min.height, from.height + dy), viewport.height - MARGIN - from.y);
  if (edges.left) {
    width = Math.min(Math.max(min.width, from.width - dx), right - MARGIN);
    x = right - width;
  }
  if (edges.top) {
    height = Math.min(Math.max(min.height, from.height - dy), bottom - MARGIN);
    y = bottom - height;
  }
  return clampRect({ x, y, width, height }, viewport, min);
}
