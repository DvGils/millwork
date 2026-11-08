// A floating button that becomes a window. Minimized, it is a round button
// in a corner that can be dragged about. Opened, the button gives way to a
// window that grows from its corner, is dragged by its header and resized
// from its edges, and minimizes back into the button at its near corner. On
// a phone the window is a sheet from the bottom.

import { useCallback, useEffect, useRef } from "react";
import { cn } from "cn";
import type { Renderer } from "../render";
import { icon } from "../icons";
import { t } from "../theme";
import { useIsMobile } from "@/hooks/use-mobile";
import { Sheet as UiSheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useOwnedOpen } from "./surfaces";
import { useFloating, useWindow, viewport } from "./floating";
import { minimizeTo, openFrom, panelSize } from "../assistant-math";

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
    draggable,
    size: BUTTON,
    onPress: () => toggle(true),
  });
  const last = useRef(button.place);
  last.current = button.place;

  const win = useWindow<HTMLDivElement>({
    storageKey: `mw:floating:${node.id}:window`,
    draggable,
    resizable: draggable,
    defaultSize: panelSize(viewport()),
    initial: (size) => openFrom(last.current(), size ?? panelSize(viewport()), viewport()),
  });

  // The window takes its place the first time it opens; after that it is
  // where the reader left it.
  const { open: placeWindow } = win;
  useEffect(() => {
    if (open && !mobile) placeWindow();
  }, [open, mobile, placeWindow]);

  const minimize = useCallback(() => {
    if (win.ref.current) button.moveTo(minimizeTo(win.current(), BUTTON, viewport()));
    toggle(false);
  }, [win, button, toggle]);

  // Escape minimizes, and opening moves focus into the window.
  useEffect(() => {
    if (!open || mobile) return;
    win.ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") minimize();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, mobile, minimize, win.ref]);

  const body = <div className="flex min-h-0 grow flex-col p-3 [&>*>.mw-fill]:basis-0">{children}</div>;

  if (open && !mobile && win.placed) {
    return (
      <div
        ref={win.ref}
        role="dialog"
        aria-label={title}
        tabIndex={-1}
        style={win.style}
        {...win.frameHandlers}
        className="fixed z-40 flex touch-none flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-xl outline-none print:hidden"
      >
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
    );
  }

  return (
    <>
      <button
        ref={button.ref}
        type="button"
        aria-label={label}
        aria-expanded={open}
        {...button.handlers}
        style={button.style}
        className={cn(
          "fixed z-40 flex size-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none print:hidden",
          draggable && "cursor-grab touch-none select-none active:cursor-grabbing",
          button.corner,
          props.cls as string,
        )}
      >
        {Icon ? <Icon className="size-5" /> : null}
      </button>
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
