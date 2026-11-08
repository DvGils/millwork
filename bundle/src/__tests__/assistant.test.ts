import { describe, expect, it } from "vitest";
import { clampPosition, clampRect, cursorFor, edgesAt, isClick, minimizeTo, openFrom, panelSize, resizeRect, restingPlace } from "../assistant-math";

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

describe("the window", () => {
  it("opens up and inward from a button at the bottom right, and minimizes back to it", () => {
    const panel = panelSize(viewport);
    expect(panel).toEqual({ width: 380, height: 600 });
    const at = openFrom({ x: 1208, y: 828, ...button }, panel, viewport);
    expect(at).toEqual({ x: 1208 + 48 - 380, y: 828 + 48 - 600, width: 380, height: 600 });
    expect(minimizeTo(at, button, viewport)).toEqual({ x: 1208, y: 828 });
  });

  it("opens to the right of a button on the left, kept inside the viewport", () => {
    const at = openFrom({ x: 24, y: 30, ...button }, panelSize(viewport), viewport);
    expect(at).toEqual({ x: 24, y: 16, width: 380, height: 600 });
    expect(minimizeTo(at, button, viewport)).toEqual({ x: 24, y: 16 + 600 - 48 });
  });

  it("shrinks to a small viewport and stays inside it", () => {
    const small = { width: 360, height: 640 };
    expect(panelSize(small)).toEqual({ width: 328, height: 600 });
    const at = clampRect({ x: 100, y: 100, width: 900, height: 900 }, small);
    expect(at).toEqual({ x: 16, y: 16, width: 328, height: 608 });
  });

  it("knows which edge a press takes hold of, and the cursor for it", () => {
    const rect = { x: 100, y: 100, width: 300, height: 400 };
    expect(edgesAt({ x: 102, y: 250 }, rect)).toMatchObject({ left: true, right: false, top: false, bottom: false });
    expect(edgesAt({ x: 398, y: 498 }, rect)).toMatchObject({ right: true, bottom: true });
    expect(edgesAt({ x: 250, y: 250 }, rect)).toEqual({ left: false, right: false, top: false, bottom: false });
    expect(cursorFor(edgesAt({ x: 398, y: 498 }, rect))).toBe("nwse-resize");
    expect(cursorFor(edgesAt({ x: 102, y: 498 }, rect))).toBe("nesw-resize");
    expect(cursorFor(edgesAt({ x: 250, y: 102 }, rect))).toBe("ns-resize");
  });

  it("resizes from an edge, never below the minimum, never past the viewport", () => {
    const rect = { x: 500, y: 200, width: 380, height: 600 };
    const edges = { left: false, right: true, top: false, bottom: true };
    expect(resizeRect(rect, edges, 100, 50, viewport)).toEqual({ x: 500, y: 200, width: 480, height: 650 });
    const fromLeft = resizeRect(rect, { left: true, right: false, top: true, bottom: false }, 200, 400, viewport);
    expect(fromLeft).toEqual({ x: 600, y: 480, width: 280, height: 320 });
    const tooFar = resizeRect(rect, edges, 2000, 2000, viewport);
    expect(tooFar.width).toBe(1280 - 32);
    expect(tooFar.x + tooFar.width).toBeLessThanOrEqual(1280 - 16);
  });
});
