// Chips that can be dragged into order. The dragged chip leaves a faint
// placeholder in the row and a copy rides under the pointer; the others
// slide out of its way as the pointer passes their centres. Alt with the
// arrow keys moves a focused chip one step. The new order is committed when
// the pointer lifts, or at once for a key move.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "cn";
import { icon } from "../icons";
import { moved, slotAt } from "../sortable";
import { ComboboxChip } from "@/components/ui/combobox";

const THRESHOLD = 4;
const CHIP = "[data-slot=combobox-chip]";
const BOX = "[data-slot=combobox-chips]";
// While a chip is in the air the whole page shows a grabbing hand and
// selects nothing (the rule is in index.css).
const DRAGGING = "mw-dragging";
// A committed order the owner never echoed is dropped after this long.
const ECHO_MS = 500;

// A press on the chips box focuses the input and opens the list; a press on
// a sortable chip is a grab, or a click that focuses the chip itself, so it
// stops here.
const stopHere = (e: React.MouseEvent) => e.stopPropagation();

export interface Chip {
  value: string;
  label: string;
}

interface Drag {
  value: string;
  width: number;
  dx: number;
  dy: number;
  x: number;
  y: number;
}

// A move the owner has been asked for: the slide and the focus wait for the
// chips to come back in that order, and are forgotten if they do not.
interface Pending {
  order: string[];
  focus: string | null;
  before: Map<string, DOMRect>;
}

// Positions taken before a reorder, so each chip can start its slide from
// where it stood, even mid-slide.
function snapshot(container: Element): Map<string, DOMRect> {
  const out = new Map<string, DOMRect>();
  for (const el of Array.from(container.querySelectorAll<HTMLElement>(CHIP))) {
    if (el.dataset.value !== undefined) out.set(el.dataset.value, el.getBoundingClientRect());
  }
  return out;
}

