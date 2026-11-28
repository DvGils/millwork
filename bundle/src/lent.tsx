// What a component of the app's own borrows from millwork, as
// `import { useRowDrag, RowGrip, Editable } from "millwork"`: rows dragged
// into another order, and a text typed over where it stands. Both show what
// was done at once and leave the last word to the page.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent, type PointerEvent, type RefObject } from "react";
import { GripVerticalIcon } from "lucide-react";
import { cn } from "cn";
import { t } from "./theme";
import { moved } from "./sortable";
import { carry, shiftOf } from "./row-drag";
import { scrollBy } from "./components/drag-rows";

// How long what was done is shown when nothing says whether the page took
// it: a callback that gave no promise, and a page that did not change.
const PATIENCE = 4000;

function thenable(value: unknown): value is PromiseLike<unknown> {
  return typeof value === "object" && value !== null && typeof (value as { then?: unknown }).then === "function";
}

// What was done here stands in for what the page gave until the page has
// answered. Then the page's own value shows again, which is the new one
// when the page took it and the old one when it did not. `answer` is what
// the callback returned. A promise is the page's answer when it is over,
// and the last one given is the one waited for, so what is done several
// times in a row stands until the page is done with all of it. Without a
// promise the answer is a change of what the page gave, or a while gone by.
function useStandIn<T>(given: unknown): [T | null, (shown: T, answer: unknown) => void] {
  const [mine, setMine] = useState<T | null>(null);
  const asked = useRef(0);
  const timer = useRef(0);
  const promised = useRef(false);
  useEffect(() => {
    if (promised.current) return;
    asked.current++;
    window.clearTimeout(timer.current);
    setMine(null);
  }, [given]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const stand = useCallback((shown: T, answer: unknown) => {
    const mineNow = ++asked.current;
    window.clearTimeout(timer.current);
    setMine(shown);
    const back = () => {
      if (asked.current !== mineNow) return;
      promised.current = false;
      setMine(null);
    };
    promised.current = thenable(answer);
    if (thenable(answer)) answer.then(back, back);
    else timer.current = window.setTimeout(back, PATIENCE);
  }, []);
  return [mine, stand];
}

// One place for a screen reader to hear where a row went, for all of them.
// It is on the page before anything is said in it, since words put in a
// place that is new with them are often not read out.
let region: HTMLElement | null = null;
function saidAt(): HTMLElement {
  if (!region) {
    region = document.createElement("span");
    region.className = "mw-said";
    region.setAttribute("aria-live", "polite");
    document.body.appendChild(region);
  }
  return region;
}
// Emptied first, so the same words twice in a row are said twice. Words
// that come before the ones before them were said take their place.
let saying = 0;
function say(words: string) {
  const at = saidAt();
  at.textContent = "";
  window.clearTimeout(saying);
  saying = window.setTimeout(() => (at.textContent = words), 50);
}

// What scrolls the rows: the nearest thing around them, the list itself
// included, that scrolls down and has more than it shows.
function scrollerOf(el: Element): Element {
  for (let up: Element | null = el; up && up !== document.body; up = up.parentElement) {
    const flow = getComputedStyle(up).overflowY;
    if ((flow === "auto" || flow === "scroll") && up.scrollHeight > up.clientHeight) return up;
  }
  return document.scrollingElement ?? document.documentElement;
}

// The order that was dropped, of the rows the page has now: a row the page
// has taken away is left out, and one it has added comes at the end.
function fit(mine: string[], keys: string[]): string[] {
  const have = new Set(keys);
  const kept = mine.filter((key) => have.has(key));
  if (kept.length === keys.length) return kept;
  const seen = new Set(kept);
  return [...kept, ...keys.filter((key) => !seen.has(key))];
}

export type Grip = Pick<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "onPointerDown" | "onPointerMove" | "onPointerUp" | "onPointerCancel" | "onLostPointerCapture" | "onKeyDown" | "disabled" | "aria-keyshortcuts" | "style"
>;

// A finger on a grip carries the row, and does not scroll the page.
const HELD_BY_A_FINGER = { touchAction: "none" } as const;

export interface RowDragOptions {
  // The keys of the rows, in the order the page gave them.
  keys: string[];
  // A row was moved to another place, counted from 0: dropped there, or
  // moved a place by the keyboard. Called once for each move. What it
  // returns is waited for when it is a promise, as `emit` gives one.
  onMove: (key: string, to: number) => unknown;
  disabled?: boolean;
  // How much of the top and bottom of the box that scrolls is covered by
  // what stays there, a header that sticks say, in pixels. A row held near
  // what is left of an edge scrolls the box.
  inset?: { top?: number; bottom?: number };
  // The ref of the element whose children are the rows, for a component
  // that has one of its own. `list` in what comes back is then this one.
  list?: RefObject<HTMLElement | null>;
}

export interface RowDrag {
  // Goes on the element whose children are the rows.
  list: RefObject<never>;
  // The order to draw the rows in: the page's, and after a move the
  // moved one until the page has answered. Always the keys the page gave.
  order: string[];
  // Goes on each row. The same object for a key at every drawing.
  row: (key: string) => { "data-mw-row": string };
  // Goes on the row's grip, a `RowGrip` or a button of the component's own.
  // The same object for a key at every drawing.
  grip: (key: string) => Grip;
}

interface Held {
  key: string;
  from: number;
  to: number;
  // The rows from the lowest to the highest place the row has been over,
  // which are the only ones that were touched.
  low: number;
  high: number;
  touched: Set<HTMLElement>;
  els: HTMLElement[];
  spans: { top: number; height: number }[];
  // The room between two rows, which a row that makes room moves by as well.
  gap: number;
  order: string[];
  y0: number;
  y: number;
  scroller: Element;
  scroll0: number;
  frame: number;
}

// Rows of one parent, dragged by a grip into another order, or moved a
// place at a time with Alt and an arrow key on the grip. A row follows the
// pointer by a transform and the rows it passes make room the same way, so
// the page is not laid out again until the row is dropped. Only the rows it
// passes are touched: in a long table a style on every row is a slow frame.
export function useRowDrag({ keys, onMove, disabled = false, inset, list: theirs }: RowDragOptions): RowDrag {
  const own = useRef<HTMLElement>(null);
  const list = theirs ?? own;
  const held = useRef<Held | null>(null);
  const given = keys.join("\n");
  const [mine, stand] = useStandIn<string[]>(given);
  const order = useMemo(() => (mine ? fit(mine, keys) : keys), [mine, given]); // eslint-disable-line react-hooks/exhaustive-deps
  // The row that was moved last, said to a screen reader where the page
  // has it once the page has answered.
  const moving = useRef<string | null>(null);
  useEffect(() => void saidAt(), []);
  useEffect(() => {
    const key = moving.current;
    if (mine !== null || key === null) return;
    moving.current = null;
    const at = keys.indexOf(key);
    if (at >= 0) say(t("row_moved", { n: at + 1, of: keys.length }));
  }, [mine, given]); // eslint-disable-line react-hooks/exhaustive-deps
  // The grip a row was moved by with the keyboard. A browser may take
  // the keyboard off it as the row changes places, when it is moved and
  // again when the page puts it back, and it is given the keyboard again
  // for as long as nothing else has it.
  const keyboard = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const grip = keyboard.current;
    if (!grip) return;
    const nowhere = document.activeElement === null || document.activeElement === document.body;
    if (grip.isConnected && nowhere) grip.focus();
    if (mine === null) keyboard.current = null;
  });

  const place = () => {
    const d = held.current;
    if (!d) return;
    const at = carry(d.spans, d.from, d.y - d.y0 + (d.scroller.scrollTop - d.scroll0));
    d.to = at.to;
    d.low = Math.min(d.low, at.to);
    d.high = Math.max(d.high, at.to);
    const height = d.spans[d.from].height + d.gap;
    for (let i = d.low; i <= d.high; i++) {
      const el = d.els[i];
      const shift = i === d.from ? at.by : shiftOf(i, d.from, at.to, height);
      if (i !== d.from && !d.touched.has(el)) {
        d.touched.add(el);
        el.style.transition = "transform 140ms ease";
      }
      el.style.transform = shift ? `translateY(${shift}px)` : "";
    }
  };

  const scroll = () => {
    const d = held.current;
    if (!d) return;
    const box = d.scroller === document.scrollingElement ? { top: 0, bottom: window.innerHeight } : d.scroller.getBoundingClientRect();
    const by = scrollBy(d.y, box.top + (inset?.top ?? 0), box.bottom - (inset?.bottom ?? 0));
    if (by) {
      d.scroller.scrollTop += by;
      place();
    }
    d.frame = requestAnimationFrame(scroll);
  };

  // The row is let go. Its transform and those of the rows it passed go in
  // one step, with the rows drawn in their new order right after.
  const end = (drop: boolean) => {
    const d = held.current;
    if (!d) return;
    held.current = null;
    cancelAnimationFrame(d.frame);
    const own = d.els[d.from];
    own.style.transform = "";
    own.removeAttribute("data-mw-dragged");
    for (const el of d.touched) {
      el.style.transition = "none";
      el.style.transform = "";
    }
    requestAnimationFrame(() => d.touched.forEach((el) => (el.style.transition = "")));
    if (drop && d.to !== d.from) go(d.order, d.key, d.from, d.to);
  };

  const go = (from: string[], key: string, at: number, to: number) => {
    moving.current = key;
    stand(moved(from, at, to), onMove(key, to));
  };

  // The rows changed under a row that is held, or the page put them back
  // in the order they had: the row is let go where it was. What it was
  // measured against is no longer what is drawn.
  const drawnAs = mine ? order.join("\n") : given;
  useEffect(() => () => end(false), [drawnAs]); // eslint-disable-line react-hooks/exhaustive-deps

  const down = (key: string, e: PointerEvent<HTMLButtonElement>) => {
    const parent = list.current;
    if (disabled || e.button !== 0 || !parent || held.current) return;
    const els = Array.from(parent.children).filter((el): el is HTMLElement => el instanceof HTMLElement && el.dataset.mwRow !== undefined);
    const from = els.findIndex((el) => el.dataset.mwRow === key);
    if (from < 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const scroller = scrollerOf(parent);
    const spans = els.map((el) => {
      const r = el.getBoundingClientRect();
      return { top: r.top, height: r.height };
    });
    held.current = {
      key,
      from,
      to: from,
      low: from,
      high: from,
      touched: new Set(),
      els,
      spans,
      gap: spans.length > 1 ? Math.max(0, spans[1].top - (spans[0].top + spans[0].height)) : 0,
      order,
      y0: e.clientY,
      y: e.clientY,
      scroller,
      scroll0: scroller.scrollTop,
      frame: requestAnimationFrame(scroll),
    };
    els[from].setAttribute("data-mw-dragged", "");
  };

  const keyed = (key: string, e: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled || held.current || !e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    const at = order.indexOf(key);
    const to = at + (e.key === "ArrowUp" ? -1 : 1);
    if (at < 0 || to < 0 || to >= order.length) return;
    keyboard.current = e.currentTarget;
    go(order, key, at, to);
  };

  // What the grips call, as it is at this drawing. The grips themselves
  // are made once a key and stay the same objects, so a row that gets its
  // grip as a prop is not drawn again for it.
  const now = { down, keyed, place, end, disabled };
  const live = useRef(now);
  live.current = now;
  const grips = useRef(new Map<string, Grip>());
  const ables = useRef(disabled);
  if (ables.current !== disabled) {
    ables.current = disabled;
    grips.current.clear();
  }
  const grip = useCallback((key: string): Grip => {
    let made = grips.current.get(key);
    if (!made) {
      made = {
        "aria-keyshortcuts": "Alt+ArrowUp Alt+ArrowDown",
        style: HELD_BY_A_FINGER,
        disabled: live.current.disabled || undefined,
        onPointerDown: (e) => live.current.down(key, e),
        onPointerMove: (e) => {
          if (!held.current) return;
          held.current.y = e.clientY;
          live.current.place();
        },
        onPointerUp: (e) => {
          if (!held.current) return;
          held.current.y = e.clientY;
          live.current.place();
          e.currentTarget.releasePointerCapture(e.pointerId);
          live.current.end(true);
        },
        onPointerCancel: () => live.current.end(false),
        onLostPointerCapture: () => live.current.end(false),
        onKeyDown: (e) => live.current.keyed(key, e),
      };
      grips.current.set(key, made);
    }
    return made;
  }, []);

  const marks = useRef(new Map<string, { "data-mw-row": string }>());
  const row = useCallback((key: string) => {
    let made = marks.current.get(key);
    if (!made) {
      made = { "data-mw-row": key };
      marks.current.set(key, made);
    }
    return made;
  }, []);
  return { list: list as RefObject<never>, order, row, grip };
}

