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
import { optionLabel } from "./option-label";
import { typedOption } from "./typed-option";
import { answerDue, caughtUp, type Told } from "../owned";
import { t } from "../theme";
import { Combobox as ComboboxPrimitive } from "@base-ui/react";
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
import { holdBack, request, type Ongoing } from "../ws";
import { Label } from "@/components/ui/label";

interface Opt {
  value: string;
  label?: string | null;
  description?: string | null;
  icon?: string | null;
  disabled?: boolean;
  group?: string | null;
  // The row that offers the text as typed, which is no option of the app's.
  typed?: boolean;
}

function opts(value: unknown): Opt[] {
  return Array.isArray(value) ? (value as Opt[]) : [];
}

// Options under the headings they name, in the order the headings first
// appear. Those that name none come under none.
export function grouped<T extends { group?: string | null }>(items: T[]): Array<{ group: string | null; items: T[] }> {
  const out: Array<{ group: string | null; items: T[] }> = [];
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

// A draft kept here. Controlled: the server's value is taken over whenever it
// changes (by content, so a value rebuilt on every render does not loop) and
// what the user does in between stays until then. Uncontrolled: the draft
// starts at `initial` and is the component's own. A field that shows what is
// typed before the server has it calls `tell` with each value it sends, so
// that the server's answer to it does not wipe out what was typed since.
export function useOwned<T>(controlled: boolean, value: T, initial: T): [T, (v: T) => void, (v: T) => void] {
  const [draft, setDraft] = useState<T>(controlled ? value : initial);
  const key = JSON.stringify(value);
  const seen = useRef(key);
  const told = useRef<Told[]>([]);
  useEffect(() => {
    if (!controlled || seen.current === key) return;
    seen.current = key;
    const next = caughtUp(told.current, key, performance.now());
    told.current = next.told;
    if (next.take) setDraft(value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controlled, key]);
  const tell = useCallback(
    (v: T) => {
      const sent = JSON.stringify(v);
      const now = performance.now();
      // What the server holds already it will not send back.
      if (controlled && answerDue(told.current, seen.current, sent, now)) told.current.push({ key: sent, at: now });
    },
    [controlled],
  );
  return [draft, setDraft, tell];
}

export interface Debounced {
  (fn: () => void): void;
  flush(): void;
}

// A debounce timer. `flush` runs what is pending now: before a submit, when
// the component goes away, and before anything else the tab sends, so the
// last change is never lost and never arrives after what followed it.
export function useDebounced(ms: number): Debounced {
  const timer = useRef<number | null>(null);
  const pending = useRef<(() => void) | null>(null);
  const release = useRef<(() => void) | null>(null);
  const flush = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
    release.current?.();
    release.current = null;
    const fn = pending.current;
    pending.current = null;
    if (fn) fn();
  }, []);
  useEffect(() => flush, [flush]);
  const later = useCallback(
    (fn: () => void) => {
      if (timer.current) window.clearTimeout(timer.current);
      pending.current = fn;
      release.current ??= holdBack(flush);
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
  // What the closed field shows for the chosen option, icon included.
  const labels = items.map((o) => ({ value: o.value, label: optionLabel(o) }));
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
                {optionLabel(o)}
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
  const [current, setDraft, tell] = useOwned<string>(controlled, String(props.value ?? ""), String(props.default ?? ""));
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
      autoFocus={Boolean(props.autofocus)}
      aria-describedby={counted ? countId : undefined}
      // In the box the field takes the height there is, for a box that was
      // given more than the field asks for.
      className={cn(props.autosize ? "field-sizing-content" : "resize-y", counted ? cn("grow", rest) : (props.cls as string))}
      onChange={(e) => {
        const next = e.target.value;
        setDraft(next);
        if (props.on_change)
          later(() => {
            tell(next);
            emit("change", next);
          });
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && props.on_submit) {
          later.flush();
          emit("submit", current);
          if (props.clear_on_submit) {
            // Emptied here and now, for the next entry: a handler that
            // cleared the value would do it a round trip later, on top of
            // what was typed meanwhile.
            setDraft("");
            if (props.on_change) {
              tell("");
              emit("change", "");
            }
          }
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
  const [current, setDraft, tell] = useOwned<string>(
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
    // As the server's value reads here: a number as text, none as no text.
    tell(value === null ? "" : String(value));
    emit("change", value);
  };
  return (
    <div className={cn("flex items-center gap-2", props.cls as string)} data-press="">
      <UiInput
        type="number"
        value={current}
        min={typeof props.min === "number" ? props.min : undefined}
        max={typeof props.max === "number" ? props.max : undefined}
        step={typeof props.step === "number" ? props.step : undefined}
        placeholder={props.placeholder ? String(props.placeholder) : undefined}
        disabled={Boolean(props.disabled)}
        autoFocus={Boolean(props.autofocus)}
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
// With `allow_custom` a last row offers the text as typed. Enter takes the row
// that is lit. With static options that is the first match as soon as there is
// text, and the typed text when it is the only row or the one moved to. With
// `on_search` the list is the answer to an earlier keystroke, so no row is lit
// until one is moved to, and Enter with none lit takes the text as typed.
export const Combobox: Renderer = ({ node, props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string | null>(controlled, (props.value as string | null) ?? null, (props.default as string | null) ?? null);
  const remote = Boolean(props.on_search);
  const staticItems = opts(props.options);
  const [results, setResults] = useState<Opt[]>([]);
  const [text, setText] = useState("");
  const later = useDebounced(150);
  const found = remote ? results : staticItems;
  // Labels of every option seen so far: a chosen item keeps its label after the
  // results move on, and a controlled value whose option came earlier still reads.
  const labels = useRef(new Map<string, string>());
  for (const o of [...found, ...staticItems]) labels.current.set(o.value, o.label ?? o.value);
  // One object per value: the primitive treats a new object as a new value and
  // would reset the typed text on every render.
  const selectedLabel = current === null ? null : (labels.current.get(current) ?? current);
  const selected = useMemo<Opt | null>(
    () => (current === null ? null : { value: current, label: selectedLabel }),
    [current, selectedLabel],
  );
  const allowCustom = Boolean(props.allow_custom);
  const typed = useMemo(() => (allowCustom ? typedOption(found, text, selected) : null), [allowCustom, found, text, selected]);
  const items = useMemo<Opt[]>(() => (typed ? [...found, typed] : found), [found, typed]);
  const { contains } = ComboboxPrimitive.useFilter();

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
  // Whether there is text typed since the last choice. A choice ends what was
  // typed, so leaving the field after one sends nothing more, also while a
  // controlled value has yet to follow.
  const typedSince = useRef(false);
  const choose = (next: string | null) => {
    typedSince.current = false;
    if (!controlled) setDraft(next);
    if (props.on_change) emit("change", next);
  };
  // Text that is typed and left becomes the value when custom entries are
  // allowed, as the option it names or as it stands. An option that is
  // disabled cannot be chosen by its name either.
  const commitCustom = () => {
    const left = text.trim();
    if (!allowCustom || !typedSince.current || !left || left === (selected?.label ?? selected?.value)) return;
    const match = found.find((o) => o.value === left || o.label === left);
    if (match?.disabled) return;
    choose(match ? match.value : left);
  };
  const lit = useRef(false);

  return (
    <UiCombobox
      items={items}
      value={selected}
      onValueChange={(v) => choose(v ? (v as Opt).value : null)}
      // The typed row stays whatever is typed. With `on_search` the server
      // has done the matching.
      filter={remote ? null : (o: Opt, query: string) => Boolean(o.typed) || contains(o.label ?? o.value, query)}
      autoHighlight={!remote}
      onItemHighlighted={(item: Opt | undefined) => {
        lit.current = item !== undefined;
      }}
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
        onChange={() => {
          typedSince.current = true;
        }}
        onKeyDown={(e: React.KeyboardEvent) => {
          if (e.key === "Enter" && !lit.current) commitCustom();
        }}
      />
      <ComboboxContent>
        <ComboboxEmpty>{t("no_results")}</ComboboxEmpty>
        <ComboboxList>
          {(item: Opt) => (
            <ComboboxItem key={item.typed ? "\u0000typed" : item.value} value={item} disabled={Boolean(item.disabled)}>
              {item.typed ? t("use_typed", { text: item.value }) : optionLabel(item)}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </UiCombobox>
  );
};
