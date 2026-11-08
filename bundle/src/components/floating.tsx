// Things that float over the page: a button pinned in a corner, and a window
// that is dragged by a handle and resized from its edges. Both remember where
// the reader put them, per node, and both stay inside the browser window as
// it changes size. `Floating` is the plain container; the Assistant's button
// and window use the same hooks.

import { useCallback, useEffect, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { cn } from "cn";
import type { Renderer } from "../render";
import {
  clampPosition,
  clampRect,
  cursorFor,
  edgesAt,
  fitSize,
  hasEdge,
  isClick,
  resizeRect,
  restingPlace,
  type Edges,
  type Point,
  type Rect,
  type Size,
} from "../assistant-math";

export function viewport(): Size {
  return { width: window.innerWidth, height: window.innerHeight };
}

function read<T>(key: string, check: (v: unknown) => v is T): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const v: unknown = JSON.parse(raw);
    return check(v) ? v : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage may be unavailable; the thing then starts in its corner next time
  }
}

const isPoint = (v: unknown): v is Point =>
  typeof v === "object" && v !== null && typeof (v as Point).x === "number" && typeof (v as Point).y === "number";
const isRect = (v: unknown): v is Rect =>
  isPoint(v) && typeof (v as Rect).width === "number" && typeof (v as Rect).height === "number";

type Drag = { from: Point; origin: Point; moved: boolean };

// A press is a drag once it has moved more than a few pixels; the click that
// ends a drag is swallowed before it reaches anything.
function useDrag<T extends HTMLElement>(enabled: boolean, origin: () => Point, move: (to: Point) => void, done: () => void, onPress?: () => void) {
  const drag = useRef<Drag | null>(null);
  const dragged = useRef(false);
  const onPointerDown = (e: ReactPointerEvent<T>) => {
    if (!enabled || e.button !== 0) return;
    // A press on a control inside is that control's, not a drag: taking the
    // pointer here would take its click as well.
    const control = (e.target as Element).closest("button, a, input, textarea, select, [role=button], [contenteditable]");
    if (control && control !== e.currentTarget) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { from: { x: e.clientX, y: e.clientY }, origin: origin(), moved: false };
  };
  const onPointerMove = (e: ReactPointerEvent<T>) => {
    const d = drag.current;
    if (!d) return;
    const now = { x: e.clientX, y: e.clientY };
    if (!d.moved && isClick(d.from, now)) return;
    d.moved = true;
    move({ x: d.origin.x + now.x - d.from.x, y: d.origin.y + now.y - d.from.y });
  };
  const onPointerUp = (e: ReactPointerEvent<T>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    if (!d.moved) return;
    // Only the click of this same gesture is swallowed: it comes right after
    // this event, or not at all when the pointer let go somewhere else.
    dragged.current = true;
    window.setTimeout(() => (dragged.current = false), 0);
    done();
  };
  const onClickCapture = (e: ReactMouseEvent<T>) => {
    if (!dragged.current) return;
    dragged.current = false;
    e.preventDefault();
    e.stopPropagation();
  };
  const onClick = () => onPress?.();
  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: () => (drag.current = null), onClickCapture, onClick };
}

export interface FloatingOptions {
  storageKey: string;
  side: "left" | "right";
  draggable: boolean;
  size: Size;
  onPress?: () => void;
}

