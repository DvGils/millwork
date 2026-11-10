// Inputs backed by shadcn: select, checkbox, switch, textarea, number.
//
// Owner rule: a prop on the wire (`value`, `checked`) means the server owns
// the state and the control shows exactly that; the draft lives here only
// when the key is absent.

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type React from "react";
import type { Renderer } from "../render";
import { cn } from "cn";
import { has, placed } from "../lib";
import { icon } from "../icons";
import { t } from "../theme";
import {
  Select as UiSelect,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox as UiCheckbox } from "@/components/ui/checkbox";
import { Switch as UiSwitch } from "@/components/ui/switch";
import { Textarea as UiTextarea } from "@/components/ui/textarea";
import { Input as UiInput } from "@/components/ui/input";
import {
  Combobox as UiCombobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { request, type Ongoing } from "../ws";
import { Label } from "@/components/ui/label";

interface Opt {
  value: string;
  label?: string | null;
  description?: string | null;
  disabled?: boolean;
  group?: string | null;
}

function opts(value: unknown): Opt[] {
  return Array.isArray(value) ? (value as Opt[]) : [];
}

function grouped(items: Opt[]): Array<{ group: string | null; items: Opt[] }> {
  const out: Array<{ group: string | null; items: Opt[] }> = [];
  for (const it of items) {
    const g = it.group ?? null;
    let bucket = out.find((b) => b.group === g);
    if (!bucket) {
      bucket = { group: g, items: [] };
      out.push(bucket);
    }
    bucket.items.push(it);
  }
  return out;
}

// A draft kept here. Controlled: the server's value is taken over whenever it
// changes (by content, so a value rebuilt on every render does not loop) and
// what the user does in between stays until then. Uncontrolled: the draft
// starts at `initial` and is the component's own.
// A password field with a button that shows what was typed, for whoever is
// typing it. The same field serves ui.Input, a form's password widget and
// the sign-in form. Shown, it is a text field to the browser, which would
// spellcheck it and may send what it checks to a service: never a password.
export function PasswordInput({ className, type: _type, ...props }: React.ComponentProps<"input">) {
  const [shown, setShown] = useState(false);
  const Eye = icon(shown ? "eye-off" : "eye");
  return (
    <div className="relative flex w-full items-center">
      <UiInput type={shown ? "text" : "password"} className={cn("pr-8", className)} {...props} spellCheck={false} />
      {Eye ? (
        <button
          type="button"
          aria-label={t("show_password")}
          aria-pressed={shown}
          onClick={() => setShown((s) => !s)}
          disabled={props.disabled}
          className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm text-muted-foreground hover:text-foreground disabled:pointer-events-none"
        >
          <Eye className="size-4" />
        </button>
      ) : null}
    </div>
  );
}

export function useOwned<T>(controlled: boolean, value: T, initial: T): [T, (v: T) => void] {
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

export interface Debounced {
  (fn: () => void): void;
  flush(): void;
}

// A debounce timer. `flush` runs what is pending now (before a submit, and when
// the component goes away, so the last change is never lost).
export function useDebounced(ms: number): Debounced {
  const timer = useRef<number | null>(null);
  const pending = useRef<(() => void) | null>(null);
  const flush = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
    const fn = pending.current;
    pending.current = null;
    if (fn) fn();
  }, []);
  useEffect(() => flush, [flush]);
  const later = useCallback(
    (fn: () => void) => {
      if (timer.current) window.clearTimeout(timer.current);
      pending.current = fn;
      timer.current = window.setTimeout(flush, ms);
    },
    [flush, ms],
  ) as Debounced;
  later.flush = flush;
  return later;
}

