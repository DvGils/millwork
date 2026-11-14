// The layer that draws the highlights. It lies over the whole page and
// takes no press. For each mark that shows it measures where the component
// is, every frame while there are marks, and puts a frame there: a border
// set on the component itself would not do, since the wrapper a node is
// drawn in takes no room and a dialog is drawn outside the page's own
// elements.
//
// The tab is the one that knows what is on the screen. A mark's time runs
// from when its component was first there to see, and getting to the
// component, with the pointer or the keyboard, takes the mark off. The
// session is told either. The frame goes at once, and the mark itself
// when the session sends the list without it: the session is the one that
// holds the marks. What it was told can be lost, with a connection or
// with a page that did not come, and then the mark shows again.

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { emit } from "./ws";
import { around, common, elementsOf, type Box } from "./pointing";
import { inkOn, markBadge, markColor, useMarks, type Mark } from "./marks";

// How far the frame stands off the component.
const OFF = 3;
// How long the session has to send the list without a mark it was told is
// done, before the mark shows again.
export const TOLD_FOR = 3000;
// How many frames pass before a mark's component is looked up again. In
// between, the elements found last are measured, unless one of them left
// the page.
const LOOK_EVERY = 12;

// What is known of a mark between the lists the session sends.
interface Known {
  seen: boolean;
  scrolled: boolean;
  timer: number | null;
  ink: string;
  // When the session was told that this one is done, or 0.
  told: number;
  // The elements it is on, the ones above them that cut what shows, and
  // the frame they were looked up in.
  targets: HTMLElement[];
  clips: HTMLElement[];
  looked: number;
}
const known = new Map<number, Known>();
let frames = 0;

function about(n: number): Known {
  let k = known.get(n);
  if (!k) known.set(n, (k = { seen: false, scrolled: false, timer: null, ink: "", told: 0, targets: [], clips: [], looked: -LOOK_EVERY }));
  return k;
}

// Whether the session was told a mark is done and still has the time to
// say so itself.
export function stillTold(told: number, now: number): boolean {
  return told > 0 && now - told < TOLD_FOR;
}

function done(mark: Mark, what: "touched" | "timed out") {
  const k = about(mark.n);
  if (stillTold(k.told, performance.now())) return;
  k.told = performance.now();
  if (k.timer != null) window.clearTimeout(k.timer);
  k.timer = null;
  // Should it show again, its time runs anew.
  k.seen = false;
  emit(mark.id, "mark", { n: mark.n, what });
}

// The elements of a mark, looked up again when they are gone or stale.
function targetsOf(mark: Mark, k: Known): HTMLElement[] {
  const stale = frames - k.looked >= LOOK_EVERY || k.targets.length === 0 || k.targets.some((t) => !t.isConnected);
  if (stale) {
    k.looked = frames;
    k.targets = elementsOf(mark.id, mark.field);
    k.clips = [];
    for (let up = k.targets[0]?.parentElement; up && up !== document.body; up = up.parentElement) {
      const flow = getComputedStyle(up);
      if (flow.overflowX !== "visible" || flow.overflowY !== "visible") k.clips.push(up);
    }
  }
  return k.targets;
}

// The part of a component that is there to see: inside the window and
// inside whatever it scrolls in. Null when none of it is, or when something
// else lies over it, a dialog over the page behind it.
function shows(k: Known, box: Box): Box | null {
  let part: Box | null = common(box, { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight });
  for (const clip of k.clips) {
    if (!part) break;
    part = common(part, clip.getBoundingClientRect());
  }
  if (!part) return null;
  const top = document.elementFromPoint((part.left + part.right) / 2, (part.top + part.bottom) / 2);
  if (top && !k.targets.some((t) => t.contains(top) || top.contains(t))) return null;
  return part;
}

// The color a mark's badge is in, as red, green and blue, for the ink on it.
let probe: CanvasRenderingContext2D | null | undefined;
function inkFor(color: string): string {
  if (probe === undefined) probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  if (!probe) return "#fff";
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = color;
  probe.fillRect(0, 0, 1, 1);
  const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
  return inkOn(r, g, b);
}

interface Placed {
  el: HTMLDivElement;
  box: Box | null;
  part: Box | null;
  color: string | null;
}

