// Surfaces and feedback: tabs, dialogs, empties, alerts, progress, split panes.

import { useEffect, useState } from "react";
import type { Renderer } from "../render";
import { Slot } from "../render";
import { useStatus } from "../ws";
import { t } from "../theme";
import { store, useNode } from "../store";
import { navigate } from "../ws";
import { has, isInternalPath, safeUrl } from "../lib";
import { ScrollArea as UiScrollArea } from "@/components/ui/scroll-area";
import { cn } from "cn";
import { icon } from "../icons";
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

// Tabs: `value` controlled by the server, `default` kept by the client.
export const Tabs: Renderer = ({ node, props, emit }) => {
  const controlled = has(props, "value");
  const tabs = node.children;
  return (
    <UiTabs
      value={controlled ? String(props.value ?? "") : undefined}
      defaultValue={!controlled ? String(props.default ?? firstTabId(tabs)) : undefined}
      onValueChange={(v) => props.on_change && emit("change", v)}
      className={cn("flex flex-col gap-3", props.cls as string)}
    >
      <TabsList variant={props.variant === "pill" ? "default" : "line"}>
        {tabs.map((id) => (
          <TabTrigger key={id} id={id} />
        ))}
      </TabsList>
      {tabs.map((id) => (
        <TabPanel key={id} id={id} />
      ))}
    </UiTabs>
  );
};

function firstTabId(ids: string[]): string {
  const first = ids[0] ? store.get(ids[0]) : undefined;
  return first ? String(first.props.id ?? "") : "";
}

function TabTrigger({ id }: { id: string }) {
  const tab = useNode(id);
  if (!tab) return null;
  const Icon = icon(tab.props.icon);
  return (
    <TabsTrigger value={String(tab.props.id)} disabled={Boolean(tab.props.disabled)}>
      {Icon ? <Icon /> : null}
      {String(tab.props.label ?? "")}
      {tab.props.badge ? <UiBadge variant="secondary">{String(tab.props.badge)}</UiBadge> : null}
    </TabsTrigger>
  );
}

function TabPanel({ id }: { id: string }) {
  const tab = useNode(id);
  if (!tab) return null;
  return (
    <TabsContent value={String(tab.props.id)} keepMounted className="flex flex-col gap-4">
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

const dialogSize: Record<string, string> = {
  sm: "sm:max-w-sm",
  md: "sm:max-w-lg",
  lg: "sm:max-w-2xl",
  xl: "sm:max-w-4xl",
  full: "sm:max-w-[calc(100%-2rem)]",
};

export const Dialog: Renderer = ({ props, children, emit }) => {
  const status = useStatus();
  return (
  <UiDialog
    open={Boolean(props.open) && status !== "closed"}
    disablePointerDismissal={props.dismissable === false}
    onOpenChange={(open) => {
      if (!open && props.dismissable !== false && props.on_close) emit("close");
    }}
  >
    <DialogContent
      // A column no taller than the window: the title and the footer stay, and
      // the body between them scrolls when what it holds is taller or wider.
      className={cn("flex max-h-[calc(100dvh-2rem)] flex-col", dialogSize[String(props.size ?? "md")], props.cls as string)}
      showCloseButton={props.dismissable !== false}
    >
      {props.title || props.description ? (
        <DialogHeader>
          {props.title ? <DialogTitle>{String(props.title)}</DialogTitle> : null}
          {props.description ? <DialogDescription>{String(props.description)}</DialogDescription> : null}
        </DialogHeader>
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

export const Alert: Renderer = ({ props, emit }) => {
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

const gridCols: Record<number, string> = { 1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4", 5: "grid-cols-5", 6: "grid-cols-6", 12: "grid-cols-12" };
const gridColsMd: Record<number, string> = { 1: "md:grid-cols-1", 2: "md:grid-cols-2", 3: "md:grid-cols-3", 4: "md:grid-cols-4", 5: "md:grid-cols-5", 6: "md:grid-cols-6" };
const gridColsLg: Record<number, string> = { 1: "lg:grid-cols-1", 2: "lg:grid-cols-2", 3: "lg:grid-cols-3", 4: "lg:grid-cols-4", 5: "lg:grid-cols-5", 6: "lg:grid-cols-6" };

export const Grid: Renderer = ({ props, children }) => {
  const cols = props.cols;
  let classes = "grid-cols-2";
  if (typeof cols === "number") classes = gridCols[cols] ?? "grid-cols-2";
  else if (cols && typeof cols === "object") {
    const c = cols as Record<string, number>;
    classes = cn(gridCols[c.sm ?? 1], c.md ? gridColsMd[c.md] : undefined, c.lg ? gridColsLg[c.lg] : undefined);
  }
  const gap = typeof props.gap === "number" ? props.gap : 4;
  return <div className={cn("grid", classes, `gap-${gap}`, props.cls as string)}>{children}</div>;
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

// A same-origin page link navigates on the session; anything else is a plain anchor.
export const Link: Renderer = ({ props }) => {
  const Icon = icon(props.icon);
  const href = safeUrl(props.href);
  const internal = isInternalPath(props.href) && props.target !== "_blank";
  return (
    <a
      href={href}
      aria-current={props.active ? "page" : undefined}
      target={props.target === "_blank" ? "_blank" : undefined}
      rel={props.target === "_blank" ? "noreferrer" : undefined}
      onClick={internal ? (e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(props.href as string);
      } : undefined}
      className={cn("inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline aria-[current=page]:font-medium", props.cls as string)}
    >
      {Icon ? <Icon className="size-3.5" /> : null}
      {String(props.label ?? "")}
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

export const ScrollArea: Renderer = ({ props, children }) => (
  <UiScrollArea className={cn("min-h-0", props.cls as string)} style={props.height ? { height: String(props.height) } : undefined}>
    <div className="flex flex-col gap-4">{children}</div>
  </UiScrollArea>
);
