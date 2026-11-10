// The Form: a field spec from Python, a draft kept here, issues by JSON pointer.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from "react";
import type { Renderer } from "../render";
import { cn } from "cn";
import { icon } from "../icons";
import { Count, limitOf, PasswordInput } from "./inputs";
import { t } from "../theme";
import { onStatus } from "../ws";
import { formatSize, upload, type FileRef } from "./files";
import { DatePickerControl, MultiSelectControl } from "./choices";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Opt {
  value: string | number | boolean;
  label: string;
}

interface FieldSpec {
  name: string;
  pointer: string;
  label: string;
  help?: string | null;
  placeholder?: string | null;
  required?: boolean;
  default?: unknown;
  group?: string | null;
  widget: string;
  options?: Opt[];
  clearable?: boolean;
  max_length?: number;
  counter?: boolean;
  rows?: number;
  integer?: boolean;
  min?: number;
  max?: number;
  step?: number;
  item?: FieldSpec;
  item_label?: string;
  accept?: string[] | null;
  max_files?: number;
  max_items?: number | null;
  sortable?: boolean;
  min_date?: string | null;
  max_date?: string | null;
  fields?: FieldSpec[];
  title?: string | null;
  discriminator?: string | null;
  variants?: { tag: string; label: string; fields: FieldSpec[] }[];
}

interface Issue {
  pointer: string;
  message: string;
}

type Draft = Record<string, unknown>;

// ------------------------------------------------------------- pointers

export function parts(pointer: string): string[] {
  return pointer.split("/").slice(1).map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
}

