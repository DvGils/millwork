// Something pinned over the page in a bottom corner, and the dragging that
// lets the reader move it. `useFloating` is the shared part: where the thing
// is, the pointer handlers that drag it, and the memory of where it was put,
// per node. `Floating` is the plain container; the Assistant's button uses
// the same hook.

import { useCallback, useEffect, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { cn } from "cn";
import type { Renderer } from "../render";
import { clampPosition, isClick, restingPlace, type Point, type Size } from "../assistant-math";

export function viewport(): Size {
  return { width: window.innerWidth, height: window.innerHeight };
}

function remembered(key: string): Point | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const p = JSON.parse(raw) as Point;
    return typeof p.x === "number" && typeof p.y === "number" ? p : null;
  } catch {
    return null;
  }
}

function remember(key: string, at: Point) {
  try {
    window.localStorage.setItem(key, JSON.stringify(at));
  } catch {
    // storage may be unavailable; the thing then starts in its corner next time
  }
}

export interface FloatingOptions {
  nodeId: string;
  side: "left" | "right";
  draggable: boolean;
  // The size the thing has, for keeping it inside the window. Measured from
  // the element when a ref is given, else this.
  size: Size;
  // What a press that did not turn into a drag does.
  onPress?: () => void;
}

export interface FloatingHandle<T extends HTMLElement> {
  ref: React.RefObject<T | null>;
  // Where the top-left corner is right now, dragged or at rest.
  place: () => Point;
  style: CSSProperties | undefined;
  // Classes for the resting corner; none once dragged.
  corner: string | undefined;
  handlers: {
    onPointerDown: (e: ReactPointerEvent<T>) => void;
    onPointerMove: (e: ReactPointerEvent<T>) => void;
    onPointerUp: (e: ReactPointerEvent<T>) => void;
    onPointerCancel: () => void;
    // The click that ends a drag goes nowhere; any other click is the press.
    onClickCapture: (e: ReactMouseEvent<T>) => void;
    onClick: () => void;
  };
  dragged: boolean;
}

export function useFloating<T extends HTMLElement>({ nodeId, side, draggable, size, onPress }: FloatingOptions): FloatingHandle<T> {
  const storageKey = `mw:floating:${nodeId}`;
  const ref = useRef<T>(null);
  const [at, setAt] = useState<Point | null>(() => (draggable ? remembered(storageKey) : null));
  const drag = useRef<{ from: Point; origin: Point; moved: boolean } | null>(null);
  const dragged = useRef(false);

  const measured = useCallback((): Size => {
    const el = ref.current;
    return el ? { width: el.offsetWidth, height: el.offsetHeight } : size;
  }, [size]);

  const place = useCallback((): Point => {
    if (at) return at;
    const el = ref.current;
    if (el) {
      const r = el.getBoundingClientRect();
      return { x: r.left, y: r.top };
    }
    return restingPlace(side, size, viewport());
  }, [at, side, size]);

  // A dragged thing stays inside the window as it resizes.
  useEffect(() => {
    if (!at) return;
    const onResize = () => setAt((p) => (p ? clampPosition(p, measured(), viewport()) : p));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [at, measured]);

  const onPointerDown = (e: ReactPointerEvent<T>) => {
    if (!draggable || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { from: { x: e.clientX, y: e.clientY }, origin: place(), moved: false };
  };
  const onPointerMove = (e: ReactPointerEvent<T>) => {
    const d = drag.current;
    if (!d) return;
    const now = { x: e.clientX, y: e.clientY };
    if (!d.moved && isClick(d.from, now)) return;
    d.moved = true;
    setAt(clampPosition({ x: d.origin.x + now.x - d.from.x, y: d.origin.y + now.y - d.from.y }, measured(), viewport()));
  };
  const onPointerUp = (e: ReactPointerEvent<T>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    if (!d.moved) return;
    dragged.current = true;
    const el = ref.current;
    if (el) {
      const r = el.getBoundingClientRect();
      remember(storageKey, { x: r.left, y: r.top });
    }
  };
  const onClickCapture = (e: ReactMouseEvent<T>) => {
    if (!dragged.current) return;
    dragged.current = false;
    e.preventDefault();
    e.stopPropagation();
  };
  const onClick = () => onPress?.();

  return {
    ref,
    place,
    style: at ? { left: at.x, top: at.y } : undefined,
    corner: at ? undefined : side === "left" ? "bottom-6 left-6" : "right-6 bottom-6",
    handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: () => (drag.current = null), onClickCapture, onClick },
    dragged: at !== null,
  };
}

export const Floating: Renderer = ({ node, props, children }) => {
  const draggable = props.draggable === true;
  const floating = useFloating<HTMLDivElement>({
    nodeId: node.id,
    side: props.side === "left" ? "left" : "right",
    draggable,
    size: { width: 200, height: 48 },
  });
  return (
    <div
      ref={floating.ref}
      style={floating.style}
      {...floating.handlers}
      className={cn("fixed z-40 print:hidden", draggable && "cursor-grab touch-none select-none active:cursor-grabbing", floating.corner, props.cls as string)}
    >
      {children}
    </div>
  );
};
