// Surfaces and feedback: tabs, dialogs, empties, alerts, progress, split panes.

import { type CSSProperties, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { Renderer } from "../render";
import { Slot } from "../render";
import { useStatus } from "../ws";
import { useHiddenAbove } from "../veil";
import { t } from "../theme";
import { store, useMounts, useNode } from "../store";
import { has, linkLook } from "../lib";
import { anchorProps, InSidebar } from "./anchor";
import { useStickToEnd } from "../stick";
import { ScrollArea as UiScrollArea } from "@/components/ui/scroll-area";
import { cn } from "cn";
import { icon } from "../icons";
import { toneText } from "./layout";
import { Tabs as UiTabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog as UiDialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Empty as UiEmpty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Alert as UiAlert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Progress as UiProgress, ProgressLabel, ProgressTrack, ProgressIndicator, ProgressValue } from "@/components/ui/progress";
import { Skeleton as UiSkeleton } from "@/components/ui/skeleton";
import { Spinner as UiSpinner } from "@/components/ui/spinner";
import { Sparkline } from "./charts";
import { formatNumber } from "../format";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Kbd as UiKbd, KbdGroup } from "@/components/ui/kbd";
import { Tooltip as UiTooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Badge as UiBadge } from "@/components/ui/badge";

// What is left beside a tab that was scrolled into sight, in pixels, so
// that it does not sit against the edge.
const STRIP_EDGE = 12;

// Tabs: `value` controlled by the server, `default` kept by the client.
export const Tabs: Renderer = ({ node, props, emit }) => {
  const controlled = has(props, "value");
  const tabs = node.children;
  const first = firstTabId(tabs, props.default);
  // The open tab, for tabs that keep their own choice. The server asks for
  // it with `track` when parts of the page under these tabs are only kept up
  // to date while their tab is open. It is said when the tabs appear and
  // when the choice changes. It is said again when the socket opens and
  // when a whole page is put here, since these tabs live on under the same
  // id while the session behind them may be a new one, or may have been on
  // a page without them in between and have forgotten.
  const [open, setOpen] = useState(first);
  const status = useStatus();
  const mounts = useMounts();
  const track = Boolean(props.track) && !controlled;
  useEffect(() => {
    if (track && status === "open") emit("show", open);
    // `emit` is made anew at every render and always speaks for this node.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track, open, status, mounts]);
  // A strip wider than its place scrolls sideways, and the chosen tab is
  // brought into sight when the choice changes and when the strip gets
  // another width, as it does when a phone is turned. Only the strip is
  // moved: the page stays where the person has it, also when the choice
  // comes from the server.
  const strip = useRef<HTMLDivElement>(null);
  const chosen = controlled ? String(props.value ?? "") : open;
  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    const show = () => {
      const tab = el.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
      if (!tab) return;
      const box = el.getBoundingClientRect();
      const at = tab.getBoundingClientRect();
      if (at.left < box.left) el.scrollLeft -= box.left - at.left + STRIP_EDGE;
      else if (at.right > box.right) el.scrollLeft += at.right - box.right + STRIP_EDGE;
    };
    show();
    if (typeof ResizeObserver === "undefined") return;
    const sizes = new ResizeObserver(show);
    sizes.observe(el);
    return () => sizes.disconnect();
  }, [chosen]);
  return (
    <UiTabs
      value={controlled ? String(props.value ?? "") : undefined}
      defaultValue={!controlled ? first : undefined}
      onValueChange={(v) => {
        // Also when the tabs move on by themselves, from a tab that was
        // removed or disabled to the first one that can be chosen.
        setOpen(String(v));
        if (props.on_change) emit("change", v);
      }}
      // In a row, or in a column that centers what is in it, the tabs would
      // be as wide as their strip. Held to the width there is, the strip
      // scrolls there too.
      className={cn("flex max-w-full min-w-0 flex-col gap-3", props.cls as string)}
    >
      {/* The room above and below is for the line under the chosen tab,
          which what scrolls would cut off. */}
      <div ref={strip} className="-my-1 overflow-x-auto py-1 [scrollbar-width:none]">
        <TabsList variant={props.variant === "pill" ? "default" : "line"}>
          {tabs.map((id) => (
            <TabTrigger key={id} id={id} />
          ))}
        </TabsList>
      </div>
      {tabs.map((id) => (
        <TabPanel key={id} id={id} />
      ))}
    </UiTabs>
  );
};