export function getAt(obj: unknown, pointer: string): unknown {
  let cur: unknown = obj;
  for (const p of parts(pointer)) {
    if (cur === null || cur === undefined) return undefined;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}

export function setAt(obj: unknown, pointer: string, value: unknown): unknown {
  const ps = parts(pointer);
  const walk = (cur: unknown, i: number): unknown => {
    if (i === ps.length) return value;
    const key = ps[i];
    const isIndex = /^\d+$/.test(key);
    const base = cur === null || cur === undefined ? (isIndex ? [] : {}) : cur;
    if (Array.isArray(base)) {
      const copy = [...base];
      copy[Number(key)] = walk(copy[Number(key)], i + 1);
      return copy;
    }
    const copy = { ...(base as Record<string, unknown>) };
    copy[key] = walk(copy[key], i + 1);
    return copy;
  };
  return walk(obj, 0);
}

function defaultFor(f: FieldSpec): unknown {
  if (f.default !== undefined) return f.default;
  switch (f.widget) {
    case "fieldset":
      return defaults(f.fields ?? []);
    case "list":
    case "tags":
    case "checkboxes":
    case "multiselect":
    case "files":
      return [];
    case "file":
      return null;
    case "switch":
    case "checkbox":
      return false;
    case "union": {
      const v = f.variants?.[0];
      return v ? { ...(defaults(v.fields)), ...(f.discriminator ? { [f.discriminator]: v.tag } : {}) } : null;
    }
    default:
      return f.clearable ? null : f.required ? "" : null;
  }
}

export function defaults(fields: FieldSpec[]): Draft {
  const out: Draft = {};
  for (const f of fields) out[f.name] = defaultFor(f);
  return out;
}

function itemDefault(item: FieldSpec | undefined): unknown {
  if (!item) return null;
  return defaultFor(item);
}

// Pointers inside a list item or variant are schema pointers; the draft pointer
// substitutes the index. rebase("/ops/0", "/ops/source") -> "/ops/0/source".
export function rebase(base: string, schemaPointer: string, schemaBase: string): string {
  return base + schemaPointer.slice(schemaBase.length);
}

// ------------------------------------------------------------- the component

export const Form: Renderer = ({ node, props, emit }) => {
  const schema = (props.schema ?? { fields: [] }) as { title?: string; fields: FieldSpec[] };
  const initial = (props.initial ?? null) as Draft | null;
  const serverIssues = (Array.isArray(props.issues) ? (props.issues as Issue[]) : []);
  const readOnly = Boolean(props.read_only);
  const disabled = Boolean(props.disabled);

  const start = useMemo(() => ({ ...defaults(schema.fields), ...(initial ?? {}) }), [schema, initial]);
  const [draft, setDraft] = useState<Draft>(start);
  const [dirty, setDirty] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [submitting, setSubmitting] = useState(false);

  // A new `initial` replaces a clean draft, never a dirty one.
  useEffect(() => {
    if (!dirty) setDraft(start);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start]);

  // A reconnect means the pending submit may never be answered: let the user try again.
  useEffect(() => onStatus((s) => s !== "open" && setSubmitting(false)), []);

  useEffect(() => {
    const onIssues = (e: Event) => {
      const d = (e as CustomEvent<{ node: string; issues: Issue[] }>).detail;
      if (d.node !== node.id) return;
      setIssues(d.issues);
      setSubmitting(false);
      if (d.issues.length === 0) setDirty(false);
    };
    window.addEventListener("mw:form-issues", onIssues);
    return () => window.removeEventListener("mw:form-issues", onIssues);
  }, [node.id]);

  const allIssues = useMemo(() => [...serverIssues, ...issues], [serverIssues, issues]);
  const issueFor = useCallback((pointer: string) => allIssues.filter((i) => i.pointer === pointer), [allIssues]);

  const update = useCallback((pointer: string, value: unknown) => {
    setDraft((d) => setAt(d, pointer, value) as Draft);
    setDirty(true);
  }, []);

  const submit = () => {
    if (!props.on_submit || submitting || disabled || readOnly) return;
    setSubmitting(true);
    emit("submit", draft);
  };

  const layout = props.layout;
  const orientation = layout === "horizontal" ? "horizontal" : "vertical";
  const gridCols = typeof layout === "number" ? layout : 0;
  const ctx: Ctx = { node: node.id, draft, update, issueFor, disabled: disabled || readOnly, readOnly, orientation, dense: Boolean(props.dense) };

  return (
    <form
      id={props.form_id ? `mw-form-${String(props.form_id)}` : undefined}
      className={cn("flex flex-col gap-5", props.cls as string)}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <FieldGroup className={cn(gridCols > 0 && "grid gap-4", gridCols === 2 && "md:grid-cols-2", gridCols === 3 && "md:grid-cols-3", gridCols === 4 && "md:grid-cols-4")}>
        <Fields fields={schema.fields} base="" schemaBase="" ctx={ctx} />
      </FieldGroup>
      {issueFor("").length ? <FieldError errors={issueFor("")} /> : null}
      {props.submit || props.cancel ? (
        <div className="flex items-center gap-2">
          {props.submit ? (
            <Button type="submit" disabled={disabled || readOnly || submitting}>
              {String(props.submit)}
            </Button>
          ) : null}
          {props.cancel ? (
            <Button type="button" variant="outline" onClick={() => props.on_cancel && emit("cancel")}>
              {String(props.cancel)}
            </Button>
          ) : null}
        </div>
      ) : null}
    </form>
  );
};

interface Ctx {
  node: string;
  draft: Draft;
  update: (pointer: string, value: unknown) => void;
  issueFor: (pointer: string) => Issue[];
  disabled: boolean;
  readOnly: boolean;
  orientation: "vertical" | "horizontal";
  dense: boolean;
}

// Renders a list of fields whose schema pointers start at `schemaBase`, into the
// draft at `base`. Grouped fields become fieldsets in order of first appearance.
function Fields({ fields, base, schemaBase, ctx }: { fields: FieldSpec[]; base: string; schemaBase: string; ctx: Ctx }) {
  const groups: { name: string | null; fields: FieldSpec[] }[] = [];
  for (const f of fields) {
    const g = f.group ?? null;
    let bucket = groups.find((b) => b.name === g);
    if (!bucket) {
      bucket = { name: g, fields: [] };
      groups.push(bucket);
    }
    bucket.fields.push(f);
  }
  return (
    <>
      {groups.map((g, i) =>
        g.name ? (
          <FieldSet key={g.name}>
            <FieldLegend>{g.name}</FieldLegend>
            <FieldGroup>
              {g.fields.map((f) => (
                <OneField key={f.pointer} f={f} base={base} schemaBase={schemaBase} ctx={ctx} />
              ))}
            </FieldGroup>
          </FieldSet>
        ) : (
          g.fields.map((f) => <OneField key={`${i}:${f.pointer}`} f={f} base={base} schemaBase={schemaBase} ctx={ctx} />)
        ),
      )}
    </>
  );
}

function OneField({ f, base, schemaBase, ctx }: { f: FieldSpec; base: string; schemaBase: string; ctx: Ctx }) {
  const pointer = rebase(base, f.pointer, schemaBase);
  const value = getAt(ctx.draft, pointer);
  const errors = ctx.issueFor(pointer);
  const invalid = errors.length > 0;
  const set = (v: unknown) => ctx.update(pointer, v);
  const id = `f${pointer.replace(/[^a-zA-Z0-9]/g, "_")}`;

  if (f.widget === "hidden") return null;

  if (f.widget === "fieldset") {
    return (
      <FieldSet>
        <FieldLegend>{f.title ?? f.label}</FieldLegend>
        {f.help ? <FieldDescription>{f.help}</FieldDescription> : null}
        <FieldGroup>
          <Fields fields={f.fields ?? []} base={pointer} schemaBase={f.pointer} ctx={ctx} />
        </FieldGroup>
        {invalid ? <FieldError errors={errors} /> : null}
      </FieldSet>
    );
  }

  if (f.widget === "list") {
    const items = Array.isArray(value) ? (value as unknown[]) : [];
    const Plus = icon("plus");
    const Trash = icon("trash-2");
    return (
      <FieldSet>
        <FieldLegend>{f.label}</FieldLegend>
        {f.help ? <FieldDescription>{f.help}</FieldDescription> : null}
        <div className="flex flex-col gap-(--mw-field-gap)">
          {items.map((_, i) => {
            const itemPointer = `${pointer}/${i}`;
            return (
              <div key={i} className="flex items-start gap-2 rounded-lg border p-3">
                <div className="flex grow flex-col gap-3">
                  <ItemField item={f.item!} pointer={itemPointer} schemaPointer="" ctx={ctx} />
                </div>
                {!ctx.disabled ? (
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={t("remove")} onClick={() => set(items.filter((__, j) => j !== i))}>
                    {Trash ? <Trash /> : "×"}
                  </Button>
                ) : null}
              </div>
            );
          })}
          {!ctx.disabled ? (
            <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => set([...items, itemDefault(f.item)])}>
              {Plus ? <Plus /> : null}
              {f.item_label ? `Add ${f.item_label.toLowerCase()}` : "Add"}
            </Button>
          ) : null}
        </div>
        {invalid ? <FieldError errors={errors} /> : null}
      </FieldSet>
    );
  }

  if (f.widget === "union") {
    return (
      <FieldSet>
        <FieldLegend>{f.label}</FieldLegend>
        <FieldGroup>
          <ItemField item={f} pointer={pointer} schemaPointer={f.pointer} ctx={ctx} />
        </FieldGroup>
        {invalid ? <FieldError errors={errors} /> : null}
      </FieldSet>
    );
  }

  const control = <Control f={f} id={id} value={value} set={set} ctx={ctx} invalid={invalid} pointer={pointer} />;
  const inline = f.widget === "switch" || f.widget === "checkbox";

  return (
    <Field
      orientation={inline ? "horizontal" : ctx.orientation}
      data-invalid={invalid || undefined}
      className={counts(f) && ctx.orientation === "horizontal" ? "pb-5" : undefined}
    >
      {inline ? (
        <>
          {control}
          <div className="flex flex-col gap-0.5">
            <FieldLabel htmlFor={id}>{f.label}</FieldLabel>
            {f.help ? <FieldDescription>{f.help}</FieldDescription> : null}
          </div>
        </>
      ) : (
        <>
          <FieldLabel htmlFor={id}>
            {f.label}
            {f.required ? <span className="text-destructive"> *</span> : null}
          </FieldLabel>
          {control}
          {f.help ? <FieldDescription>{f.help}</FieldDescription> : null}
        </>
      )}
      {invalid ? <FieldError errors={errors} /> : null}
    </Field>
  );
}

