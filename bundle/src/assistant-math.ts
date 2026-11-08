// Where a floating button and its panel go: pure arithmetic on rectangles,
// kept apart from the component so it can be checked on its own.

export type Point = { x: number; y: number };
export type Size = { width: number; height: number };
export type Rect = Point & Size;

// The least a floating thing keeps from the edge of the viewport.
export const MARGIN = 16;
// The room between the button and its panel.
export const GAP = 12;
// A press that moves less than this is a click, not a drag.
export const SLOP = 4;

export function isClick(from: Point, to: Point): boolean {
  return Math.abs(to.x - from.x) < SLOP && Math.abs(to.y - from.y) < SLOP;
}

// The button's top-left corner kept inside the viewport, margin included.
export function clampPosition(at: Point, button: Size, viewport: Size): Point {
  const maxX = Math.max(MARGIN, viewport.width - MARGIN - button.width);
  const maxY = Math.max(MARGIN, viewport.height - MARGIN - button.height);
  return { x: Math.min(Math.max(MARGIN, at.x), maxX), y: Math.min(Math.max(MARGIN, at.y), maxY) };
}

// The corner the button starts in: bottom right, or bottom left.
export function restingPlace(side: "left" | "right", button: Size, viewport: Size): Point {
  const y = viewport.height - MARGIN - 8 - button.height;
  return { x: side === "left" ? MARGIN + 8 : viewport.width - MARGIN - 8 - button.width, y };
}

// The panel's size: as wide and as tall as it likes, within the viewport.
export function panelSize(viewport: Size, wanted: Size = { width: 380, height: 600 }): Size {
  return {
    width: Math.min(wanted.width, viewport.width - 2 * MARGIN),
    height: Math.min(wanted.height, viewport.height - 2 * MARGIN),
  };
}

// The panel sits above the button when there is room, else below it, and
// hangs from the button's edge that is nearer the middle of the screen, so
// it opens toward the room there is. When neither above nor below has the
// room, it sits beside the button instead of over it. Then it is kept
// inside the viewport.
export function placePanel(button: Rect, panel: Size, viewport: Size): Point {
  const onRight = button.x + button.width / 2 > viewport.width / 2;
  const maxY = Math.max(MARGIN, viewport.height - MARGIN - panel.height);
  const maxX = Math.max(MARGIN, viewport.width - MARGIN - panel.width);
  const above = button.y - GAP - panel.height;
  const below = button.y + button.height + GAP;
  let x = onRight ? button.x + button.width - panel.width : button.x;
  let y: number;
  if (above >= MARGIN) y = above;
  else if (below <= maxY) y = below;
  else {
    y = Math.min(Math.max(MARGIN, button.y - panel.height / 2), maxY);
    x = onRight ? button.x - GAP - panel.width : button.x + button.width + GAP;
  }
  return { x: Math.min(Math.max(MARGIN, x), maxX), y };
}