// A hidden tab is not among the tabs: it has no trigger and no panel, and
// the strip does not open on it.
function firstTabId(ids: string[], wanted?: unknown): string {
  const shown = ids.map((id) => store.get(id)).filter((tab) => tab && !tab.props.hidden);
  const named = shown.find((tab) => wanted != null && String(tab?.props.id) === String(wanted));
  if (wanted != null && (named || shown.length === 0)) return String(wanted);
  return shown[0] ? String(shown[0].props.id ?? "") : "";
}

function TabTrigger({ id }: { id: string }) {
  const tab = useNode(id);
  if (!tab || tab.props.hidden) return null;
  const Icon = icon(tab.props.icon);
  return (
    <TabsTrigger data-node={id} value={String(tab.props.id)} disabled={Boolean(tab.props.disabled)}>
      {Icon ? <Icon /> : null}
      {String(tab.props.label ?? "")}
      {tab.props.badge ? <UiBadge variant="secondary">{String(tab.props.badge)}</UiBadge> : null}
    </TabsTrigger>
  );
}

function TabPanel({ id }: { id: string }) {
  const tab = useNode(id);
  if (!tab) return null;
  // A hidden tab keeps what is in it, as any hidden component does, and
  // shows none of it, whatever the strip is told to be on.
  return (
    <TabsContent
      value={String(tab.props.id)}
      keepMounted
      className="flex flex-col gap-4"
      style={tab.props.hidden ? { display: "none" } : undefined}
    >
      <SlotChildren ids={tab.children} />
    </TabsContent>
  );
}

// Children of a node rendered by id, for wrappers that lay their children out themselves.
import { Render } from "../render";
export function SlotChildren({ ids }: { ids: string[] }) {
  return (
    <>
      {ids.map((cid) => (
        <Render key={cid} id={cid} />
      ))}
    </>
  );
}

// Tab is rendered by its Tabs parent; on its own it is just its children.
export const Tab: Renderer = ({ children }) => <>{children}</>;

// The layers of what lies over the page. A dialog or a sheet is at 50. The
// floating assistant is over those, at 55, since it is there to help with
// whatever is open. A question, and a dialog or a sheet that cannot be
// dismissed, is over the assistant: it wants its answer before anything
// else, the assistant included. Lists, menus and tooltips are over all of
// that, at 58, wherever they were opened from, and a toast is at 60.
export const URGENT = "z-[57]";

// Whether a dialog is one that wants its answer first: a question a
// handler waits on, or one that cannot be dismissed.
export function isUrgent(nodeId: string, dismissable: unknown): boolean {
  return dismissable === false || nodeId.includes("/@ask:");
}

// How many of those are open. While one is, the assistant is under it and
// is no more to be read than to be seen.
let urgentOpen = 0;
const urgentListeners = new Set<() => void>();
function urgentChanged(by: number) {
  urgentOpen += by;
  for (const listener of urgentListeners) listener();
}
export function useUrgent(open: boolean) {
  useEffect(() => {
    if (!open) return;
    urgentChanged(1);
    return () => urgentChanged(-1);
  }, [open]);
}
export function useBlocked(): boolean {
  return useSyncExternalStore(
    (listener) => {
      urgentListeners.add(listener);
      return () => urgentListeners.delete(listener);
    },
    () => urgentOpen > 0,
    () => urgentOpen > 0,
  );
}

// Whether the person is busy in the floating assistant, or in a list or a
// menu it opened: where they last pressed or put the keyboard. A press or
// the keyboard in the assistant says yes, and in a dialog, on what dims
// the page, on a toast or on the page itself says no. Anywhere else, a
// list that hangs over the page say, leaves it as it was, since that
// belongs to whatever opened it.
let withAssistant = false;
function landed(event: Event) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest("[data-mw-over]")) withAssistant = true;
  else if (target.closest("[data-slot$='-overlay'], [data-slot$='-content'][data-node], [data-slot^='toast'], #root")) withAssistant = false;
}
if (typeof document !== "undefined") {
  document.addEventListener("pointerdown", landed, true);
  document.addEventListener("focusin", landed, true);
}