// A list item or a union value: a fieldset's fields, or a variant chosen by its tag.
function ItemField({ item, pointer, schemaPointer, ctx }: { item: FieldSpec; pointer: string; schemaPointer: string; ctx: Ctx }) {
  if (item.widget === "union") {
    const current = getAt(ctx.draft, pointer) as Record<string, unknown> | null;
    const disc = item.discriminator ?? "type";
    const tag = current ? String(current[disc] ?? "") : "";
    const variant = item.variants?.find((v) => v.tag === tag) ?? item.variants?.[0];
    return (
      <>
        <Field>
          <FieldLabel>{t("type")}</FieldLabel>
          <Select
            value={tag || null}
            disabled={ctx.disabled}
            items={(item.variants ?? []).map((v) => ({ value: v.tag, label: v.label }))}
            onValueChange={(v) => {
              const next = item.variants?.find((x) => x.tag === v);
              if (next) ctx.update(pointer, { ...defaults(next.fields), [disc]: next.tag });
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(item.variants ?? []).map((v) => (
                <SelectItem key={v.tag} value={v.tag}>
                  {v.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {variant ? <Fields fields={variant.fields} base={pointer} schemaBase={schemaPointer} ctx={ctx} /> : null}
      </>
    );
  }
  if (item.widget === "fieldset") {
    return <Fields fields={item.fields ?? []} base={pointer} schemaBase={schemaPointer} ctx={ctx} />;
  }
  const value = getAt(ctx.draft, pointer);
  return <Control f={item} id={`f${pointer.replace(/[^a-zA-Z0-9]/g, "_")}`} value={value} set={(v) => ctx.update(pointer, v)} ctx={ctx} invalid={false} pointer={pointer} />;
}

// A file field: uploads go to the form's node, named by the field's pointer, and the
// draft keeps what the upload route answered; the server swaps that for its own record.
function FileControl({ f, id, value, set, ctx, pointer, multiple }: { f: FieldSpec; id: string; value: unknown; set: (v: unknown) => void; ctx: Ctx; pointer: string; multiple: boolean }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const Up = icon("upload");
  const Remove = icon("x");
  const isRef = (v: unknown): v is FileRef => typeof v === "object" && v !== null && typeof (v as FileRef).id === "string";
  const files: FileRef[] = multiple ? (Array.isArray(value) ? (value as unknown[]).filter(isRef) : []) : isRef(value) ? [value] : [];
  const take = async (list: FileList | null) => {
    if (!list?.length) return;
    setError(null);
    const limit = multiple ? Math.max(0, (f.max_files ?? 10) - files.length) : 1;
    const done: FileRef[] = [];
    for (const file of Array.from(list).slice(0, limit)) {
      setBusy(file.name);
      try {
        done.push(await upload(ctx.node, file, () => undefined, pointer));
      } catch (e) {
        setError(`${file.name}: ${(e as Error).message}`);
      }
    }
    setBusy(null);
    if (inputRef.current) inputRef.current.value = "";
    if (done.length) set(multiple ? [...files, ...done] : done[0]);
  };
  const remove = (ref: FileRef) => set(multiple ? files.filter((x) => x.id !== ref.id) : null);
  const canAdd = !ctx.disabled && busy === null && (multiple ? files.length < (f.max_files ?? 10) : files.length === 0);
  return (
    <div className="flex flex-col gap-2">
      {files.map((ref) => (
        <div key={ref.id} className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm">
          <span className="truncate">{ref.name}</span>
          <span className="text-xs text-muted-foreground">{formatSize(ref.size)}</span>
          {!ctx.disabled ? (
            <Button type="button" variant="ghost" size="icon-xs" className="ml-auto" aria-label={t("remove")} onClick={() => remove(ref)}>
              {Remove ? <Remove /> : "×"}
            </Button>
          ) : null}
        </div>
      ))}
      {canAdd ? (
        <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => inputRef.current?.click()}>
          {Up ? <Up /> : null}
          {t("choose")}
        </Button>
      ) : null}
      {busy ? <span className="text-xs text-muted-foreground">{busy}…</span> : null}
      {error ? <span className="text-xs text-destructive">{error}</span> : null}
      <input id={id} ref={inputRef} type="file" className="hidden" accept={f.accept?.join(",") || undefined} multiple={multiple} onChange={(e) => void take(e.target.files)} />
    </div>
  );
}

function Control({ f, id, value, set, ctx, invalid, pointer }: { f: FieldSpec; id: string; value: unknown; set: (v: unknown) => void; ctx: Ctx; invalid: boolean; pointer: string }) {
  const common = { id, disabled: ctx.disabled, "aria-invalid": invalid || undefined };
  const str = value === null || value === undefined ? "" : String(value);
  switch (f.widget) {
    case "file":
    case "files":
      return <FileControl f={f} id={id} value={value} set={set} ctx={ctx} pointer={pointer} multiple={f.widget === "files"} />;
    case "textarea":
      return counted(f, id, str, ctx, <Textarea {...common} {...described(f, id)} value={str} rows={typeof f.rows === "number" ? f.rows : undefined} maxLength={f.max_length} placeholder={f.placeholder ?? undefined} readOnly={ctx.readOnly} onChange={(e) => set(e.target.value || (f.clearable ? null : ""))} />);
    case "password":
      return <PasswordInput {...common} value={str} placeholder={f.placeholder ?? undefined} onChange={(e) => set(e.target.value || null)} />;
    case "number":
      return (
        <Input
          {...common}
          type="number"
          value={str}
          min={f.min}
          max={f.max}
          step={f.step ?? (f.integer ? 1 : "any")}
          placeholder={f.placeholder ?? undefined}
          onChange={(e) => set(e.target.value === "" ? null : Number(e.target.value))}
        />
      );
    case "slider": {
      const min = f.min ?? 0;
      const num = typeof value === "number" ? value : min;
      return (
        <div className="flex items-center gap-3">
          <Slider id={id} value={num} min={min} max={f.max ?? 100} step={f.step ?? 1} disabled={ctx.disabled} onValueChange={(v) => set(Array.isArray(v) ? Number(v[0]) : Number(v))} />
          <span className="w-10 text-right text-sm tabular-nums text-muted-foreground">{num}</span>
        </div>
      );
    }
    case "switch":
      return <Switch id={id} checked={Boolean(value)} disabled={ctx.disabled} onCheckedChange={(c) => set(Boolean(c))} />;
    case "checkbox":
      return <Checkbox id={id} checked={Boolean(value)} disabled={ctx.disabled} onCheckedChange={(c) => set(Boolean(c))} />;
    case "select":
      return (
        <Select value={value === undefined || value === "" ? null : (value as string | number | boolean | null)} disabled={ctx.disabled} items={(f.options ?? []).map((o) => ({ value: o.value, label: o.label }))} onValueChange={(v) => set(v)}>
          <SelectTrigger id={id} className="w-full" aria-invalid={invalid || undefined}>
            <SelectValue placeholder={f.placeholder ?? "Choose"} />
          </SelectTrigger>
          <SelectContent>
            {(f.options ?? []).map((o) => (
              <SelectItem key={String(o.value)} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    case "radio":
      return (
        <RadioGroup value={value as string | null} disabled={ctx.disabled} onValueChange={(v) => set(v)}>
          {(f.options ?? []).map((o) => (
            <div key={String(o.value)} className="flex items-center gap-2">
              <RadioGroupItem id={`${id}-${String(o.value)}`} value={o.value as string} />
              <Label htmlFor={`${id}-${String(o.value)}`}>{o.label}</Label>
            </div>
          ))}
        </RadioGroup>
      );
    case "toggle":
      return (
        <ToggleGroup value={value === null || value === undefined ? [] : [String(value)]} disabled={ctx.disabled} onValueChange={(v) => set((v as unknown[])[0] ?? null)}>
          {(f.options ?? []).map((o) => (
            <ToggleGroupItem key={String(o.value)} value={o.value as string}>
              {o.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      );
    case "multiselect":
      return (
        <MultiSelectControl
          id={id}
          options={(f.options ?? []).map((o) => ({ value: String(o.value), label: o.label }))}
          value={Array.isArray(value) ? (value as unknown[]).map(String) : []}
          placeholder={f.placeholder ?? undefined}
          max={f.max_items ?? null}
          sortable={Boolean(f.sortable)}
          disabled={ctx.disabled}
          invalid={invalid}
          onChange={(next) => set(next)}
        />
      );
    case "date":
      return (
        <DatePickerControl
          id={id}
          value={typeof value === "string" ? value : null}
          min={f.min_date ?? null}
          max={f.max_date ?? null}
          clearable={Boolean(f.clearable)}
          placeholder={f.placeholder ?? undefined}
          disabled={ctx.disabled}
          invalid={invalid}
          onChange={(next) => set(typeof next === "string" ? next : null)}
        />
      );
    case "checkboxes": {
      const arr = Array.isArray(value) ? (value as unknown[]) : [];
      return (
        <div className="flex flex-col gap-2">
          {(f.options ?? []).map((o) => {
            const cid = `${id}-${String(o.value)}`;
            return (
              <div key={cid} className="flex items-center gap-2">
                <Checkbox id={cid} checked={arr.includes(o.value)} disabled={ctx.disabled} onCheckedChange={(c) => set(c ? [...arr.filter((x) => x !== o.value), o.value] : arr.filter((x) => x !== o.value))} />
                <Label htmlFor={cid}>{o.label}</Label>
              </div>
            );
          })}
        </div>
      );
    }
    case "tags":
      return (
        <Input
          {...common}
          value={Array.isArray(value) ? (value as unknown[]).join(", ") : str}
          placeholder={f.placeholder ?? "a, b, c"}
          onChange={(e) =>
            set(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
                .map((s) => (f.item?.widget === "number" ? Number(s) : s)),
            )
          }
        />
      );
    case "datetime":
      return <Input {...common} type="datetime-local" value={str.slice(0, 16)} onChange={(e) => set(e.target.value || null)} />;
    default:
      return counted(f, id, str, ctx, <Input {...common} {...described(f, id)} value={str} maxLength={f.max_length} placeholder={f.placeholder ?? undefined} readOnly={ctx.readOnly} onChange={(e) => set(e.target.value || (f.clearable ? null : ""))} />);
  }
}

// Whether a field shows its count: one that was asked to, and holds text.
function counts(f: FieldSpec): boolean {
  return Boolean(f.counter) && (f.widget === "textarea" || f.widget === "input");
}

// A text field that was asked to show its count, with the count under it.
// Next to its label the count hangs below the row, in room the row keeps
// for it, so the label stays level with the field.
function counted(f: FieldSpec, id: string, text: string, ctx: Ctx, field: ReactElement) {
  if (!counts(f)) return field;
  return (
    <div className={cn("flex w-full min-w-0 flex-col", ctx.orientation === "horizontal" && "-mb-5")}>
      {field}
      <Count id={`${id}-count`} length={text.length} max={limitOf(f.max_length)} />
    </div>
  );
}

function described(f: FieldSpec, id: string) {
  return counts(f) ? { "aria-describedby": `${id}-count` } : {};
}

export function labelFor(f: FieldSpec): ReactNode {
  return f.label;
}
