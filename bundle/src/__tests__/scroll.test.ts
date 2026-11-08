import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// A body that scrolls: the height it holds grows when a lazy part arrives.
class Body {
  scrollTop = 0;
  clientHeight = 800;
  scrollHeight = 800;
  style: Record<string, string> = {};
}

let body: Body | null;
let state: Record<string, unknown> | null;
let g: any;

beforeEach(() => {
  g = globalThis as any;
  body = new Body();
  state = null;
  g.document = { querySelector: () => body, addEventListener: vi.fn() };
  g.window = {
    scrollY: 0,
    scrollTo: vi.fn(),
    requestAnimationFrame: (f: () => void) => setTimeout(f, 16),
    setTimeout: (f: () => void, ms: number) => setTimeout(f, ms),
    clearTimeout: (t: unknown) => clearTimeout(t as any),
    history: {
      get state() {
        return state;
      },
      replaceState(s: Record<string, unknown>) {
        state = s;
      },
    },
  };
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  delete g.document;
  delete g.window;
});

describe("scroll", () => {
  it("restores at once when the page is tall enough, and zero always", async () => {
    const { restoreScroll } = await import("../scroll");
    body!.scrollTop = 1500;
    restoreScroll(0);
    expect(body!.scrollTop).toBe(0);
    body!.scrollHeight = 5000;
    restoreScroll(1200);
    expect(body!.scrollTop).toBe(1200);
    // anchoring is off while the new page is drawn, then back on
    expect(body!.style.overflowAnchor).toBe("none");
    vi.advanceTimersByTime(50);
    expect(body!.style.overflowAnchor).toBe("");
  });

  it("waits for a short page to grow, then lands on the position", async () => {
    const { restoreScroll } = await import("../scroll");
    restoreScroll(1200);
    expect(body!.scrollTop).toBe(0);
    vi.advanceTimersByTime(250);
    expect(body!.scrollTop).toBe(0);
    body!.scrollHeight = 5000;
    vi.advanceTimersByTime(100);
    expect(body!.scrollTop).toBe(1200);
  });

  it("gives up when the reader scrolls in the meantime", async () => {
    const { restoreScroll } = await import("../scroll");
    restoreScroll(1200);
    body!.scrollTop = 40;
    body!.scrollHeight = 5000;
    vi.advanceTimersByTime(2000);
    expect(body!.scrollTop).toBe(40);
  });

  it("keeps the position in the history entry and reads it back", async () => {
    const { keepScrollInHistory, scrollFromHistory } = await import("../scroll");
    expect(scrollFromHistory()).toBe(0);
    body!.scrollTop = 333;
    state = { mw: true };
    keepScrollInHistory();
    expect(state).toEqual({ mw: true, scroll: 333 });
    expect(scrollFromHistory()).toBe(333);
  });
});