// Whether what would close a dialog or a sheet is none of its business:
// a press outside it, Escape, or the keyboard leaving it, while the person
// is busy in the assistant, which lies over the dialog by design. A press
// that begins on a field of the assistant and ends on the list it opened
// is one. Left as it is, the dialog stays open.
//
// Escape goes by where the keyboard was when the key went down, which is
// what the key was pressed on: the window may have been minimized by it
// since. In the assistant's window, or in a list it opened, the key is for
// that. On the assistant's button, which has no use for it, or nowhere at
// all, it is the dialog's.
export function besideIt(details: { reason: string; event: Event; cancel: () => void }): boolean {
  if (!["outside-press", "escape-key", "focus-out"].includes(details.reason)) return false;
  const target = details.event.target;
  const at = target instanceof Element ? target : null;
  let beside: boolean;
  if (details.reason === "escape-key") {
    if (!at || at === document.body || at === document.documentElement || at.matches("button[data-mw-over]")) beside = false;
    else beside = at.closest("[data-mw-over]") !== null || withAssistant;
  } else {
    beside = withAssistant || at?.closest("[data-mw-over]") != null;
  }
  if (beside) details.cancel();
  return beside;
}

const dialogSize: Record<string, string> = {
  sm: "sm:max-w-sm",
  md: "sm:max-w-lg",
  lg: "sm:max-w-2xl",
  xl: "sm:max-w-4xl",
  full: "sm:max-w-[calc(100%-2rem)]",
};

export const Dialog: Renderer = ({ node, props, children, emit }) => {
  const status = useStatus();
  // Hidden, or in something hidden, it does not open: it is drawn at the
  // top of the page, where the wrapper that hides a node does not reach.
  const hidden = useHiddenAbove();
  const shown = Boolean(props.open) && status !== "closed" && !hidden;
  const urgent = isUrgent(node.id, props.dismissable);
  useUrgent(shown && urgent);
  return (
  <UiDialog
    open={shown}
    disablePointerDismissal={props.dismissable === false}
    onOpenChange={(open, details) => {
      if (!open && besideIt(details)) return;
      if (!open && props.dismissable !== false && props.on_close) emit("close");
    }}
  >
    <DialogContent
      // The window is drawn outside the page's own elements, so it carries
      // the node's id itself, for what points at the dialog.
      data-node={node.id}
      // A column no taller than the window: the title and the footer stay, and
      // the body between them scrolls when what it holds is taller or wider.
      className={cn("flex max-h-[calc(100dvh-2rem)] flex-col", dialogSize[String(props.size ?? "md")], urgent && URGENT, props.cls as string)}
      overlayClassName={urgent ? URGENT : undefined}
      showCloseButton={props.dismissable !== false}
    >
      {/* The cross has the top right corner to itself: a title stops short of
          it, and a dialog without a title begins under it. */}
      {props.title || props.description ? (
        <DialogHeader className={props.dismissable !== false ? "pr-8" : undefined}>
          {props.title ? <DialogTitle>{String(props.title)}</DialogTitle> : null}
          {props.description ? <DialogDescription>{String(props.description)}</DialogDescription> : null}
        </DialogHeader>
      ) : props.dismissable !== false ? (
        <div className="h-2 shrink-0" />
      ) : null}
      {/* The body reaches the dialog's edges, so a focus ring at its side is not
          cut off. It is a plain box that scrolls, with the column inside it: a
          column that scrolled itself would first squeeze every child that
          clips its own overflow, a card for one, down to nothing. */}
      <div data-slot="dialog-body" className="-mx-4 -my-1 min-h-0 min-w-0 overflow-auto px-4 py-1 wrap-break-word">
        <div className="flex flex-col gap-4">{children}</div>
      </div>
      {props.footer ? (
        <DialogFooter>
          <Slot value={props.footer} />
        </DialogFooter>
      ) : null}
    </DialogContent>
  </UiDialog>
  );
};

