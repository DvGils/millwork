// A floating button that becomes a window. Minimized, it is a round button
// in a corner that can be dragged about. Opened, the button gives way to a
// window that grows from where the button is, is dragged by its header and
// resized from its edges. Minimized, it is the button again: where the
// button was, or at the window's near corner once the window has been moved
// or resized. A pinned button never leaves its corner. On a phone the window
// is a sheet from the bottom.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { cn } from "cn";
import type { Renderer } from "../render";
import { icon } from "../icons";
import { t } from "../theme";
import { useIsMobile } from "@/hooks/use-mobile";
import { Sheet as UiSheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useOwnedOpen } from "./surfaces";
import { useFloating, useWindow, viewport } from "./floating";
import { minimizeTo, openFrom, panelSize, type Size } from "../assistant-math";

const BUTTON = { width: 48, height: 48 };

export const Assistant: Renderer = ({ node, props, children, emit }) => {
  const [open, setOpen] = useOwnedOpen(props.open, props.default_open);
  const mobile = useIsMobile();
  const Icon = icon(props.icon ?? "message-square");
  const Minimize = icon("chevron-down");
  const label = String(props.label ?? "Assistant");
  const title = props.title ? String(props.title) : label;
  const side = props.side === "left" ? "left" : "right";
  const draggable = props.draggable !== false;
  const pinned = props.pinned === true;

  const toggle = useCallback(
    (next: boolean) => {
      setOpen(next);
      if (props.on_toggle) emit("toggle", next);
    },
    [setOpen, props.on_toggle, emit],
  );

  const button = useFloating<HTMLButtonElement>({
    storageKey: `mw:floating:${node.id}:button`,
    side,
    draggable: draggable && !pinned,
    size: BUTTON,
    onPress: () => toggle(true),
  });
  const last = useRef(button.place);
  last.current = button.place;

  const defaultSize = useMemo(() => panelSize(viewport()), []);
  const initial = useCallback((size: Size | null) => openFrom(last.current(), size ?? defaultSize, viewport()), [defaultSize]);
  const win = useWindow<HTMLDivElement>({
    storageKey: `mw:floating:${node.id}:window`,
    draggable,
    resizable: draggable,
    defaultSize,
    initial,
    anchored: true,
  });

  // A window left where it opened gives the button back its place. One that
  // was dragged or resized takes the button along, to the bottom corner on
  // the half of the screen the window is in: the corner it opens from
  // again, so it comes back where it was left.
  const minimize = useCallback(() => {
    if (!pinned && win.moved.current && win.ref.current) {
      button.moveTo(minimizeTo(win.current(), BUTTON, viewport()));
    }
    toggle(false);
  }, [win, button, toggle, pinned]);
  const minimizeNow = useRef(minimize);
  minimizeNow.current = minimize;

  // Opening: the window takes its place before anything is painted, once
  // for each time it opens, so a screen that was narrow for a while does
  // not put a moved window back. Closing: any gesture that was under way
  // on the element that went away is forgotten.
  const { open: placeWindow, reset: resetWindow } = win;
  const { reset: resetButton } = button;
  const placedThisTime = useRef(false);
  useLayoutEffect(() => {
    if (open && !mobile) {
      if (!placedThisTime.current) placeWindow();
      placedThisTime.current = true;
    } else {
      if (!open) placedThisTime.current = false;
      resetWindow();
    }
    resetButton();
  }, [open, mobile, placeWindow, resetWindow, resetButton]);

  // Focus follows the state: into the window when it appears, back to the
  // button when the window goes.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (mobile) return;
    if (open && win.placed) win.ref.current?.focus();
    else if (!open && wasOpen.current) button.ref.current?.focus();
    wasOpen.current = open;
  }, [open, mobile, win.placed, win.ref, button.ref]);

  useEffect(() => {
    if (!open || mobile) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") minimizeNow.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, mobile]);

  const body = <div className="flex min-h-0 grow flex-col p-3 [&>*>.mw-fill]:basis-0">{children}</div>;

  // Once the window has had a place it stays in the tree, hidden while
  // minimized, so what was typed in it is there when it opens again. The
  // frame is square so a press in the corner band lands on it; the rounded
  // face inside clips the content.
  const windowShown = open && !mobile && win.placed;
  const frame = win.placed && !mobile ? (
    <div
      ref={win.ref}
      role="dialog"
      aria-label={title}
      tabIndex={-1}
      hidden={!open}
      style={win.style}
      {...win.frameHandlers}
      className="fixed z-40 touch-none outline-none print:hidden"
    >
      <div aria-hidden className="absolute -inset-1" />
      <div className="relative flex h-full w-full flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-xl">
        <div
          {...(draggable ? win.dragHandlers : {})}
          className={cn("flex shrink-0 items-center justify-between gap-2 border-b px-4 py-2.5 select-none", draggable && "cursor-grab active:cursor-grabbing")}
        >
          <span className="text-sm font-semibold">{title}</span>
          <button
            type="button"
            aria-label={t("minimize")}
            onClick={minimize}
            className="rounded-sm p-1 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {Minimize ? <Minimize className="size-4" /> : <span aria-hidden>_</span>}
          </button>
        </div>
        {body}
      </div>
    </div>
  ) : null;

  return (
    <>
      {frame}
      {windowShown || (mobile && open) ? null : (
      <button
        ref={button.ref}
        type="button"
        aria-label={label}
        aria-expanded={open}
        {...button.handlers}
        style={button.style}
        className={cn(
          "fixed z-40 flex size-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none print:hidden",
          draggable && !pinned && "cursor-grab touch-none select-none active:cursor-grabbing",
          button.corner,
          props.cls as string,
        )}
      >
        {Icon ? <Icon className="size-5" /> : null}
      </button>
      )}
      {mobile ? (
        <UiSheet open={open} onOpenChange={(next) => toggle(next)}>
          <SheetContent side="bottom" className="flex flex-col gap-0 p-0 data-[side=bottom]:h-[85dvh]">
            <SheetHeader className="border-b px-4 py-3">
              <SheetTitle>{title}</SheetTitle>
            </SheetHeader>
            {body}
          </SheetContent>
        </UiSheet>
      ) : null}
    </>
  );
};
