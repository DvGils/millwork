// Sidebar, accordion, collapsible, radio and toggle groups, checkbox group, sheet, slider.

import { useEffect, useRef, useState } from "react";
import type { Renderer } from "../render";
import { Render, Slot } from "../render";
import { useNode } from "../store";
import { cn } from "cn";
import { has } from "../lib";
import { PageBody, pageBodyClass } from "./page-body";
import { icon } from "../icons";
import {
  Sidebar as UiSidebar,
  SidebarContent,
  SidebarHeader,
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import {
  Accordion as UiAccordion,
  AccordionContent,
  AccordionItem as UiAccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Collapsible as UiCollapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { RadioGroup as UiRadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ToggleGroup as UiToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Checkbox as UiCheckbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Sheet as UiSheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Slider as UiSlider } from "@/components/ui/slider";

interface Opt {
  value: string;
  label?: string | null;
  description?: string | null;
  icon?: string | null;
  disabled?: boolean;
}

const opts = (v: unknown): Opt[] => (Array.isArray(v) ? (v as Opt[]) : []);

// The server's value is taken over when it changes by content: a value rebuilt
// on every render (a string wrapped in an array, a null made an empty list)
// would otherwise re-fire the effect without end.
function useDraft<T>(controlled: boolean, value: T, initial: T): [T, (v: T) => void] {
  const [draft, setDraft] = useState<T>(controlled ? value : initial);
  const key = JSON.stringify(value);
  const seen = useRef(key);
  useEffect(() => {
    if (controlled && seen.current !== key) {
      seen.current = key;
      setDraft(value);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controlled, key]);
  return [draft, setDraft];
}

// A Page with a Sidebar child lays out around it: provider, the sidebar, the rest inset.
export function PageWithSidebar({
  sidebarId,
  rest,
  className,
  style,
  padding,
  header,
}: {
  sidebarId: string;
  rest: string[];
  className: string;
  style?: React.CSSProperties;
  padding?: unknown;
  header?: unknown;
}) {
  const sidebar = useNode(sidebarId);
  if (!sidebar) return null;
  const p = sidebar.props;
  const controlled = has(p, "open");
  return (
    <SidebarProvider
      open={controlled ? Boolean(p.open) : undefined}
      defaultOpen={!controlled ? p.default_open !== false : undefined}
      onOpenChange={(open) => {
        if (p.on_toggle) window.__mwEmit?.(sidebarId, "toggle", open);
      }}
      className="h-dvh"
      style={p.width ? ({ "--sidebar-width": String(p.width) } as React.CSSProperties) : undefined}
    >
      <UiSidebar
        side={p.side === "right" ? "right" : "left"}
        collapsible={(p.collapsible as "offcanvas" | "icon" | "none") ?? "offcanvas"}
      >
        {p.title ? (
          <SidebarHeader>
            <div className="px-2 py-1 text-sm font-semibold">{String(p.title)}</div>
          </SidebarHeader>
        ) : null}
        <SidebarContent className="gap-4 p-3">
          {sidebar.children.map((cid) => (
            <Render key={cid} id={cid} />
          ))}
        </SidebarContent>
      </UiSidebar>
      <SidebarInset className="min-h-0 min-w-0">
        <Slot value={header} />
        <div className="flex items-center gap-2 border-b px-3 py-2 md:hidden">
          <SidebarTrigger />
        </div>
        <div className={pageBodyClass(padding)}>
          <PageBody className={className} style={style}>
            {rest.map((cid) => (
              <Render key={cid} id={cid} />
            ))}
          </PageBody>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

// Sidebar on its own (outside a Page) is just its children in a column.
export const Sidebar: Renderer = ({ props, children }) => (
  <div className={cn("flex flex-col gap-4", props.cls as string)}>{children}</div>
);

export const Accordion: Renderer = ({ node, props, emit }) => {
  const controlled = has(props, "value");
  const [draft, setDraft] = useDraft<string[]>(
    controlled,
    (props.value as string[]) ?? [],
    (props.default as string[]) ?? [],
  );
  return (
    <UiAccordion
      multiple={Boolean(props.multiple)}
      value={draft}
      onValueChange={(v) => {
        const next = (v as string[]) ?? [];
        if (!controlled) setDraft(next);
        if (props.on_change) emit("change", next);
      }}
      className={props.cls as string}
    >
      {node.children.map((cid) => (
        <AccordionEntry key={cid} id={cid} />
      ))}
    </UiAccordion>
  );
};

function AccordionEntry({ id }: { id: string }) {
  const item = useNode(id);
  if (!item) return null;
  return (
    <UiAccordionItem value={String(item.props.id)}>
      <AccordionTrigger>{String(item.props.title ?? "")}</AccordionTrigger>
      <AccordionContent className="flex flex-col gap-3">
        {item.children.map((cid) => (
          <Render key={cid} id={cid} />
        ))}
      </AccordionContent>
    </UiAccordionItem>
  );
}

export const AccordionItem: Renderer = ({ children }) => <>{children}</>;

export const Collapsible: Renderer = ({ props, children, emit }) => {
  const controlled = has(props, "open");
  const [draft, setDraft] = useDraft<boolean>(controlled, Boolean(props.open), Boolean(props.default_open));
  const Chevron = icon("chevron-right");
  return (
    <UiCollapsible
      open={draft}
      onOpenChange={(open) => {
        if (!controlled) setDraft(open);
        if (props.on_toggle) emit("toggle", open);
      }}
      className={cn("flex flex-col gap-2", props.cls as string)}
    >
      <CollapsibleTrigger className="flex items-center gap-1 text-sm font-medium [&[data-panel-open]>svg]:rotate-90">
        {Chevron ? <Chevron className="size-4 transition-transform" /> : null}
        {String(props.title ?? "")}
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-3 pl-5">{children}</CollapsibleContent>
    </UiCollapsible>
  );
};

export const RadioGroup: Renderer = ({ node, props, emit }) => {
  const items = opts(props.options);
  const controlled = has(props, "value");
  const [draft, setDraft] = useDraft<string | null>(controlled, (props.value as string) ?? null, (props.default as string | null) ?? null);
  return (
    <div className={cn("flex flex-col gap-2", props.cls as string)}>
      {props.label ? <Label>{String(props.label)}</Label> : null}
      <UiRadioGroup
        value={draft}
        disabled={Boolean(props.disabled)}
        onValueChange={(v) => {
          const next = v === null ? null : String(v);
          if (!controlled) setDraft(next);
          if (props.on_change) emit("change", next);
        }}
        className={props.orientation === "horizontal" ? "flex flex-row flex-wrap gap-4" : undefined}
      >
        {items.map((o) => {
          const id = `rg-${node.id}-${o.value}`;
          return (
            <div key={o.value} className="flex items-start gap-2">
              <RadioGroupItem id={id} value={o.value} disabled={Boolean(o.disabled)} />
              <div className="grid gap-0.5 leading-none">
                <Label htmlFor={id}>{o.label ?? o.value}</Label>
                {o.description ? <p className="text-xs text-muted-foreground">{o.description}</p> : null}
              </div>
            </div>
          );
        })}
      </UiRadioGroup>
    </div>
  );
};

export const CheckboxGroup: Renderer = ({ node, props, emit }) => {
  const items = opts(props.options);
  const controlled = has(props, "value");
  const [draft, setDraft] = useDraft<string[]>(controlled, (props.value as string[]) ?? [], (props.default as string[]) ?? []);
  const toggle = (value: string, on: boolean) => {
    const next = on ? [...draft.filter((v) => v !== value), value] : draft.filter((v) => v !== value);
    if (!controlled) setDraft(next);
    if (props.on_change) emit("change", next);
  };
  return (
    <div className={cn("flex flex-col gap-2", props.cls as string)}>
      {props.label ? <Label>{String(props.label)}</Label> : null}
      {items.map((o) => {
        const id = `cg-${node.id}-${o.value}`;
        return (
          <div key={o.value} className="flex items-start gap-2">
            <UiCheckbox
              id={id}
              checked={draft.includes(o.value)}
              disabled={Boolean(props.disabled) || Boolean(o.disabled)}
              onCheckedChange={(checked) => toggle(o.value, Boolean(checked))}
            />
            <div className="grid gap-0.5 leading-none">
              <Label htmlFor={id}>{o.label ?? o.value}</Label>
              {o.description ? <p className="text-xs text-muted-foreground">{o.description}</p> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export const ToggleGroup: Renderer = ({ props, emit }) => {
  const items = opts(props.options);
  const multiple = Boolean(props.multiple);
  const toArray = (v: unknown): string[] => (Array.isArray(v) ? (v as string[]) : typeof v === "string" ? [v] : []);
  const controlled = has(props, "value");
  const [draft, setDraft] = useDraft<string[]>(controlled, toArray(props.value), toArray(props.default));
  return (
    <UiToggleGroup
      multiple={multiple}
      value={draft}
      size={props.size === "sm" ? "sm" : props.size === "lg" ? "lg" : "default"}
      onValueChange={(v) => {
        const next = v as string[];
        if (!controlled) setDraft(next);
        if (props.on_change) emit("change", multiple ? next : (next[0] ?? null));
      }}
      className={props.cls as string}
    >
      {items.map((o) => {
        const Icon = icon(o.icon);
        return (
          <ToggleGroupItem key={o.value} value={o.value} disabled={Boolean(o.disabled)} aria-label={o.label ?? o.value}>
            {Icon ? <Icon /> : null}
            {o.label ?? (Icon ? null : o.value)}
          </ToggleGroupItem>
        );
      })}
    </UiToggleGroup>
  );
};

export const Sheet: Renderer = ({ props, children, emit }) => (
  <UiSheet
    open={Boolean(props.open)}
    disablePointerDismissal={props.dismissable === false}
    onOpenChange={(open) => {
      if (!open && props.dismissable !== false && props.on_close) emit("close");
    }}
  >
    <SheetContent side={(props.side as "left" | "right" | "top" | "bottom") ?? "right"} className={cn("flex flex-col gap-4", props.cls as string)}>
      {props.title || props.description ? (
        <SheetHeader>
          {props.title ? <SheetTitle>{String(props.title)}</SheetTitle> : null}
          {props.description ? <SheetDescription>{String(props.description)}</SheetDescription> : null}
        </SheetHeader>
      ) : null}
      <div className="flex flex-col gap-4 overflow-auto px-4 pb-4">{children}</div>
    </SheetContent>
  </UiSheet>
);

export const Slider: Renderer = ({ props, emit }) => {
  const controlled = has(props, "value");
  const min = typeof props.min === "number" ? props.min : 0;
  const max = typeof props.max === "number" ? props.max : 100;
  const [draft, setDraft] = useDraft<number>(controlled, Number(props.value ?? min), typeof props.default === "number" ? props.default : min);
  const marks = Array.isArray(props.marks) ? (props.marks as { value: number; label: string | null }[]) : [];
  const slider = (
    <UiSlider
      value={draft}
      min={min}
      max={max}
      step={typeof props.step === "number" ? props.step : 1}
      disabled={Boolean(props.disabled)}
      onValueChange={(v) => setDraft(Array.isArray(v) ? Number(v[0]) : Number(v))}
      onValueCommitted={(v) => {
        const n = Array.isArray(v) ? Number(v[0]) : Number(v);
        if (!controlled) setDraft(n);
        if (props.on_change) emit("change", n);
      }}
    />
  );
  return (
    <div className={cn("flex items-center gap-3", props.cls as string)}>
      {marks.length ? (
        <div className="flex min-w-0 grow flex-col gap-1">
          {slider}
          <div className="relative h-4 text-xs text-muted-foreground">
            {marks.map((m) => (
              <span
                key={m.value}
                className="absolute -translate-x-1/2 whitespace-nowrap first:translate-x-0 last:-translate-x-full"
                style={{ left: `${max > min ? ((m.value - min) / (max - min)) * 100 : 0}%` }}
              >
                {m.label ?? m.value}
              </span>
            ))}
          </div>
        </div>
      ) : (
        slider
      )}
      {props.show_value !== false ? <span className="w-10 text-right text-sm tabular-nums text-muted-foreground">{draft}</span> : null}
    </div>
  );
};

declare global {
  interface Window {
    __mwEmit?: (node: string, name: string, payload?: unknown) => void;
  }
}
