import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stickToEnd } from "../stick";

type Heard = Record<string, Array<() => void>>;

// A box that takes listeners, as far as the staying needs one.
class Box {
  heard: Heard = {};
  addEventListener(name: string, f: () => void) {
    (this.heard[name] ??= []).push(f);
  }
  removeEventListener(name: string, f: () => void) {
    this.heard[name] = (this.heard[name] ?? []).filter((g) => g !== f);
  }
  tell(name: string) {
    for (const f of this.heard[name] ?? []) f();
  }
}

// A viewport that scrolls: the browser clamps a position to what it holds.
class Viewport extends Box {
  private top = 0;
  clientHeight = 300;
  scrollHeight = 1000;
  firstElementChild = {};
  get scrollTop() {
    return this.top;
  }
  set scrollTop(y: number) {
    this.top = Math.max(0, Math.min(y, this.scrollHeight - this.clientHeight));
  }
  get fromEnd() {
    return this.scrollHeight - this.top - this.clientHeight;
  }
}

class Holder extends Box {
  private viewport: Viewport | null;
  constructor(viewport: Viewport | null) {
    super();
    this.viewport = viewport;
  }
  querySelector(selector: string) {
    return selector === '[data-slot="scroll-area-viewport"]' ? this.viewport : null;
  }
}

let resized: () => void;
let watched: unknown[];
let disconnected: boolean;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(100_000);
  watched = [];
  disconnected = false;
  (globalThis as any).ResizeObserver = class {
    constructor(f: () => void) {
      resized = f;
    }
    observe(what: unknown) {
      watched.push(what);
    }
    disconnect() {
      disconnected = true;
    }
  };
});

afterEach(() => {
  vi.useRealTimers();
  delete (globalThis as any).ResizeObserver;
});

function area() {
  const viewport = new Viewport();
  const holder = new Holder(viewport);
  const undo = stickToEnd(holder as unknown as HTMLElement);
  // The content grows by so much, as a row that arrives makes it.
  const grow = (by: number) => {
    viewport.scrollHeight += by;
    resized();
  };
  // The reader's own scroll: a wheel in the area, and where it left them.
  const wheelTo = (y: number) => {
    holder.tell("wheel");
    viewport.scrollTop = y;
    viewport.tell("scroll");
  };
  return { viewport, holder, undo, grow, wheelTo };
}

describe("stickToEnd", () => {
  it("opens at the end and stays there as the content grows", () => {
    const { viewport, grow } = area();
    expect(viewport.fromEnd).toBe(0);
    grow(80);
    expect(viewport.fromEnd).toBe(0);
    expect(watched).toEqual([viewport, viewport.firstElementChild]);
  });

  it("stays at the end when the area itself gets smaller", () => {
    const { viewport } = area();
    viewport.clientHeight = 200;
    resized();
    expect(viewport.fromEnd).toBe(0);
  });

  it("leaves a reader who scrolled away where they are", () => {
    const { viewport, grow, wheelTo } = area();
    wheelTo(100);
    grow(80);
    expect(viewport.scrollTop).toBe(100);
  });

  it("stays again once the reader is back at the end", () => {
    const { viewport, grow, wheelTo } = area();
    wheelTo(100);
    // Within a few pixels of the end is the end.
    wheelTo(viewport.scrollHeight - viewport.clientHeight - 5);
    grow(80);
    expect(viewport.fromEnd).toBe(0);
  });

  it("is not ended by a scroll the reader did not make", () => {
    const { viewport, holder, grow } = area();
    // A wheel long ago, and now a position the page came to by itself.
    holder.tell("wheel");
    vi.setSystemTime(100_000 + 5_000);
    viewport.scrollTop = 100;
    viewport.tell("scroll");
    grow(80);
    expect(viewport.fromEnd).toBe(0);
  });

  it("lets go of everything when it is undone", () => {
    const { viewport, holder, undo } = area();
    undo();
    expect(disconnected).toBe(true);
    expect(Object.values(viewport.heard).flat()).toEqual([]);
    expect(Object.values(holder.heard).flat()).toEqual([]);
  });

  it("does nothing for a holder without a viewport", () => {
    const undo = stickToEnd(new Holder(null) as unknown as HTMLElement);
    expect(watched).toEqual([]);
    undo();
  });
});
