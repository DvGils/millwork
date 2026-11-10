// Choices and dates: MultiSelect (chips over a combobox), DatePicker (a calendar
// in a popover), DropdownMenu, ButtonGroup and Field.

import { useMemo, useRef, useState } from "react";
import type { Renderer } from "../render";
import { Slot, isSlot } from "../render";
import { useNode } from "../store";
import { cn } from "cn";
import { has } from "../lib";
import { icon } from "../icons";
import { t, locale } from "../theme";
import { useOwned } from "./inputs";
import { optionLabel } from "./option-label";
import { SortableChips } from "./sortable-chips";
import { Button as UiButton } from "@/components/ui/button";
import {
  Combobox as UiCombobox,
  ComboboxChip,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxItem,
  ComboboxList,
  ComboboxValue,
  useComboboxAnchor,
} from "@/components/ui/combobox";
import { Calendar } from "@/components/ui/calendar";
import type { Matcher } from "react-day-picker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  DropdownMenu as UiDropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field as UiField, FieldContent, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";

interface Opt {
  value: string;
  label?: string | null;
  icon?: string | null;
  disabled?: boolean;
}

interface MenuItem {
  id: string;
  label: string;
  icon?: string | null;
  disabled?: boolean;
  destructive?: boolean;
  separator_after?: boolean;
}

const asStrings = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

