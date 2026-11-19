// The Sortable: rows a person drags into another order, or into another
// list of the same group.
//
// A drag is the tab's own until the row is dropped. The row that is held
// is taken out of its list and a copy of it follows the pointer, and a gap
// opens where it would land, in whichever list of its group the pointer is
// over. Dropped, the copy settles in the gap and the list it was dropped in
// tells the session. The session moves the row in its state, and the page
// it draws from that is where the row is: the copy stands in until then,
// and a session that left the row where it was gets it back there.
//
// With the keyboard a row moves one place at a time, with Alt and an arrow,
// and each step is told at once. Past the end of a list it goes into the
// next list of the group.

import { Children, useEffect, useId, useRef, useSyncExternalStore, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { GripVerticalIcon } from "lucide-react";
import { cn } from "cn";
import type { Renderer } from "../render";
import { store } from "../store";
import { emit as tell } from "../ws";
import { t } from "../theme";
import { gapClass } from "./layout";
import { placeAt, scrollBy } from "./drag-rows";

// ------------------------------------------------------------- the drag

interface Drag {
  // The lists the row may be dropped in besides its own: those of this group.
  group: string | null;
  row: string;
  source: string;
  // The row's place in its own list, the others counted.
  from: number;
  // The room the row takes, which is the room the gap gives.
  height: number;
  // The list the row is over and its place there, or no list.
  over: string | null;
  at: number;
  // Dropped: the copy stands in until the page says where the row is.
  settled: boolean;
}

// One drag at a time, on the whole page. Every list draws from it.
let drag: Drag | null = null;
const listeners = new Set<() => void>();
function setDrag(next: Drag | null) {
  drag = next;
  for (const listener of listeners) listener();
}
function useDrag(): Drag | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => drag,
    () => drag,
  );
}

// The row to give the keyboard to once the page has it where it was moved,
// and whether to say where that is, which is for a move by the keyboard.
let refocus: { row: string; say: boolean } | null = null;

// A press that may become a drag is under way. One at a time: a second
// finger on another row would otherwise carry the first one's row.
let pressing = false;

// The rows of a list as the page has them, to tell whether they changed.
// The store hands out a new array with each change to the list, of its
// label say, so the ids are what is held against each other.
const rowsNow = (id: string) => (store.snapshot(id)?.children ?? []).join("\n");

const listOf = (id: string) => document.querySelector<HTMLElement>(`[data-sortable="${CSS.escape(id)}"]`);
const rowsOf = (list: HTMLElement) => Array.from(list.querySelectorAll<HTMLElement>(":scope > [data-sortable-row]"));

// The lists a row of `source` may be dropped in: its own, and those of
// its group that take rows. A list inside the row itself is none of them.
function listsFor(source: string, group: string | null, row: string): HTMLElement[] {
  const all = Array.from(document.querySelectorAll<HTMLElement>("[data-sortable]"));
  return all.filter((list) => {
    if (list.dataset.sortable === source) return true;
    if (list.dataset.sortable!.startsWith(`${row}/`)) return false;
    return group !== null && list.dataset.group === group && list.dataset.takes !== "false" && list.dataset.disabled !== "true";
  });
}

// What scrolls under a point: the nearest thing above it that has more
// than it shows, or the window.
function scrollerAt(x: number, y: number): Element {
  for (let up = document.elementFromPoint(x, y); up && up !== document.body; up = up.parentElement) {
    const flow = getComputedStyle(up).overflowY;
    if ((flow === "auto" || flow === "scroll") && up.scrollHeight > up.clientHeight) return up;
  }
  return document.scrollingElement ?? document.documentElement;
}

// A press that is for what it landed on, in a row that is dragged by all
// of it: a button in the row, a field.
const PRESSED = "button, a, input, textarea, select, label, [role=button], [role=combobox], [contenteditable=true]";

// A press on a row's grip, or on a row that is dragged by all of it. With
// a finger on such a row, which is also how the page under it is scrolled,
// the row is held by resting the finger on it for a moment.
const HOLD = 300;

