import { describe, expect, it } from "vitest";
import { clampPosition, isClick, panelSize, placePanel, restingPlace } from "../assistant-math";

const viewport = { width: 1280, height: 900 };
const button = { width: 48, height: 48 };

describe("the floating button", () => {
  it("rests in a bottom corner and stays inside the viewport when dragged", () => {
    expect(restingPlace("right", button, viewport)).toEqual({ x: 1208, y: 828 });
    expect(restingPlace("left", button, viewport)).toEqual({ x: 24, y: 828 });
    expect(clampPosition({ x: -50, y: 2000 }, button, viewport)).toEqual({ x: 16, y: 836 });
    expect(clampPosition({ x: 500, y: 300 }, button, viewport)).toEqual({ x: 500, y: 300 });
  });

  it("tells a click from a drag by how far the pointer moved", () => {
    expect(isClick({ x: 10, y: 10 }, { x: 12, y: 13 })).toBe(true);
    expect(isClick({ x: 10, y: 10 }, { x: 15, y: 10 })).toBe(false);
  });
});

describe("the panel", () => {
  it("opens above a button at the bottom right, hanging from its right edge", () => {
    const panel = panelSize(viewport);
    expect(panel).toEqual({ width: 380, height: 600 });
    const at = placePanel({ x: 1208, y: 828, ...button }, panel, viewport);
    expect(at).toEqual({ x: 1208 + 48 - 380, y: 828 - 12 - 600 });
  });

  it("opens below a button near the top, and to the right of one on the left", () => {
    const panel = panelSize(viewport);
    const at = placePanel({ x: 24, y: 30, ...button }, panel, viewport);
    expect(at).toEqual({ x: 24, y: 30 + 48 + 12 });
  });

  it("sits beside a button when there is room neither above nor below", () => {
    const panel = panelSize(viewport);
    const at = placePanel({ x: 376, y: 276, ...button }, panel, viewport);
    expect(at).toEqual({ x: 376 + 48 + 12, y: 16 });
    const right = placePanel({ x: 900, y: 276, ...button }, panel, viewport);
    expect(right).toEqual({ x: 900 - 12 - 380, y: 16 });
  });

  it("shrinks to a small viewport and stays inside it", () => {
    const small = { width: 360, height: 640 };
    const panel = panelSize(small);
    expect(panel).toEqual({ width: 328, height: 600 });
    const at = placePanel({ x: 296, y: 576, ...button }, panel, small);
    expect(at).toEqual({ x: 16, y: 24 });
    expect(at.x + panel.width).toBeLessThanOrEqual(small.width - 16);
  });
});