// Several choices as chips; the list filters on what is typed. `max` stops
// further picks without touching what is chosen. The chips keep the order
// they were picked in; `sortable` lets that order be changed by hand.
export function MultiSelectControl({
  options,
  value,
  onChange,
  placeholder,
  max,
  sortable,
  disabled,
  invalid,
  id,
}: {
  options: Opt[];
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  max?: number | null;
  sortable?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  id?: string;
}) {
  const anchor = useComboboxAnchor();
  const [open, setOpen] = useState(false);
  const byValue = useMemo(() => new Map(options.map((o) => [o.value, o])), [options]);
  const selected = useMemo(() => value.map((v) => byValue.get(v) ?? { value: v, label: v }), [value, byValue]);
  const full = typeof max === "number" && value.length >= max;
  const items = useMemo(() => (full ? options.filter((o) => value.includes(o.value)) : options), [full, options, value]);
  return (
    <UiCombobox
      multiple
      items={items}
      value={selected}
      onValueChange={(next: Opt[]) => onChange(next.map((o) => o.value))}
      itemToStringLabel={(o: Opt) => o.label ?? o.value}
      isItemEqualToValue={(a: Opt, b: Opt) => a.value === b.value}
      disabled={disabled}
      open={open}
      onOpenChange={setOpen}
    >
      <ComboboxChips ref={anchor} className="w-full" aria-invalid={invalid || undefined}>
        <ComboboxValue>
          {(chosen: Opt[]) => (
            <>
              {sortable ? (
                <SortableChips chips={chosen.map((o) => ({ value: o.value, label: o.label ?? o.value, icon: o.icon }))} onReorder={onChange} disabled={disabled} />
              ) : (
                chosen.map((o) => (
                  <ComboboxChip key={o.value}>{optionLabel(o, "size-3")}</ComboboxChip>
                ))
              )}
              <ComboboxChipsInput
                id={id}
                placeholder={chosen.length ? undefined : placeholder}
                onKeyDown={(e: React.KeyboardEvent & { preventBaseUIHandler?: () => void }) => {
                  // Escape closes the list and nothing more: the primitive would
                  // also drop every chosen chip.
                  if (e.key === "Escape") {
                    e.preventBaseUIHandler?.();
                    setOpen(false);
                  }
                }}
              />
            </>
          )}
        </ComboboxValue>
      </ComboboxChips>
      <ComboboxContent anchor={anchor}>
        <ComboboxEmpty>{t("no_results")}</ComboboxEmpty>
        <ComboboxList>
          {(item: Opt) => (
            <ComboboxItem key={item.value} value={item} disabled={Boolean(item.disabled)}>
              {optionLabel(item)}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </UiCombobox>
  );
}

export const MultiSelect: Renderer = ({ props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string[]>(controlled, asStrings(props.value), asStrings(props.default));
  return (
    <div className={props.cls as string}>
      <MultiSelectControl
        options={Array.isArray(props.options) ? (props.options as Opt[]) : []}
        value={current}
        placeholder={props.placeholder ? String(props.placeholder) : undefined}
        max={typeof props.max === "number" ? props.max : null}
        sortable={Boolean(props.sortable)}
        disabled={Boolean(props.disabled)}
        onChange={(next) => {
          if (!controlled) setDraft(next);
          if (props.on_change) emit("change", next);
        }}
      />
    </div>
  );
};

// ISO dates on the wire; Date objects only inside the calendar, at local midnight
// so the day shown is the day named.
function parseIso(s: unknown): Date | undefined {
  if (typeof s !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(s)) return undefined;
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}
function toIso(d: Date | undefined): string | null {
  if (!d) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function showDate(iso: string | null | undefined): string {
  const d = parseIso(iso);
  return d ? d.toLocaleDateString(locale(), { year: "numeric", month: "short", day: "numeric" }) : "";
}

export function DatePickerControl({
  value,
  onChange,
  range,
  min,
  max,
  placeholder,
  clearable,
  disabled,
  invalid,
  id,
}: {
  value: string | (string | null)[] | null;
  onChange: (next: string | (string | null)[] | null) => void;
  range?: boolean;
  min?: string | null;
  max?: string | null;
  placeholder?: string;
  clearable?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  id?: string;
}) {
  const [open, setOpen] = useState(false);
  const Cal = icon("calendar");
  const Clear = icon("x");
  const disabledDays: Matcher[] = [];
  const before = parseIso(min);
  const after = parseIso(max);
  if (before) disabledDays.push({ before });
  if (after) disabledDays.push({ after });
  const text = range
    ? Array.isArray(value) && (value[0] || value[1])
      ? `${showDate(value[0])} – ${showDate(value[1])}`
      : ""
    : showDate(typeof value === "string" ? value : null);
  const empty = text === "";
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div className="relative flex w-full items-center">
        <PopoverTrigger
          render={
            <UiButton id={id} type="button" variant="outline" disabled={disabled} aria-invalid={invalid || undefined} className={cn("w-full justify-start font-normal", empty && "text-muted-foreground", clearable && !empty && "pr-8")} />
          }
        >
          {Cal ? <Cal className="text-muted-foreground" /> : null}
          {empty ? (placeholder ?? t("choose")) : text}
        </PopoverTrigger>
        {clearable && !empty && !disabled && Clear ? (
          <button type="button" aria-label={t("clear")} className="absolute right-2.5 text-muted-foreground hover:text-foreground" onClick={() => onChange(null)}>
            <Clear className="size-4" />
          </button>
        ) : null}
      </div>
      <PopoverContent className="w-auto p-0" align="start">
        {range ? (
          <Calendar
            mode="range"
            selected={Array.isArray(value) ? { from: parseIso(value[0]), to: parseIso(value[1]) } : undefined}
            disabled={disabledDays}
            defaultMonth={Array.isArray(value) ? parseIso(value[0]) : undefined}
            onSelect={(r) => {
              onChange(r && (r.from || r.to) ? [toIso(r.from), toIso(r.to)] : null);
              // The first click reports a one-day range; the popover stays for the second.
              if (r?.from && r?.to && r.from.getTime() !== r.to.getTime()) setOpen(false);
            }}
          />
        ) : (
          <Calendar
            mode="single"
            selected={parseIso(typeof value === "string" ? value : null)}
            defaultMonth={parseIso(typeof value === "string" ? value : null)}
            disabled={disabledDays}
            onSelect={(d) => {
              onChange(toIso(d));
              setOpen(false);
            }}
          />
        )}
      </PopoverContent>
    </Popover>
  );
}

export const DatePicker: Renderer = ({ props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string | (string | null)[] | null>(
    controlled,
    (props.value as string | (string | null)[] | null) ?? null,
    (props.default as string | (string | null)[] | null) ?? null,
  );
  return (
    <div className={props.cls as string}>
      <DatePickerControl
        value={current}
        range={Boolean(props.range)}
        min={props.min as string | null}
        max={props.max as string | null}
        placeholder={props.placeholder ? String(props.placeholder) : undefined}
        clearable={Boolean(props.clearable)}
        disabled={Boolean(props.disabled)}
        onChange={(next) => {
          if (!controlled) setDraft(next);
          if (props.on_change) emit("change", next);
        }}
      />
    </div>
  );
};

// The trigger is a Button node in a slot: its props draw the real trigger
// element, so the menu's own handlers land on one button, not a button in a button.
export const DropdownMenu: Renderer = ({ props, emit }) => {
  const triggerId = isSlot(props.trigger) ? (props.trigger as { $node: string }).$node : null;
  const trigger = useNode(triggerId ?? "");
  const items = Array.isArray(props.items) ? (props.items as MenuItem[]) : [];
  const tp = trigger?.props ?? {};
  const Icon = icon(tp.icon);
  const variants: Record<string, "default" | "secondary" | "outline" | "ghost" | "link" | "destructive"> = {
    primary: "default", secondary: "secondary", outline: "outline", ghost: "ghost", link: "link", destructive: "destructive",
  };
  const sizes: Record<string, "sm" | "default" | "lg"> = { sm: "sm", md: "default", lg: "lg" };
  return (
    <UiDropdownMenu>
      <DropdownMenuTrigger
        render={
          <UiButton
            variant={variants[String(tp.variant ?? "outline")]}
            size={sizes[String(tp.size ?? "md")]}
            disabled={Boolean(tp.disabled) || Boolean(props.disabled)}
            className={cn(tp.cls as string, props.cls as string)}
          />
        }
      >
        {Icon && tp.icon_position !== "end" ? <Icon /> : null}
        {trigger ? String(tp.label ?? "") : <Slot value={props.trigger} />}
        {Icon && tp.icon_position === "end" ? <Icon /> : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align={props.align === "end" ? "end" : "start"}>
        {items.map((item) => {
          const ItemIcon = icon(item.icon);
          return (
            <div key={item.id} className="contents">
              <DropdownMenuItem disabled={Boolean(item.disabled)} variant={item.destructive ? "destructive" : "default"} onClick={() => props.on_select && emit("select", item.id)}>
                {ItemIcon ? <ItemIcon /> : null}
                {item.label}
              </DropdownMenuItem>
              {item.separator_after ? <DropdownMenuSeparator /> : null}
            </div>
          );
        })}
      </DropdownMenuContent>
    </UiDropdownMenu>
  );
};

export const ButtonGroup: Renderer = ({ props, children }) => (
  <div
    role="group"
    className={cn(
      // By data-slot, not by tag: a button with an href is an anchor.
      "inline-flex items-stretch [&>*>[data-slot=button]]:rounded-none [&>*:first-child>[data-slot=button]]:rounded-l-md [&>*:last-child>[data-slot=button]]:rounded-r-md [&>*:not(:first-child)>[data-slot=button]]:-ml-px [&>*>[data-slot=button]]:relative [&>*>[data-slot=button]:focus-visible]:z-10",
      props.cls as string,
    )}
  >
    {children}
  </div>
);

export const Field: Renderer = ({ props, children }) => {
  const error = props.error ? String(props.error) : null;
  return (
    <UiField data-invalid={error ? true : undefined} className={props.cls as string}>
      <FieldLabel>
        {String(props.label ?? "")}
        {props.required ? <span className="text-destructive"> *</span> : null}
      </FieldLabel>
      <FieldContent>
        {children}
        {props.help ? <FieldDescription>{String(props.help)}</FieldDescription> : null}
        {error ? <FieldError>{error}</FieldError> : null}
      </FieldContent>
    </UiField>
  );
};