function begin(e: ReactPointerEvent<HTMLElement>, list: string, group: string | null, row: string, byAll: boolean) {
  if (e.button !== 0 || drag || pressing) return;
  const rowEl = (e.currentTarget as HTMLElement).closest<HTMLElement>("[data-sortable-row]");
  if (!rowEl) return;
  pressing = true;
  const pointer = e.pointerId;
  const startX = e.clientX;
  const startY = e.clientY;
  let x = startX;
  let y = startY;
  let copy: HTMLElement | null = null;
  let offX = 0;
  let offY = 0;
  let frame = 0;
  let hold = 0;
  const resting = byAll && e.pointerType === "touch";
  let stopWatching = () => {};

  // Where the row would land for a pointer at (x, y), put in the drag.
  const place = () => {
    const d = drag;
    if (!d || d.settled) return;
    // The list the pointer is over, the innermost of them. Above or below
    // every list it is the nearest one in that column, so a row can be let
    // go under the last row of a short list, where the list itself has
    // ended. Beside every list it is none, and the row goes back.
    let over: HTMLElement | null = null;
    let off = Infinity;
    for (const candidate of listsFor(d.source, d.group, d.row)) {
      const box = candidate.getBoundingClientRect();
      if (x < box.left - 8 || x > box.right + 8) continue;
      const away = y < box.top ? box.top - y : y > box.bottom ? y - box.bottom : 0;
      if (away < off || away === 0) {
        over = candidate;
        off = away;
      }
    }
    if (!over) {
      if (d.over !== null) setDrag({ ...d, over: null });
      return;
    }
    const id = over.dataset.sortable!;
    let at: number;
    if (id === d.source && over.dataset.reorder === "false") {
      // The rows keep their order, so back in its own list is back in its place.
      at = d.from;
    } else {
      const rows = rowsOf(over).filter((r) => r.dataset.sortableRow !== d.row);
      const spans = rows.map((r) => {
        const box = r.getBoundingClientRect();
        return { top: box.top, height: box.height };
      });
      const between = parseFloat(getComputedStyle(over).rowGap) || 0;
      at = placeAt(spans, y - offY + d.height / 2, d.height, between, d.over === id ? d.at : null);
    }
    if (d.over !== id || d.at !== at) setDrag({ ...d, over: id, at });
  };

  const follow = () => {
    if (copy) copy.style.transform = `translate(${x - offX}px, ${y - offY}px)`;
  };

  // While the pointer is near an edge of what scrolls, that scrolls.
  const scroll = () => {
    frame = 0;
    if (!drag || drag.settled) return;
    const scroller = scrollerAt(x, y);
    const whole = scroller === (document.scrollingElement ?? document.documentElement);
    const box = whole ? { top: 0, bottom: window.innerHeight } : scroller.getBoundingClientRect();
    const by = scrollBy(y, box.top, box.bottom);
    if (by) {
      const before = scroller.scrollTop;
      scroller.scrollTop += by;
      if (scroller.scrollTop !== before) place();
    }
    frame = requestAnimationFrame(scroll);
  };

  const lift = () => {
    const box = rowEl.getBoundingClientRect();
    offX = startX - box.left;
    offY = startY - box.top;
    copy = document.createElement("div");
    copy.className = "mw-sortable-copy";
    copy.setAttribute("aria-hidden", "true");
    copy.style.width = `${box.width}px`;
    copy.style.height = `${box.height}px`;
    const inner = rowEl.cloneNode(true) as HTMLElement;
    // A copy to look at: nothing in it is found by its id or its node.
    for (const el of [inner, ...Array.from(inner.querySelectorAll<HTMLElement>("[id], [data-node], [data-sortable], [data-sortable-row]"))]) {
      el.removeAttribute("id");
      el.removeAttribute("data-node");
      el.removeAttribute("data-sortable");
      el.removeAttribute("data-sortable-row");
    }
    copy.appendChild(inner);
    document.body.appendChild(copy);
    document.body.classList.add("mw-dragging");
    const rows = rowsOf(listOf(list)!);
    const from = rows.findIndex((r) => r.dataset.sortableRow === row);
    setDrag({ group, row, source: list, from, height: box.height, over: list, at: from, settled: false });
    follow();
    // A page that changes the rows of the list while one is held has
    // another list than the one the drag began in, so the drag ends.
    const rowsThen = rowsNow(list);
    stopWatching = store.subscribe(list, () => {
      if (rowsNow(list) !== rowsThen && drag && !drag.settled) end();
    });
    frame = requestAnimationFrame(scroll);
  };

  const stop = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onCancel);
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("touchmove", noScroll);
    window.removeEventListener("blur", onBlur);
    window.clearTimeout(hold);
    pressing = false;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    stopWatching();
    document.body.classList.remove("mw-dragging");
  };

  // The drag is over, and the row shows where the page has it. The copy
  // goes at once when the row is where it was dropped. A row that is
  // still where it was held, let go beside every list or left there by
  // the session, has the copy go back to it first.
  const end = (back = false) => {
    stop();
    const was = copy;
    copy = null;
    if (drag) setDrag(null);
    if (!was) return;
    const home = back ? document.querySelector<HTMLElement>(`[data-sortable-row="${CSS.escape(row)}"]`) : null;
    if (!home) {
      was.remove();
      return;
    }
    // The row shows again as the drag ends, which is by the next frame.
    requestAnimationFrame(() => {
      // The keyboard was on the grip, which was out of sight with its row.
      (home.querySelector<HTMLElement>("[data-sortable-grip]") ?? home).focus({ preventScroll: true });
      const box = home.getBoundingClientRect();
      was.classList.add("mw-sortable-settled");
      was.style.transform = `translate(${box.left}px, ${box.top}px)`;
      window.setTimeout(() => was.remove(), 140);
    });
  };

  const drop = () => {
    const d = drag;
    if (!d || d.over === null || (d.over === d.source && d.at === d.from)) {
      end(true);
      return;
    }
    stop();
    setDrag({ ...d, settled: true });
    // The copy settles in the gap, and stays until the page has the row.
    const gap = listOf(d.over)?.querySelector<HTMLElement>(":scope > [data-sortable-gap]");
    if (copy && gap) {
      const box = gap.getBoundingClientRect();
      copy.classList.add("mw-sortable-settled");
      copy.style.transform = `translate(${box.left}px, ${box.top}px)`;
    }
    const over = d.over;
    tell(over, "move", { key: d.row, source: d.source, to: d.at });
    // The keyboard goes with the row, to where the page puts it.
    refocus = { row: `${over}/${d.row.slice(d.source.length + 1)}`, say: false };
    const was = { source: rowsNow(d.source), over: rowsNow(over) };
    const changed = () => rowsNow(d.source) !== was.source || rowsNow(over) !== was.over;
    let waited = 0;
    const finish = (back: boolean) => {
      window.clearTimeout(waited);
      window.removeEventListener("mw:moved", heard);
      stopSource();
      stopOver();
      end(back);
    };
    // The page has the rows in another order: the row is where it is.
    const answered = () => {
      if (changed()) finish(false);
    };
    // The session is done with the move, and has drawn the page. Rows
    // that are as they were mean the row was left where it was.
    const heard = (ev: Event) => {
      if ((ev as CustomEvent<{ node: string }>).detail.node === over) finish(!changed());
    };
    const stopSource = store.subscribe(d.source, answered);
    const stopOver = store.subscribe(over, answered);
    window.addEventListener("mw:moved", heard);
    // The session says when it is done with a move, taken or not. This is
    // for a session that says nothing, with its connection gone.
    waited = window.setTimeout(() => finish(true), 8000);
  };

  // A held row is the finger's to carry, and the page under it stays put.
  const noScroll = (ev: TouchEvent) => {
    if (drag) ev.preventDefault();
  };
  const onMove = (ev: PointerEvent) => {
    if (ev.pointerId !== pointer) return;
    if (ev.pointerType === "mouse" && ev.buttons === 0) {
      // The button came up where this window did not see it.
      if (!drag?.settled) end(true);
      return;
    }
    x = ev.clientX;
    y = ev.clientY;
    if (!drag) {
      const far = Math.hypot(x - startX, y - startY);
      if (resting) {
        // A finger that moves before the row is held is scrolling the page.
        if (far > 8) end();
        return;
      }
      // A press that hardly moves is a press, and no drag.
      if (far < 6) return;
      lift();
    }
    if (drag?.settled) return;
    follow();
    place();
  };
  const onUp = (ev: PointerEvent) => {
    if (ev.pointerId !== pointer) return;
    if (!drag) end();
    else if (!drag.settled) drop();
  };
  const onCancel = (ev: PointerEvent) => {
    if (ev.pointerId === pointer && !drag?.settled) end(true);
  };
  // The window is left with a row held, for another one say.
  const onBlur = () => {
    if (!drag?.settled) end(true);
  };
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key !== "Escape" || !drag || drag.settled) return;
    // The key puts the row back, and is for nothing else on the page.
    ev.preventDefault();
    ev.stopPropagation();
    end(true);
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onCancel);
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("blur", onBlur);
  if (resting) {
    window.addEventListener("touchmove", noScroll, { passive: false });
    hold = window.setTimeout(() => {
      if (!drag) lift();
    }, HOLD);
  }
}