export function Marks() {
  const list = useMarks();
  const drawn = useRef(new Map<number, HTMLDivElement>());

  useEffect(() => {
    // What the session no longer has needs no time kept for it.
    for (const [n, k] of known) {
      if (list.some((m) => m.n === n)) continue;
      if (k.timer != null) window.clearTimeout(k.timer);
      known.delete(n);
    }
    if (list.length === 0) return;

    let frame = 0;
    const tick = () => {
      frames += 1;
      const now = performance.now();
      // Everything is measured first and then put in place, so the page is
      // laid out once a frame and not once a mark.
      const placed: Placed[] = [];
      for (const mark of list) {
        if (mark.waits) continue;
        const el = drawn.current.get(mark.n);
        if (!el) continue;
        const k = about(mark.n);
        if (stillTold(k.told, now)) {
          placed.push({ el, box: null, part: null, color: null });
          continue;
        }
        const targets = targetsOf(mark, k);
        const box = around(targets.map((t) => t.getBoundingClientRect()));
        const part = box ? shows(k, box) : null;
        if (box && mark.scroll && !k.scrolled) {
          k.scrolled = true;
          // Only what is not in view, or not all of it, is brought there.
          const whole = part && part.right - part.left >= box.right - box.left - 1 && part.bottom - part.top >= box.bottom - box.top - 1;
          if (!whole) targets[0].scrollIntoView({ block: "center", behavior: "smooth" });
        }
        const badge = el.firstElementChild;
        placed.push({ el, box, part, color: box && part && badge ? getComputedStyle(badge).backgroundColor : null });
        if (box && part && !k.seen) {
          k.seen = true;
          if (mark.seconds) k.timer = window.setTimeout(() => done(mark, "timed out"), mark.seconds * 1000);
        }
      }
      for (const { el, box, part, color } of placed) {
        if (!box || !part) {
          el.style.display = "none";
          continue;
        }
        el.style.display = "";
        el.style.transform = `translate(${box.left - OFF}px, ${box.top - OFF}px)`;
        el.style.width = `${box.right - box.left + 2 * OFF}px`;
        el.style.height = `${box.bottom - box.top + 2 * OFF}px`;
        // Cut where the component is cut by what it scrolls in, and whole
        // on the sides where all of it shows.
        const cut = (edge: number) => (edge > 0.5 ? `${edge + OFF}px` : "-40px");
        el.style.clipPath = `inset(${cut(part.top - box.top)} ${cut(box.right - part.right)} ${cut(box.bottom - part.bottom)} ${cut(part.left - box.left)})`;
        const badge = el.firstElementChild as HTMLElement | null;
        if (badge && color && color !== badge.dataset.on) {
          badge.dataset.on = color;
          badge.style.color = inkFor(color);
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    // Getting to a component takes its mark off: the pointer over it, a
    // press on it, a key or a text typed in it, or the Tab key arriving in
    // it. A text counts by itself, since a phone's keyboard and a paste
    // send no key. The
    // keyboard being put there by the page does not count, as a dialog
    // does with its first field when it opens. On a component whose mark
    // waits for the steps before it, only a press or a key counts: the
    // pointer passing over something that shows no mark is no sign of
    // anything.
    const reach = (target: EventTarget | null, pressed: boolean) => {
      if (!(target instanceof Node)) return;
      for (const mark of list) {
        if (mark.waits && !pressed) continue;
        if (targetsOf(mark, about(mark.n)).some((el) => el.contains(target))) done(mark, "touched");
      }
    };
    const over = (e: Event) => reach(e.target, false);
    const press = (e: Event) => reach(e.target, true);
    const arrive = (e: KeyboardEvent) => {
      if (e.key === "Tab") reach(e.target, true);
    };
    document.addEventListener("pointerover", over, true);
    document.addEventListener("pointerdown", press, true);
    document.addEventListener("keydown", press, true);
    document.addEventListener("input", press, true);
    document.addEventListener("keyup", arrive, true);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("pointerover", over, true);
      document.removeEventListener("pointerdown", press, true);
      document.removeEventListener("keydown", press, true);
      document.removeEventListener("input", press, true);
      document.removeEventListener("keyup", arrive, true);
    };
  }, [list]);

  const shown = list.filter((m) => !m.waits);
  if (shown.length === 0) return null;
  return createPortal(
    <div className="mw-marks" aria-hidden="true">
      {shown.map((mark) => {
        const badge = markBadge(mark);
        return (
          <div
            key={mark.n}
            ref={(el) => {
              if (el) drawn.current.set(mark.n, el);
              else drawn.current.delete(mark.n);
            }}
            className={`mw-mark mw-mark-${mark.style}`}
            style={{ "--mw-mark": markColor(mark.color), display: "none" } as React.CSSProperties}
          >
            {badge ? <span className="mw-mark-badge">{badge}</span> : null}
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