export const Empty: Renderer = ({ props }) => {
  const Icon = icon(props.icon);
  return (
    <UiEmpty className={props.cls as string}>
      <EmptyHeader>
        {Icon ? (
          <EmptyMedia variant="icon">
            <Icon />
          </EmptyMedia>
        ) : null}
        <EmptyTitle>{String(props.title ?? "")}</EmptyTitle>
        {props.description ? <EmptyDescription>{String(props.description)}</EmptyDescription> : null}
      </EmptyHeader>
      {props.action ? (
        <EmptyContent>
          <Slot value={props.action} />
        </EmptyContent>
      ) : null}
    </UiEmpty>
  );
};

const alertIcon: Record<string, string> = {
  default: "info",
  muted: "info",
  primary: "info",
  accent: "info",
  success: "check-circle-2",
  warning: "alert-triangle",
  destructive: "alert-circle",
};

const alertTone: Record<string, string> = {
  success: "text-success *:data-[slot=alert-description]:text-success/90",
  warning: "text-warning *:data-[slot=alert-description]:text-warning/90",
};

export const Alert: Renderer = ({ node, props, emit, children }) => {
  const tone = String(props.tone ?? "default");
  const Icon = icon(props.icon ?? alertIcon[tone]);
  return (
    <UiAlert
      variant={tone === "destructive" ? "destructive" : "default"}
      className={cn(alertTone[tone], props.cls as string)}
    >
      {Icon ? <Icon /> : null}
      {props.title ? <AlertTitle>{String(props.title)}</AlertTitle> : null}
      {props.description ? <AlertDescription>{String(props.description)}</AlertDescription> : null}
      {node.children.length ? <div className="col-start-2 mt-1 flex min-w-0 flex-col gap-2">{children}</div> : null}
      {Array.isArray(props.actions) && props.actions.length ? (
        <div className="col-start-2 mt-2 flex flex-wrap gap-2">
          {(props.actions as unknown[]).map((a, i) => (
            <Slot key={i} value={a} />
          ))}
        </div>
      ) : null}
      {props.dismissable ? (
        <button
          type="button"
          className="absolute top-2 right-2 text-muted-foreground hover:text-foreground"
          aria-label={t("dismiss")}
          onClick={() => emit("dismiss")}
        >
          ×
        </button>
      ) : null}
    </UiAlert>
  );
};

export const Progress: Renderer = ({ props }) => {
  const value = typeof props.value === "number" ? Math.round(props.value * 100) : null;
  return (
    <UiProgress value={value} className={cn("flex flex-col gap-1.5", props.cls as string)}>
      {props.label || value !== null ? (
        <div className="flex items-center justify-between text-sm">
          {props.label ? <ProgressLabel>{String(props.label)}</ProgressLabel> : <span />}
          {value !== null ? <ProgressValue /> : null}
        </div>
      ) : null}
      <ProgressTrack>
        <ProgressIndicator />
      </ProgressTrack>
      {props.description ? <p className="text-xs text-muted-foreground">{String(props.description)}</p> : null}
    </UiProgress>
  );
};