export const Select: Renderer = ({ props, emit }) => {
  const items = opts(props.options);
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string | null>(controlled, (props.value as string | null) ?? null, (props.default as string | null) ?? null);
  const labels = items.map((o) => ({ value: o.value, label: o.label ?? o.value }));
  const Clear = icon("x");
  const clearable = Boolean(props.clearable) && current !== null && !props.disabled;
  const clear = () => {
    if (!controlled) setDraft(null);
    if (props.on_change) emit("change", null);
  };
  const select = (
    <UiSelect
      items={labels}
      value={current}
      onValueChange={(v) => {
        const next = v === null ? null : String(v);
        if (!controlled) setDraft(next);
        if (props.on_change) emit("change", next);
      }}
      disabled={Boolean(props.disabled)}
    >
      <SelectTrigger className={cn("w-full", clearable && "pr-8", props.cls as string)}>
        <SelectValue placeholder={props.placeholder ? String(props.placeholder) : undefined} />
      </SelectTrigger>
      <SelectContent>
        {grouped(items).map((bucket, i) => (
          <SelectGroup key={bucket.group ?? i}>
            {bucket.group ? <SelectLabel>{bucket.group}</SelectLabel> : null}
            {bucket.items.map((o) => (
              <SelectItem key={o.value} value={o.value} disabled={Boolean(o.disabled)}>
                {o.label ?? o.value}
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </UiSelect>
  );
  if (!props.clearable) return select;
  return (
    <div className="relative">
      {select}
      {clearable && Clear ? (
        <button
          type="button"
          aria-label={t("clear")}
          onClick={clear}
          className="absolute top-1/2 right-8 -translate-y-1/2 rounded-sm text-muted-foreground hover:text-foreground"
        >
          <Clear className="size-4" />
        </button>
      ) : null}
    </div>
  );
};

export const Checkbox: Renderer = ({ node, props, emit }) => {
  const controlled = has(props, "checked");
  const [current, setDraft] = useOwned<boolean>(controlled, Boolean(props.checked), Boolean(props.default_checked));
  const id = `cb-${node.id}`;
  return (
    <div className={cn("flex items-start gap-2", props.cls as string)}>
      <UiCheckbox
        id={id}
        checked={current}
        disabled={Boolean(props.disabled)}
        onCheckedChange={(checked) => {
          const next = Boolean(checked);
          if (!controlled) setDraft(next);
          if (props.on_change) emit("change", next);
        }}
      />
      {props.label || props.description ? (
        <div className="grid gap-0.5 leading-none">
          {props.label ? <Label htmlFor={id}>{String(props.label)}</Label> : null}
          {props.description ? <p className="text-xs text-muted-foreground">{String(props.description)}</p> : null}
        </div>
      ) : null}
    </div>
  );
};

export const Switch: Renderer = ({ node, props, emit }) => {
  const controlled = has(props, "checked");
  const [current, setDraft] = useOwned<boolean>(controlled, Boolean(props.checked), Boolean(props.default_checked));
  const id = `sw-${node.id}`;
  return (
    <div className={cn("flex items-center gap-2", props.cls as string)}>
      <UiSwitch
        id={id}
        checked={current}
        disabled={Boolean(props.disabled)}
        onCheckedChange={(checked) => {
          const next = Boolean(checked);
          if (!controlled) setDraft(next);
          if (props.on_change) emit("change", next);
        }}
      />
      {props.label ? (
        <div className="grid gap-0.5 leading-none">
          <Label htmlFor={id}>{String(props.label)}</Label>
          {props.description ? <p className="text-xs text-muted-foreground">{String(props.description)}</p> : null}
        </div>
      ) : null}
    </div>
  );
};

// The limit a field was given, when it is one a field can have.
export function limitOf(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;
}

// How much a text field holds, against its limit when it has one. The length
// is counted the way the browser counts it for `maxlength`, so the two agree
// on when the field is full.
export function Count({ id, length, max }: { id?: string; length: number; max?: number }) {
  const full = max !== undefined && length >= max;
  return (
    <p id={id} data-slot="count" data-full={full || undefined} className={cn("mt-1 text-right text-xs whitespace-nowrap tabular-nums", full ? "text-destructive" : "text-muted-foreground")}>
      {max !== undefined ? `${length} / ${max}` : length}
    </p>
  );
}

// Text controls: a controlled one shows the server's value and emits each change
// (debounced); an uncontrolled one keeps its draft and emits the same way.
export const Textarea: Renderer = ({ props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string>(controlled, String(props.value ?? ""), String(props.default ?? ""));
  const later = useDebounced(typeof props.debounce_ms === "number" ? props.debounce_ms : 250);
  const max = limitOf(props.max_length);
  const countId = useId();
  const counted = Boolean(props.counter);
  // With a count under it the field is in a box. The box takes over the
  // classes that place the field among its neighbours, and the field keeps
  // the rest, so a class does with a count what it does without one.
  const { box, rest } = placed(props.cls);
  const field = (
    <UiTextarea
      value={current}
      rows={typeof props.rows === "number" ? props.rows : 3}
      maxLength={max}
      spellCheck={typeof props.spellcheck === "boolean" ? props.spellcheck : undefined}
      placeholder={props.placeholder ? String(props.placeholder) : undefined}
      disabled={Boolean(props.disabled)}
      readOnly={Boolean(props.readonly)}
      aria-describedby={counted ? countId : undefined}
      // In the box the field takes the height there is, for a box that was
      // given more than the field asks for.
      className={cn(props.autosize ? "field-sizing-content" : "resize-y", counted ? cn("grow", rest) : (props.cls as string))}
      onChange={(e) => {
        const next = e.target.value;
        setDraft(next);
        if (props.on_change) later(() => emit("change", next));
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && props.on_submit) {
          later.flush();
          emit("submit", current);
        }
      }}
    />
  );
  if (!counted) return field;
  return (
    <div className={cn("flex w-full flex-col", box)}>
      {field}
      <Count id={countId} length={current.length} max={max} />
    </div>
  );
};

export const NumberInput: Renderer = ({ props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string>(
    controlled,
    props.value === null || props.value === undefined ? "" : String(props.value),
    typeof props.default === "number" ? String(props.default) : "",
  );
  const parse = (s: string): number | null => {
    if (s === "") return null;
    const n = Number(s);
    return Number.isNaN(n) ? null : n;
  };
  // Enter reports, and so does leaving the field. The value the server last
  // heard is not sent again, so Enter and then Tab is one change, not two.
  const sent = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    sent.current = undefined;
  }, [props.value]);
  const report = () => {
    if (!props.on_change) return;
    const value = parse(current);
    if (sent.current !== undefined && sent.current === value) return;
    sent.current = value;
    emit("change", value);
  };
  return (
    <div className={cn("flex items-center gap-2", props.cls as string)}>
      <UiInput
        type="number"
        value={current}
        min={typeof props.min === "number" ? props.min : undefined}
        max={typeof props.max === "number" ? props.max : undefined}
        step={typeof props.step === "number" ? props.step : undefined}
        placeholder={props.placeholder ? String(props.placeholder) : undefined}
        disabled={Boolean(props.disabled)}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={report}
        onKeyDown={(e) => {
          if (e.key === "Enter") report();
        }}
      />
      {props.suffix ? <span className="text-sm text-muted-foreground">{String(props.suffix)}</span> : null}
    </div>
  );
};

// Combobox: static `options` filter in the tab; with `on_search` every change of the
// text (debounced) asks the server over the socket and shows what comes back.
export const Combobox: Renderer = ({ node, props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string | null>(controlled, (props.value as string | null) ?? null, (props.default as string | null) ?? null);
  const remote = Boolean(props.on_search);
  const staticItems = opts(props.options);
  const [results, setResults] = useState<Opt[]>([]);
  const [text, setText] = useState("");
  const later = useDebounced(150);
  const items = remote ? results : staticItems;
  // Labels of every option seen so far: a chosen item keeps its label after the
  // results move on, and a controlled value whose option came earlier still reads.
  const labels = useRef(new Map<string, string>());
  for (const o of [...items, ...staticItems]) labels.current.set(o.value, o.label ?? o.value);
  // One object per value: the primitive treats a new object as a new value and
  // would reset the typed text on every render.
  const selectedLabel = current === null ? null : (labels.current.get(current) ?? current);
  const selected = useMemo<Opt | null>(
    () => (current === null ? null : { value: current, label: selectedLabel }),
    [current, selectedLabel],
  );
  const allowCustom = Boolean(props.allow_custom);

  // One search in flight: a newer one cancels the older, whose answer (or
  // "cancelled") must not touch the list.
  const inflight = useRef<Ongoing<unknown> | null>(null);
  const search = (q: string) => {
    inflight.current?.cancel();
    const mine = request(node.id, "search", q);
    inflight.current = mine;
    mine
      .then((r) => {
        if (inflight.current === mine) setResults(opts(r));
      })
      .catch(() => {
        if (inflight.current === mine) setResults([]);
      })
      .finally(() => {
        if (inflight.current === mine) inflight.current = null;
      });
  };
  useEffect(() => () => inflight.current?.cancel(), []);
  const choose = (next: string | null) => {
    if (!controlled) setDraft(next);
    if (props.on_change) emit("change", next);
  };
  // Typed text that matches no option becomes the value when custom entries are allowed.
  const commitCustom = () => {
    const typed = text.trim();
    if (!allowCustom || !typed || typed === (selected?.label ?? selected?.value)) return;
    const match = items.find((o) => o.value === typed || o.label === typed);
    choose(match ? match.value : typed);
  };

  return (
    <UiCombobox
      items={items}
      value={selected}
      onValueChange={(v) => choose(v ? (v as Opt).value : null)}
      filter={remote || allowCustom ? null : undefined}
      itemToStringLabel={(o: Opt) => o.label ?? o.value}
      isItemEqualToValue={(a: Opt, b: Opt) => a.value === b.value}
      onInputValueChange={(s: string) => {
        setText(s);
        if (remote) later(() => search(s));
      }}
      onOpenChange={(open: boolean) => {
        if (open && remote && results.length === 0) search(text);
      }}
      disabled={Boolean(props.disabled)}
    >
      <ComboboxInput
        placeholder={props.placeholder ? String(props.placeholder) : undefined}
        showClear={Boolean(props.clearable) && current !== null}
        className={cn("w-full", props.cls as string)}
        onBlur={commitCustom}
        onKeyDown={(e: React.KeyboardEvent) => {
          if (e.key === "Enter") commitCustom();
        }}
      />
      <ComboboxContent>
        <ComboboxEmpty>{t("no_results")}</ComboboxEmpty>
        <ComboboxList>
          {(item: Opt) => (
            <ComboboxItem key={item.value} value={item} disabled={Boolean(item.disabled)}>
              {item.label ?? item.value}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </UiCombobox>
  );
};