// One place up or down with the keyboard, told at once. Past the end of
// the list the row goes into the next list of the group that takes rows.
function step(list: string, group: string | null, reorder: boolean, row: string, by: -1 | 1) {
  const here = listOf(list);
  if (!here) return;
  const rows = rowsOf(here);
  const at = rows.findIndex((r) => r.dataset.sortableRow === row);
  const key = row.slice(list.length + 1);
  if (at + by >= 0 && at + by < rows.length) {
    if (!reorder) return;
    refocus = { row, say: true };
    tell(list, "move", { key: row, source: list, to: at + by });
    return;
  }
  if (group === null) return;
  const lists = listsFor(list, group, row);
  const next = lists[lists.findIndex((l) => l.dataset.sortable === list) + by];
  if (!next) return;
  const target = next.dataset.sortable!;
  refocus = { row: `${target}/${key}`, say: true };
  tell(target, "move", { key: row, source: list, to: by < 0 ? rowsOf(next).length : 0 });
}

// ------------------------------------------------------------- the list

export const Sortable: Renderer = ({ node, props, children }) => {
  const d = useDrag();
  const group = typeof props.group === "string" ? props.group : null;
  const disabled = Boolean(props.disabled);
  // A list with no handler has nobody to tell of a row dropped in it, so
  // it takes none and its rows keep their order. They may still leave.
  const heard = Boolean(props.on_move);
  const reorder = heard && props.reorder !== false;
  const takes = heard && props.takes !== false;
  const handle = props.handle !== false;
  const ids = node.children;
  const rows = Children.toArray(children);
  // A row can be held when it has somewhere to go.
  const movable = !disabled && (reorder || group !== null);
  const said = useRef<HTMLSpanElement>(null);
  const name = useId();

  // The keyboard goes with the row it moved, to where the page has it now.
  useEffect(() => {
    if (!refocus || !ids.includes(refocus.row)) return;
    const { row, say } = refocus;
    refocus = null;
    const el = document.querySelector<HTMLElement>(`[data-sortable-row="${CSS.escape(row)}"]`);
    (el?.querySelector<HTMLElement>("[data-sortable-grip]") ?? el)?.focus({ preventScroll: !say });
    if (say && said.current) {
      const words = { n: ids.indexOf(row) + 1, of: ids.length, list: String(props.label ?? "") };
      said.current.textContent = props.label ? t("row_moved_in", words) : t("row_moved", words);
    }
  }, [ids, props.label]);

  const here = d !== null && d.over === node.id;
  const gap = here ? <div key="mw-gap" role="none" aria-hidden="true" data-sortable-gap="" className="mw-sortable-gap" style={{ height: d.height }} /> : null;
  const shown: ReactNode[] = [];
  let others = 0;
  ids.forEach((id, i) => {
    const held = d !== null && d.row === id && d.source === node.id;
    if (here && !held && others === d.at) shown.push(gap);
    if (!held) others += 1;
    const keys = (e: ReactKeyboardEvent<HTMLElement>) => {
      if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown") || e.target !== e.currentTarget) return;
      e.preventDefault();
      step(node.id, group, reorder, id, e.key === "ArrowUp" ? -1 : 1);
    };
    const press = (e: ReactPointerEvent<HTMLElement>) => {
      // A press in a list inside this row is that list's.
      if ((e.target as HTMLElement).closest("[data-sortable]")?.getAttribute("data-sortable") !== node.id) return;
      if (!handle && (e.target as HTMLElement).closest(PRESSED)) return;
      begin(e, node.id, group, id, !handle);
    };
    const gripped = movable && handle;
    shown.push(
      <div
        key={id}
        role="listitem"
        data-sortable-row={id}
        className={cn("mw-sortable-row", gripped && "mw-sortable-gripped", held && "hidden", movable && !handle && "cursor-grab select-none")}
        {...(movable && !handle ? { tabIndex: 0, onPointerDown: press, onKeyDown: keys, "aria-keyshortcuts": "Alt+ArrowUp Alt+ArrowDown" } : {})}
      >
        {gripped ? (
          <button
            type="button"
            data-sortable-grip=""
            aria-label={t("move_row")}
            aria-describedby={`${name}-${i}`}
            aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
            className="mw-sortable-grip"
            onPointerDown={press}
            onKeyDown={keys}
          >
            <GripVerticalIcon className="size-4" />
          </button>
        ) : null}
        <div id={`${name}-${i}`} className="mw-sortable-held">
          {rows[i]}
        </div>
      </div>,
    );
  });
  if (here && others <= d.at) shown.push(gap);
  const none = others === 0 && !here;

  return (
    <>
      <div
        role="list"
        aria-label={props.label ? String(props.label) : undefined}
        data-sortable={node.id}
        data-group={group ?? undefined}
        data-takes={takes ? undefined : "false"}
        data-reorder={reorder ? undefined : "false"}
        data-disabled={disabled ? "true" : undefined}
        className={cn("mw-sortable flex flex-col", gapClass(props.gap ?? 2), props.cls as string)}
      >
        {shown}
        {none ? (
          <div role="listitem" className="mw-sortable-empty">
            {props.empty ? String(props.empty) : null}
          </div>
        ) : null}
      </div>
      <span ref={said} aria-live="polite" className="sr-only" />
    </>
  );
};