// The grip a row is dragged by, as millwork draws one. It takes what
// `grip(key)` gives, and `label` says to a screen reader which row it moves.
export function RowGrip({ label, className, ...grip }: Grip & { label?: string; className?: string }) {
  return (
    <button type="button" aria-label={label ?? t("move_row")} {...grip} className={cn("mw-row-grip", className)}>
      <GripVerticalIcon className="size-4" />
    </button>
  );
}

export interface EditableProps {
  value: string | number;
  // The text was changed. Called once, with the text as typed, its ends
  // trimmed. What it returns is waited for when it is a promise.
  onCommit: (text: string) => unknown;
  // What a screen reader calls it.
  label?: string;
  // What stands there, fainter, while the text is empty.
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

// A text that is typed over where it stands. Pressed, it is a field of the
// same size. Enter, or leaving the field, says the new text once, and
// Escape leaves the text as it was. What was typed shows, a little
// fainter, until the page has answered.
export function Editable({ value, onCommit, label, placeholder, disabled = false, className }: EditableProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const [mine, stand] = useStandIn<string>(value);
  const button = useRef<HTMLButtonElement>(null);
  // Closed from the keyboard, the keyboard stays on it.
  const refocus = useRef(false);
  // A field that is closed by a key leaves the page, which a browser may
  // tell it as losing the keyboard. It is closed once.
  const closed = useRef(true);
  useEffect(() => {
    if (draft === null && refocus.current) {
      refocus.current = false;
      button.current?.focus();
    }
  }, [draft]);
  const shown = mine ?? String(value);
  if (draft === null) {
    return (
      <button
        ref={button}
        type="button"
        disabled={disabled}
        aria-label={label ? `${label}: ${shown}` : undefined}
        onClick={() => {
          closed.current = false;
          setDraft(shown);
        }}
        className={cn("mw-editable", (mine !== null || shown === "") && "mw-editable-sent", className)}
      >
        {shown === "" ? placeholder : shown}
      </button>
    );
  }
  const close = (keep: boolean, byKey: boolean) => {
    if (closed.current) return;
    closed.current = true;
    const next = draft.trim();
    refocus.current = byKey;
    setDraft(null);
    if (keep && next !== shown) stand(next, onCommit(next));
  };
  return (
    <input
      autoFocus
      aria-label={label ?? placeholder}
      placeholder={placeholder}
      value={draft}
      onFocus={(e) => e.currentTarget.select()}
      onChange={(e) => setDraft(e.currentTarget.value)}
      onBlur={() => close(true, false)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          close(true, true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          close(false, true);
        }
      }}
      className={cn("mw-editable mw-editable-field", className)}
    />
  );
}
