// A floating button that opens a panel beside it. The button is a Floating
// thing with the shared drag; the panel follows it and stays in the window.
// On a phone the panel is a sheet from the bottom.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "cn";
import type { Renderer } from "../render";
import { icon } from "../icons";
import { t } from "../theme";
import { useIsMobile } from "@/hooks/use-mobile";
import { Sheet as UiSheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useOwnedOpen } from "./surfaces";
import { useFloating, viewport } from "./floating";
import { panelSize, placePanel, type Rect } from "../assistant-math";

const BUTTON = { width: 48, height: 48 };

export const Assistant: Renderer = ({ node, props, children, emit }) => {
  const [open, setOpen] = useOwnedOpen(props.open, props.default_open);
  const mobile = useIsMobile();
  const Icon = icon(props.icon ?? "message-square");
  const label = String(props.label ?? "Assistant");
  const title = props.title ? String(props.title) : label;
  const draggable = props.draggable !== false;

  const toggle = useCallback(
    (next: boolean) => {
      setOpen(next);
      if (props.on_toggle) emit("toggle", next);
    },
    [setOpen, props.on_toggle, emit],
  );

  const floating = useFloating<HTMLButtonElement>({
    nodeId: node.id,
    side: props.side === "left" ? "left" : "right",
    draggable,
    size: BUTTON,
    onPress: () => toggle(!open),
  });

  const [panelAt, setPanelAt] = useState<Rect | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // The panel follows the button, and both stay inside the window as it resizes.
  const { place } = floating;
  useLayoutEffect(() => {
    if (!open || mobile) {
      setPanelAt(null);
      return;
    }
    const compute = () => {
      const size = panelSize(viewport());
      setPanelAt({ ...placePanel({ ...place(), ...BUTTON }, size, viewport()), ...size });
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [open, mobile, place]);

  // Escape closes the panel, and opening it moves focus inside.
  useEffect(() => {
    if (!open || mobile) return;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        toggle(false);
        floating.ref.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, mobile, toggle, floating.ref]);

  const body = <div className="flex min-h-0 grow flex-col [&>*>.mw-fill]:basis-0">{children}</div>;

  return (
    <>
      <button
        ref={floating.ref}
        type="button"
        aria-label={label}
        aria-expanded={open}
        {...floating.handlers}
        style={floating.style}
        className={cn(
          "fixed z-40 flex size-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none print:hidden",
          draggable && "cursor-grab touch-none select-none active:cursor-grabbing",
          floating.corner,
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
            <div className="flex min-h-0 grow flex-col p-3">{body}</div>
          </SheetContent>
        </UiSheet>
      ) : open && panelAt ? (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={title}
          tabIndex={-1}
          style={{ left: panelAt.x, top: panelAt.y, width: panelAt.width, height: panelAt.height }}
          className="fixed z-40 flex flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-xl outline-none print:hidden"
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b px-4 py-2.5">
            <span className="text-sm font-semibold">{title}</span>
            <button
              type="button"
              aria-label={t("close")}
              onClick={() => toggle(false)}
              className="rounded-sm p-1 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <CloseIcon />
            </button>
          </div>
          <div className="flex min-h-0 grow flex-col p-3">{body}</div>
        </div>
      ) : null}
    </>
  );
};

function CloseIcon() {
  const X = icon("x");
  return X ? <X className="size-4" /> : <span aria-hidden>×</span>;
}