export const Skeleton: Renderer = ({ props }) => {
  const rows = typeof props.rows === "number" ? props.rows : 3;
  const shape = String(props.shape ?? "text");
  if (shape === "card") return <UiSkeleton className={cn("h-32 w-full rounded-xl", props.cls as string)} />;
  return (
    <div className={cn("flex flex-col gap-2", props.cls as string)}>
      {Array.from({ length: rows }, (_, i) => (
        <UiSkeleton key={i} className={cn("h-4", shape === "table" ? "w-full" : i === rows - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
};

// Icon: one of the bundle's or a file of the app's, on its own. With a
// label it is an image with a name, and without one it is decoration.
export const Icon: Renderer = ({ props }) => {
  const Drawn = icon(props.name);
  if (!Drawn) return null;
  const size = props.size === "lg" ? "size-6" : props.size === "sm" ? "size-3" : "size-4";
  const tone = props.tone === "accent" ? "text-accent-foreground" : props.tone ? toneText[String(props.tone)] : undefined;
  const drawn = <Drawn className={cn("shrink-0", size, tone, props.cls as string)} />;
  if (!props.label) return drawn;
  return (
    <span role="img" aria-label={String(props.label)} className="inline-flex">
      {drawn}
    </span>
  );
};

export const Spinner: Renderer = ({ props }) => (
  <span className={cn("inline-flex items-center gap-2 text-sm text-muted-foreground", props.cls as string)}>
    <UiSpinner className={props.size === "lg" ? "size-6" : props.size === "sm" ? "size-3" : "size-4"} />
    {props.label ? String(props.label) : null}
  </span>
);

// Split: resizable panes; the user's drag is client-owned, `sizes` is the starting point.
export const Split: Renderer = ({ node, props }) => {
  const sizes = Array.isArray(props.sizes) ? (props.sizes as number[]) : [];
  const mins = Array.isArray(props.min_sizes) ? (props.min_sizes as number[]) : [];
  const vertical = props.direction === "vertical";
  const collapsible = (i: number) => (Array.isArray(props.collapsible) ? Boolean(props.collapsible[i]) : Boolean(props.collapsible));
  // The panel group sizes itself to 100% of its parent inline, so the height
  // (from `cls`, or from filling the page body) lives on a wrapper.
  return (
    <div className={cn("mw-fill flex min-h-0 grow flex-col", props.cls as string)}>
      <ResizablePanelGroup orientation={vertical ? "vertical" : "horizontal"} className="min-h-0 grow">
        {node.children.map((cid, i) => (
          <PaneAndHandle key={cid} id={cid} index={i} last={i === node.children.length - 1} size={sizes[i]} min={mins[i]} collapsible={collapsible(i)} />
        ))}
      </ResizablePanelGroup>
    </div>
  );
};

function PaneAndHandle({ id, index, last, size, min, collapsible }: { id: string; index: number; last: boolean; size?: number; min?: number; collapsible: boolean }) {
  return (
    <>
      <ResizablePanel
        id={`pane-${index}`}
        defaultSize={size !== undefined ? `${size}%` : undefined}
        minSize={min !== undefined ? `${min}%` : undefined}
        collapsible={collapsible}
        collapsedSize={0}
        className="flex min-h-0 flex-col overflow-auto"
      >
        <Render id={id} />
      </ResizablePanel>
      {!last ? <ResizableHandle withHandle /> : null}
    </>
  );
}

// The column counts go to the stylesheet as variables, which has the widths at
// which each takes over, so any count works and none needs a class of its own.
// A grid says all four, a width it has no count for as one that is not set.
// A variable left out would be the one a grid around this one set, since
// variables are handed down.
export function gridColumns(cols: unknown): Record<string, number | string> {
  const by = typeof cols === "number" ? { sm: cols } : cols && typeof cols === "object" ? (cols as Record<string, number>) : { sm: 2 };
  return {
    "--mw-cols": by.sm ?? 1,
    "--mw-cols-md": by.md ?? "initial",
    "--mw-cols-lg": by.lg ?? "initial",
    "--mw-cols-xl": by.xl ?? "initial",
  };
}

export const Grid: Renderer = ({ props, children }) => {
  const gap = typeof props.gap === "number" ? props.gap : 4;
  return (
    <div data-box="" className={cn("mw-grid grid", `gap-${gap}`, props.cls as string)} style={gridColumns(props.cols) as CSSProperties}>
      {children}
    </div>
  );
};

export const Stat: Renderer = ({ props }) => {
  const Icon = icon(props.icon);
  const tone = String(props.tone ?? "");
  const delta = typeof props.delta === "number" ? props.delta : null;
  const trend = Array.isArray(props.trend) ? (props.trend as unknown[]).filter((v): v is number => typeof v === "number") : [];
  // The delta's colour says whether the move is welcome, not which way it went.
  const goodUp = props.good !== "down";
  const up = delta !== null && delta > 0;
  const down = delta !== null && delta < 0;
  const DeltaIcon = icon(up ? "arrow-up" : down ? "arrow-down" : "minus");
  const deltaTone = !up && !down ? "text-muted-foreground" : up === goodUp ? "text-success" : "text-destructive";
  return (
    <div className={cn("flex flex-col gap-1 rounded-xl bg-card p-4 ring-1 ring-foreground/10", props.cls as string)}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {Icon ? <Icon className="size-3.5" /> : null}
        {String(props.label ?? "")}
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-2">
          <div className={cn("text-2xl font-semibold tabular-nums", tone === "destructive" && "text-destructive", tone === "success" && "text-success", tone === "warning" && "text-warning", tone === "primary" && "text-primary")}>
            {String(props.value ?? "")}
          </div>
          {delta !== null ? (
            <span className={cn("inline-flex items-center gap-0.5 text-xs font-medium tabular-nums", deltaTone)}>
              {DeltaIcon ? <DeltaIcon className="size-3" /> : null}
              {formatNumber(Math.abs(delta), props.delta_format === "number" ? "number" : "percent")}
            </span>
          ) : null}
        </div>
        {trend.length > 1 ? <Sparkline values={trend} /> : null}
      </div>
      {props.hint ? <div className="text-xs text-muted-foreground">{String(props.hint)}</div> : null}
    </div>
  );
};

// How a link in a sidebar looks: a row to press, the current page marked,
// in the sidebar's own colors.
const navLook =
  "flex items-start gap-2 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground aria-[current=page]:bg-sidebar-accent aria-[current=page]:font-medium aria-[current=page]:text-sidebar-accent-foreground";

// A link in the header: no line under it, but for the current page.
const headerLook =
  "in-data-[slot=header]:no-underline in-data-[slot=header]:aria-[current=page]:underline in-data-[slot=header]:aria-[current=page]:decoration-current in-data-[slot=header]:aria-[current=page]:decoration-2 in-data-[slot=header]:aria-[current=page]:underline-offset-8";

// A same-origin page link navigates on the session; anything else is a plain anchor.
export const Link: Renderer = ({ props }) => {
  const Icon = icon(props.icon);
  const inSidebar = useContext(InSidebar);
  return (
    <a
      {...anchorProps(props.href, props.target)}
      aria-current={props.active ? "page" : undefined}
      // In the header a link is one of a row of places to go, and a row of
      // underlined words is not how that reads. The one line there is under
      // the page the tab is on.
      className={cn(
        inSidebar
          ? navLook
          : ["inline-flex items-center gap-1 text-sm text-primary aria-[current=page]:font-medium", linkLook, headerLook],
        props.cls as string,
      )}
    >
      {Icon ? <Icon className={inSidebar ? "mt-0.5 size-4 shrink-0" : "size-3.5"} /> : null}
      {String(props.label ?? "")}
      {/* In a sidebar the count stands at the row's end, where a column of them lines up. */}
      {props.badge ? (
        <UiBadge variant="secondary" className={inSidebar ? "ml-auto" : undefined}>
          {String(props.badge)}
        </UiBadge>
      ) : null}
    </a>
  );
};

export const Kbd: Renderer = ({ props }) => (
  <KbdGroup className={props.cls as string}>
    {(Array.isArray(props.keys) ? (props.keys as string[]) : []).map((k, i) => (
      <UiKbd key={i}>{k}</UiKbd>
    ))}
  </KbdGroup>
);

// The trigger hugs its child (`w-fit`): in a column it would otherwise
// stretch to the full width and the tip would float over empty space.
export const Tooltip: Renderer = ({ props, children }) => (
  <UiTooltip>
    <TooltipTrigger render={<span className={cn("inline-flex w-fit max-w-full", props.cls as string)} />}>{children}</TooltipTrigger>
    <TooltipContent>{String(props.content ?? "")}</TooltipContent>
  </UiTooltip>
);

// Keeps a client-owned open/closed flag that the server may override with `open`.
export function useOwnedOpen(open: unknown, defaultOpen: unknown): [boolean, (v: boolean) => void] {
  const controlled = typeof open === "boolean";
  const [local, setLocal] = useState(Boolean(defaultOpen));
  useEffect(() => {
    if (controlled) setLocal(Boolean(open));
  }, [controlled, open]);
  return [controlled ? Boolean(open) : local, setLocal];
}

export const ScrollArea: Renderer = ({ props, children }) => {
  const holder = useStickToEnd<HTMLDivElement>(Boolean(props.stick_to_end));
  return (
    <UiScrollArea
      ref={holder}
      // One that fills is a column of its own, so its viewport is given the
      // height the area came to and scrolls inside it. It keeps a few rows
      // of height where its neighbors leave it none, and the page scrolls.
      className={cn("min-h-0", props.fill ? "mw-fill flex min-h-24 grow flex-col" : undefined, props.cls as string)}
      style={props.height ? { height: String(props.height) } : undefined}
    >
      <div className="flex flex-col gap-4">{children}</div>
    </UiScrollArea>
  );
};