// A thing of fixed size pinned in a corner until dragged.
export function useFloating<T extends HTMLElement>({ storageKey, side, draggable, size, onPress }: FloatingOptions) {
  const ref = useRef<T>(null);
  const [at, setAt] = useState<Point | null>(() => (draggable ? read(storageKey, isPoint) : null));

  const measured = useCallback((): Size => {
    const el = ref.current;
    return el ? { width: el.offsetWidth, height: el.offsetHeight } : size;
  }, [size]);

  const place = useCallback((): Rect => {
    const el = ref.current;
    if (el) {
      const r = el.getBoundingClientRect();
      return { x: r.left, y: r.top, width: r.width, height: r.height };
    }
    return { ...(at ?? restingPlace(side, size, viewport())), ...size };
  }, [at, side, size]);

  const moveTo = useCallback(
    (p: Point) => {
      const next = clampPosition(p, measured(), viewport());
      setAt(next);
      write(storageKey, next);
    },
    [measured, storageKey],
  );

  useEffect(() => {
    if (!at) return;
    const onResize = () => setAt((p) => (p ? clampPosition(p, measured(), viewport()) : p));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [at, measured]);

  const handlers = useDrag<T>(
    draggable,
    () => place(),
    (to) => setAt(clampPosition(to, measured(), viewport())),
    () => {
      const r = place();
      write(storageKey, { x: r.x, y: r.y });
    },
    onPress,
  );

  return {
    ref,
    place,
    moveTo,
    style: at ? ({ left: at.x, top: at.y } as CSSProperties) : undefined,
    corner: at ? undefined : side === "left" ? "bottom-6 left-6" : "right-6 bottom-6",
    handlers,
  };
}

export interface WindowOptions {
  storageKey: string;
  draggable: boolean;
  resizable: boolean;
  // The size the window has until the reader resizes it; null leaves it to its content.
  defaultSize: Size | null;
  // Where it goes when nothing is remembered yet.
  initial: (size: Size | null) => Point;
}

// A window: dragged by a handle, resized from any edge or corner, kept
// inside the browser window and shrunk to fit it, remembered as a whole.
export function useWindow<T extends HTMLElement>({ storageKey, draggable, resizable, defaultSize, initial }: WindowOptions) {
  const ref = useRef<T>(null);
  const [geometry, setGeometry] = useState<{ at: Point; size: Size | null } | null>(() => {
    const kept = read(storageKey, isRect);
    if (kept) return { at: { x: kept.x, y: kept.y }, size: { width: kept.width, height: kept.height } };
    const keptAt = read(storageKey, isPoint);
    return keptAt ? { at: keptAt, size: null } : null;
  });
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const resizing = useRef<{ edges: Edges; from: Rect; start: Point } | null>(null);

  const current = useCallback((): Rect => {
    const el = ref.current;
    if (el) {
      const r = el.getBoundingClientRect();
      return { x: r.left, y: r.top, width: r.width, height: r.height };
    }
    const size = geometry?.size ?? defaultSize ?? { width: 200, height: 48 };
    return { ...(geometry?.at ?? initial(size)), ...size };
  }, [geometry, defaultSize, initial]);

  const keep = useCallback(
    (rect: Rect, sized: boolean) => {
      setGeometry({ at: { x: rect.x, y: rect.y }, size: sized ? { width: rect.width, height: rect.height } : null });
      write(storageKey, sized ? rect : { x: rect.x, y: rect.y });
    },
    [storageKey],
  );

  // Opened for the first time, or shown again: a place, and the size it was given.
  const open = useCallback(() => {
    setGeometry((g) => {
      if (g) return g;
      const size = defaultSize ? fitSize(defaultSize, viewport()) : null;
      return { at: initial(size), size };
    });
  }, [defaultSize, initial]);

  useEffect(() => {
    if (!geometry) return;
    const onResize = () =>
      setGeometry((g) => {
        if (!g) return g;
        const size = g.size ?? (ref.current ? { width: ref.current.offsetWidth, height: ref.current.offsetHeight } : defaultSize ?? { width: 1, height: 1 });
        const next = clampRect({ ...g.at, ...size }, viewport());
        return { at: { x: next.x, y: next.y }, size: g.size ? { width: next.width, height: next.height } : null };
      });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [geometry, defaultSize]);

  const dragHandlers = useDrag<HTMLElement>(
    draggable,
    () => current(),
    // The first drag of a thing still in its corner gives it a place of its own.
    (to) => setGeometry((g) => ({ at: clampPosition(to, current(), viewport()), size: g?.size ?? null })),
    () => {
      const r = current();
      keep(r, geometry?.size !== null && geometry?.size !== undefined);
    },
  );

  // Resizing takes hold at the edges of the frame itself.
  const frameHandlers = {
    onPointerDown: (e: ReactPointerEvent<T>) => {
      if (!resizable || e.button !== 0) return;
      const edges = edgesAt({ x: e.clientX, y: e.clientY }, current());
      if (!hasEdge(edges)) return;
      e.preventDefault();
      e.stopPropagation();
      e.currentTarget.setPointerCapture(e.pointerId);
      resizing.current = { edges, from: current(), start: { x: e.clientX, y: e.clientY } };
    },
    onPointerMove: (e: ReactPointerEvent<T>) => {
      const r = resizing.current;
      if (r) {
        const next = resizeRect(r.from, r.edges, e.clientX - r.start.x, e.clientY - r.start.y, viewport());
        setGeometry({ at: { x: next.x, y: next.y }, size: { width: next.width, height: next.height } });
        return;
      }
      if (resizable) setCursor(cursorFor(edgesAt({ x: e.clientX, y: e.clientY }, current())));
    },
    onPointerUp: (e: ReactPointerEvent<T>) => {
      const r = resizing.current;
      if (!r) return;
      resizing.current = null;
      e.currentTarget.releasePointerCapture(e.pointerId);
      keep(current(), true);
    },
    onPointerLeave: () => {
      if (!resizing.current) setCursor(undefined);
    },
  };

  const style: CSSProperties | undefined = geometry
    ? { left: geometry.at.x, top: geometry.at.y, width: geometry.size?.width, height: geometry.size?.height, cursor }
    : cursor
      ? { cursor }
      : undefined;

  return { ref, geometry, current, open, style, dragHandlers, frameHandlers, placed: geometry !== null };
}

export const Floating: Renderer = ({ node, props, children }) => {
  const draggable = props.draggable === true;
  const resizable = props.resizable === true;
  const side = props.side === "left" ? "left" : "right";
  const win = useWindow<HTMLDivElement>({
    storageKey: `mw:floating:${node.id}`,
    draggable,
    resizable,
    defaultSize: null,
    initial: (size) => restingPlace(side, size ?? { width: 200, height: 48 }, viewport()),
  });
  return (
    <div
      ref={win.ref}
      style={win.style}
      {...win.frameHandlers}
      {...(draggable ? win.dragHandlers : {})}
      className={cn(
        "fixed z-40 print:hidden",
        draggable && "cursor-grab touch-none select-none active:cursor-grabbing",
        resizable && "touch-none",
        !win.placed && (side === "left" ? "bottom-6 left-6" : "right-6 bottom-6"),
        props.cls as string,
      )}
    >
      {children}
    </div>
  );
};