function slide(container: Element, before: Map<string, DOMRect>) {
  for (const el of Array.from(container.querySelectorAll<HTMLElement>(CHIP))) {
    const was = el.dataset.value === undefined ? undefined : before.get(el.dataset.value);
    el.style.transition = "none";
    el.style.transform = "";
    if (!was) continue;
    const now = el.getBoundingClientRect();
    const dx = was.left - now.left;
    const dy = was.top - now.top;
    if (!dx && !dy) continue;
    el.style.transform = `translate(${dx}px, ${dy}px)`;
    void el.offsetWidth;
    el.style.transition = "transform 160ms cubic-bezier(0.2, 0, 0, 1)";
    el.style.transform = "";
  }
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((v, i) => v === b[i]);

// An order kept across changes of the chips themselves: values that left
// are dropped, values that arrived go at the end.
function reconcile(order: string[], chips: Chip[]): string[] {
  const have = new Set(chips.map((c) => c.value));
  const kept = order.filter((v) => have.has(v));
  const seen = new Set(kept);
  return [...kept, ...chips.map((c) => c.value).filter((v) => !seen.has(v))];
}

export function SortableChips({
  chips,
  onReorder,
  disabled,
}: {
  chips: Chip[];
  onReorder: (values: string[]) => void;
  disabled?: boolean;
}) {
  const [order, setOrder] = useState<string[] | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [said, setSaid] = useState("");
  const overlay = useRef<HTMLDivElement>(null);
  const before = useRef<Map<string, DOMRect> | null>(null);
  const pending = useRef<Pending | null>(null);
  const chipsRef = useRef(chips);
  chipsRef.current = chips;
  const box = useRef<HTMLElement | null>(null);
  const endDrag = useRef<(() => void) | null>(null);
  const Grip = icon("grip-vertical");

  const values = chips.map((c) => c.value);
  const shown = order
    ? reconcile(order, chips).map((v) => chips.find((c) => c.value === v) ?? { value: v, label: v })
    : chips;

  // A reorder in the air slides from the snapshot taken just before it.
  useLayoutEffect(() => {
    if (before.current && box.current) slide(box.current, before.current);
    before.current = null;
  }, [order]);

  // The chips came back from the owner: a committed order shows as is, a
  // pending key move slides and keeps its focus, and anything stale is
  // forgotten. Without an echo the committed order is dropped after a beat.
  useLayoutEffect(() => {
    const p = pending.current;
    pending.current = null;
    if (order && !drag) setOrder(null);
    const el = box.current;
    if (!p || !el || !same(values, p.order)) return;
    slide(el, p.before);
    if (p.focus !== null) el.querySelector<HTMLElement>(`${CHIP}[data-value="${CSS.escape(p.focus)}"]`)?.focus();
    // The chips prop is what this effect follows; `order`, `drag` and
    // `values` are read, not followed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chips]);

  useEffect(() => {
    if (!order || drag) return;
    const t = window.setTimeout(() => {
      pending.current = null;
      setOrder(null);
    }, ECHO_MS);
    return () => window.clearTimeout(t);
  }, [order, drag]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (disabled || e.button !== 0 || endDrag.current) return;
      if ((e.target as Element).closest("[data-slot=combobox-chip-remove]")) return;
      const el = e.currentTarget;
      const value = el.dataset.value;
      const chipsBox = el.closest<HTMLElement>(BOX);
      if (value === undefined || !chipsBox) return;
      box.current = chipsBox;
      const id = e.pointerId;
      const rect = el.getBoundingClientRect();
      const start = { x: e.clientX, y: e.clientY };
      let live: string[] = chipsRef.current.map((c) => c.value);
      let active = false;

      const stop = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        chipsBox.removeEventListener("lostpointercapture", onLost);
        endDrag.current = null;
        if (!active) return;
        document.body.classList.remove(DRAGGING);
        if (chipsBox.hasPointerCapture(id)) chipsBox.releasePointerCapture(id);
      };
      const onMove = (ev: PointerEvent) => {
        if (ev.pointerId !== id) return;
        if (!active) {
          if (Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < THRESHOLD) return;
          active = true;
          document.body.classList.add(DRAGGING);
          // The box holds the capture: unlike the chip it never leaves the
          // DOM while the order changes, and a lift over an iframe or
          // outside the window still reaches it.
          try {
            chipsBox.setPointerCapture(id);
          } catch {
            // an inactive pointer: the lift will come through the window
          }
          setDrag({ value, width: rect.width, dx: start.x - rect.left, dy: start.y - rect.top, x: ev.clientX, y: ev.clientY });
          setOrder(live);
        }
        ev.preventDefault();
        if (overlay.current) {
          overlay.current.style.left = `${ev.clientX - (start.x - rect.left)}px`;
          overlay.current.style.top = `${ev.clientY - (start.y - rect.top)}px`;
        }
        live = reconcile(live, chipsRef.current);
        const others: DOMRect[] = [];
        for (const chip of Array.from(chipsBox.querySelectorAll<HTMLElement>(CHIP))) {
          if (chip.dataset.value !== value) others.push(chip.getBoundingClientRect());
        }
        const from = live.indexOf(value);
        const to = slotAt(others, ev.clientX, ev.clientY);
        if (from >= 0 && to !== from) {
          before.current = snapshot(chipsBox);
          live = moved(live, from, to);
          setOrder(live);
        }
      };
      const onUp = (ev: PointerEvent) => {
        if (ev.pointerId !== id) return;
        const was = active;
        stop();
        if (!was) return;
        // The lift lands on the chips box, which would open the list.
        const swallow = (ce: Event) => {
          ce.stopPropagation();
          ce.preventDefault();
        };
        window.addEventListener("click", swallow, { capture: true });
        window.setTimeout(() => window.removeEventListener("click", swallow, { capture: true }), 0);
        setDrag(null);
        const final = reconcile(live, chipsRef.current);
        if (same(final, chipsRef.current.map((c) => c.value))) {
          setOrder(null);
          return;
        }
        // The order stays on screen until the owner echoes it.
        setOrder(final);
        pending.current = { order: final, focus: null, before: new Map() };
        onReorder(final);
      };
      const onLost = (ev: PointerEvent) => {
        if (ev.pointerId === id && active) onUp(ev);
      };
      endDrag.current = () => {
        stop();
        setDrag(null);
        setOrder(null);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      chipsBox.addEventListener("lostpointercapture", onLost);
    },
    [disabled, onReorder],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement> & { preventBaseUIHandler?: () => void }) => {
      if (endDrag.current) {
        // No edits from the keyboard while a chip is in the air.
        e.preventDefault();
        e.preventBaseUIHandler?.();
        return;
      }
      if (disabled || !e.altKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
      const value = e.currentTarget.dataset.value;
      if (value === undefined) return;
      const current = chipsRef.current;
      const vals = current.map((c) => c.value);
      const from = vals.indexOf(value);
      const to = e.key === "ArrowLeft" ? from - 1 : from + 1;
      if (from < 0 || to < 0 || to >= vals.length) return;
      e.preventDefault();
      e.preventBaseUIHandler?.();
      box.current = e.currentTarget.closest<HTMLElement>(BOX);
      const next = moved(vals, from, to);
      pending.current = { order: next, focus: value, before: box.current ? snapshot(box.current) : new Map() };
      setSaid(`${current[from].label}, ${to + 1} of ${vals.length}`);
      onReorder(next);
    },
    [disabled, onReorder],
  );

  // Unmounting mid-drag ends it without a commit.
  useEffect(() => () => endDrag.current?.(), []);

  return (
    <>
      {shown.map((c) => (
        <ComboboxChip
          key={c.value}
          data-value={c.value}
          aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight"
          onPointerDown={onPointerDown}
          onMouseDown={stopHere}
          onKeyDown={onKeyDown}
          className={cn("touch-none", !disabled && "cursor-grab", drag?.value === c.value && "opacity-30")}
        >
          {Grip ? <Grip className="-ml-0.5 size-3 shrink-0 text-muted-foreground" /> : null}
          {c.label}
        </ComboboxChip>
      ))}
      <span aria-live="polite" className="sr-only">
        {said}
      </span>
      {drag
        ? createPortal(
            <div
              ref={overlay}
              className="pointer-events-none fixed z-50 flex h-[calc(--spacing(5.25))] items-center gap-1 rounded-sm bg-muted px-1.5 text-xs font-medium whitespace-nowrap text-foreground shadow-lg ring-1 ring-border"
              style={{ left: drag.x - drag.dx, top: drag.y - drag.dy, width: drag.width }}
            >
              {Grip ? <Grip className="-ml-0.5 size-3 shrink-0 text-muted-foreground" /> : null}
              {shown.find((c) => c.value === drag.value)?.label}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
