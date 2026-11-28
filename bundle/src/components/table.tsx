// The Table: every row in the browser, sorted, filtered and paged here;
// selection reported to the server, tones instead of styles. A long table
// draws the rows in view, and a row is drawn again only when it changed.

import { partName, usePartMarks } from "../marks";
import { asDate, dateFormat, dateTimeFormat, formatNumber } from "../format";
import { locale, t } from "../theme";
import { type CSSProperties, type KeyboardEvent as KeyPress, type ReactNode, memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Renderer } from "../render";
import { type Sort, emptyFilter, equalsFilter, includesFilter, rangeFilter, sortRows } from "../table-rows";
import { cn } from "cn";
import { icon } from "../icons";
import { useRowWindow, useSteadyColumns } from "../hooks/use-row-window";
import { linkLook, safeUrl } from "../lib";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { ownPress } from "../press";
import { emitHeard } from "../ws";
import { type Grip, RowGrip, useRowDrag } from "../lent";
import { type Way, fieldText, neighbor, same, typed } from "../cell-edit";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface Column {
  key: string;
  header?: string | null;
  group?: string | null;
  width?: number | string | null;
  align?: "left" | "center" | "right";
  format?: string;
  sortable?: boolean;
  filterable?: boolean;
  editable?: boolean;
  hidden?: boolean;
  wrap?: boolean;
  lines?: number | null;
}

interface MenuItem {
  id: string;
  label: string;
  icon?: string | null;
  disabled?: boolean;
  destructive?: boolean;
  separator_after?: boolean;
}

// The filter a column gets: a range for numbers, a choice for a column with few
// distinct values, a contains-text box otherwise. Inferred from the format and
// the data, as Shiny's DataGrid does.
type FilterKind = { kind: "text" } | { kind: "number" } | { kind: "select"; values: string[] };

const NUMERIC = new Set(["number", "integer", "percent", "currency"]);

function filterKind(c: Column, rows: Record<string, unknown>[]): FilterKind {
  if (NUMERIC.has(c.format ?? "")) return { kind: "number" };
  const present = rows.map((r) => r[c.key]).filter((v) => v !== null && v !== undefined && v !== "");
  if (!present.length) return { kind: "text" };
  if (c.format === "bool" || present.every((v) => typeof v === "boolean")) return { kind: "select", values: ["true", "false"] };
  if ((c.format === "text" || c.format === undefined) && present.every((v) => typeof v === "number")) return { kind: "number" };
  if (c.format === "link" || c.format === "code" || c.format === "date" || c.format === "datetime") return { kind: "text" };
  const distinct = Array.from(new Set(present.map((v) => String(v))));
  if (distinct.length <= 12 && distinct.length < present.length) return { kind: "select", values: distinct.sort((a, b) => a.localeCompare(b)) };
  return { kind: "text" };
}

function FilterCell({ kind, value, onChange }: { kind: FilterKind; value: unknown; onChange: (v: unknown) => void }) {
  if (kind.kind === "number") {
    const [min, max] = (Array.isArray(value) ? value : [null, null]) as [number | null, number | null];
    const num = (s: string) => (s === "" ? null : Number(s));
    return (
      <div className="flex items-center gap-1">
        <Input type="number" value={min ?? ""} onChange={(e) => onChange([num(e.target.value), max])} placeholder={t("min")} className="h-7 w-16 px-1.5 text-xs" />
        <Input type="number" value={max ?? ""} onChange={(e) => onChange([min, num(e.target.value)])} placeholder={t("max")} className="h-7 w-16 px-1.5 text-xs" />
      </div>
    );
  }
  if (kind.kind === "select") {
    const current = value === null || value === undefined ? "" : String(value);
    return (
      <select
        value={current}
        onChange={(e) => onChange(e.target.value)}
        aria-label={t("filter")}
        className="h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-xs text-foreground"
      >
        <option value="">{t("all")}</option>
        {kind.values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    );
  }
  return <Input value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} placeholder={t("filter")} className="h-7 text-xs" />;
}

const rowTone: Record<string, string> = {
  muted: "bg-muted/40 text-muted-foreground",
  primary: "bg-primary/10",
  accent: "bg-accent",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  destructive: "bg-destructive/10 text-destructive",
};

const badgeByTone: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  default: "secondary",
  muted: "secondary",
  primary: "default",
  accent: "secondary",
  success: "outline",
  warning: "outline",
  destructive: "destructive",
};

const badgeTone: Record<string, string> = {
  success: "border-success text-success",
  warning: "border-warning text-warning",
};

// A cell's tone colours its text, as a row's tone does; a badge wears it instead.
const cellTone: Record<string, string> = {
  muted: "text-muted-foreground",
  primary: "text-primary font-medium",
  accent: "text-accent-foreground",
  success: "text-success font-medium",
  warning: "text-warning font-medium",
  destructive: "text-destructive font-medium",
};


const DASH_WHEN_EMPTY = { number: 1, integer: 1, percent: 1, currency: 1, date: 1, datetime: 1, badge: 1, code: 1, link: 1 };

function formatCell(value: unknown, format: string, tone?: string) {
  // Nothing to show is a dash, and so is a text that is empty or only
  // spaces in a format that would make something of it: a number, a date,
  // a badge, a code pill or a link.
  const empty = typeof value === "string" && value.trim() === "";
  const blank = value === null || value === undefined || (empty && format in DASH_WHEN_EMPTY);
  if (blank) return <span className="text-muted-foreground">–</span>;
  switch (format) {
    case "number":
    case "integer":
    case "percent":
    case "currency":
      return formatNumber(value, format);
    case "date":
    case "datetime": {
      // What is not a date is shown as it came: formatting it would throw.
      const when = asDate(value);
      if (Number.isNaN(when.getTime())) return String(value);
      return (format === "date" ? dateFormat : dateTimeFormat).format(when);
    }
    case "bool": {
      const Icon = icon(value ? "check" : "minus");
      const own = value ? "text-success" : "text-muted-foreground";
      return Icon ? <Icon className={cn("size-4", tone ? cellTone[tone] : own)} /> : String(value);
    }
    case "badge":
      return (
        <Badge variant={badgeByTone[tone ?? "default"]} className={badgeTone[tone ?? ""]}>
          {String(value)}
        </Badge>
      );
    case "link":
      return (
        <a href={safeUrl(value)} target="_blank" rel="noreferrer" className={cn(tone ? cellTone[tone] : "text-primary", linkLook)}>
          {String(value)}
        </a>
      );
    case "code":
      return <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{String(value)}</code>;
    default:
      return String(value);
  }
}

// A row as the table holds it: the record as it arrived, its place in the
// rows, its key, and the key as text for sets and for React.
type Entry = { row: Record<string, unknown>; i: number; key: unknown; id: string };

type Act = (what: "select" | "range" | "click" | "action", key: unknown, id?: string) => void;

// A cell that is typed over. How its field is left: Enter goes down and
// with shift up, Tab to the next cell and with shift to the one before,
// Escape stays, and a press elsewhere takes the keyboard with it.
type Leave = Way | "stay" | "blur";
// What became of it: the field is closed and the keyboard is the table's
// to place, or the field is closed and the keyboard is where the person
// took it, or what was typed is no value of the column and the field is
// still open.
type Left = "placed" | "left" | "wrong";
// `open` a cell, with the character that was typed to open it or nothing;
// `close` its field with the text in it, or nothing to leave the cell as it
// was; `set` a cell that has no field, a yes or no.
type CellAct = (what: "open" | "close" | "set", name: string, col: string, payload: unknown, how?: Leave) => Left;
type Opened = { name: string; col: string; initial: string | null };

// The field of the one cell that is open. It lies over the cell, as big as
// the cell, so typing in it changes no column's width.
function CellField({ start, typedOver, label, close }: { start: string; typedOver: boolean; label: string; close: (text: string | null, how: Leave) => Left }) {
  const [draft, setDraft] = useState(start);
  // What the field held when it opened. The row may be given another
  // value while it is open, and the field is as it was against this one.
  const [first] = useState(start);
  const [wrong, setWrong] = useState(false);
  // A field that is closed by a key leaves the page, which a browser may
  // tell it as losing the keyboard. It is closed once.
  const closed = useRef(false);
  // Enter that takes a word from an input method is that method's, and
  // one browser says the word is taken just before it says Enter.
  const composed = useRef(false);
  const leave = (text: string | null, how: Leave) => {
    if (closed.current) return;
    // A field that was opened and left as it was says nothing: the cell
    // may show less of a number than the row holds, and what it shows is
    // not what was typed.
    const said = text !== null && !typedOver && text === first ? null : text;
    let left = close(said, how);
    // What is no value of the column, with the keyboard gone elsewhere,
    // is not kept open for a person who is no longer there.
    if (left === "wrong" && how === "blur") left = close(null, how);
    if (left === "wrong") setWrong(true);
    else closed.current = true;
  };
  return (
    <input
      autoFocus
      aria-label={label}
      aria-invalid={wrong || undefined}
      value={draft}
      onCompositionEnd={() => {
        composed.current = true;
        window.setTimeout(() => (composed.current = false), 0);
      }}
      // Opened by typing, the field goes on from what was typed. Opened
      // otherwise, what it holds is typed over.
      onFocus={(e) => {
        if (!typedOver) e.currentTarget.select();
      }}
      onChange={(e) => {
        setDraft(e.currentTarget.value);
        setWrong(false);
      }}
      onBlur={() => leave(draft, "blur")}
      onKeyDown={(e) => {
        if (e.nativeEvent.isComposing || composed.current || e.keyCode === 229) return;
        if (e.key === "Enter") {
          e.preventDefault();
          leave(draft, e.shiftKey ? "up" : "down");
        } else if (e.key === "Tab") {
          // The keyboard goes where the table puts it: the next cell, or
          // this one at the end of them, from where Tab leaves the table.
          e.preventDefault();
          leave(draft, e.shiftKey ? "prev" : "next");
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          leave(null, "stay");
        }
      }}
      className={cn("mw-editable mw-editable-field absolute inset-0", wrong && "mw-editable-wrong")}
    />
  );
}

const NONE: never[] = [];

// The lines a column's cells are cut to, or 0 for a column that is not cut.
const cutTo = (c: Column): number => (typeof c.lines === "number" && c.lines >= 1 ? c.lines : 0);
// Whether a column is cut and has no width, so takes the width left over.
const takesTheRest = (c: Column): boolean => cutTo(c) > 0 && c.width == null;

interface RowProps {
  row: Record<string, unknown>;
  rowKey: unknown;
  // What a highlight on this row finds it by.
  part: string;
  tone: string | null | undefined;
  cellTones: Record<string, string> | null | undefined;
  selected: boolean;
  columns: Column[];
  checkbox: boolean;
  actions: MenuItem[];
  clickable: boolean;
  // Whether Tab stops at this row. One row of a table that can be pressed
  // does, and the arrow keys go to the others from there.
  stop: boolean;
  act: Act;
  // What a row that can be dragged carries, and its grip. The same objects
  // from one drawing to the next.
  mark?: { "data-mw-row": string };
  grip?: Grip;
  // In a table whose cells are typed over: what a cell does, the column
  // of this row that Tab stops at, the cell of this row that is open, and
  // what was typed in this row that the page has not answered yet.
  cell?: CellAct;
  stopCol?: string | null;
  opened?: Opened | null;
  sent?: Record<string, unknown> | null;
}

// One row, drawn again only when something it shows changed: the record is the
// same object from one patch to the next unless the patch touched it, and
// everything else here is a plain value or stable for the table's life.
const Row = memo(function Row({ row, rowKey, part, tone, cellTones, selected, columns, checkbox, actions, clickable, stop, act, mark, grip, cell, stopCol, opened, sent }: RowProps) {
  const takers = columns.filter(takesTheRest).length;
  // Whether shift was down for the press that is changing the checkbox. The
  // change itself does not say, and it comes during the click that does.
  const shift = useRef(false);
  return (
    <TableRow
      {...mark}
      data-part={part}
      data-state={selected ? "selected" : undefined}
      data-press={clickable ? "" : undefined}
      tabIndex={clickable ? (stop ? 0 : -1) : undefined}
      className={cn(tone && rowTone[tone], clickable && rowFocus)}
      onClick={(e) => {
        if (ownPress(e)) act("click", rowKey);
      }}
    >
      {grip ? (
        <TableCell data-free="" className="py-(--mw-cell-y) pr-0 whitespace-nowrap">
          {/* Named by what the row starts with, so a screen reader says which row it moves. */}
          <RowGrip {...grip} label={`${t("move_row")} ${columns.length ? String(row[columns[0].key] ?? "") : ""}`.trim()} />
        </TableCell>
      ) : null}
      {checkbox ? (
        <TableCell
          // The checkbox's column is as wide as it was told to be.
          data-free=""
          className="py-(--mw-cell-y) whitespace-nowrap"
          onClickCapture={(e) => {
            shift.current = e.shiftKey;
          }}
          // A press with shift would also select the text up to here. Stopping
          // that stops the press from taking the keyboard along, so it is sent.
          onMouseDown={(e) => {
            if (!e.shiftKey) return;
            e.preventDefault();
            e.currentTarget.querySelector<HTMLElement>("[role=checkbox]")?.focus();
          }}
        >
          <Checkbox checked={selected} onCheckedChange={() => act(shift.current ? "range" : "select", rowKey)} aria-label={t("select_row")} />
        </TableCell>
      ) : null}
      {columns.map((c) => {
        const cellTone_ = cellTones?.[c.key];
        if (cell && c.editable) {
          const format = c.format ?? "text";
          const waits = sent != null && c.key in sent;
          const value = waits ? sent[c.key] : row[c.key];
          const label = c.header ?? c.key;
          const tab = stopCol === c.key ? 0 : -1;
          const align = cn(c.align === "right" && "text-right tabular-nums", c.align === "center" && "text-center");
          if (format === "bool") {
            return (
              <TableCell key={c.key} data-free="" className={cn("py-(--mw-cell-y) whitespace-nowrap", align)}>
                <Checkbox
                  data-cell=""
                  data-col={c.key}
                  tabIndex={tab}
                  checked={Boolean(value)}
                  onCheckedChange={(on) => cell("set", part, c.key, on === true)}
                  aria-label={label}
                  className={cn("inline-flex", waits && "opacity-60")}
                />
              </TableCell>
            );
          }
          const open = opened && opened.col === c.key ? opened : null;
          const shown = formatCell(value, format, cellTone_);
          const text = typeof shown === "string" ? shown : "";
          // A column that is cut to a line keeps no width for its text,
          // as its cells do when they are not typed over.
          const cut = cutTo(c) > 0;
          return (
            <TableCell
              key={c.key}
              data-free={cut ? "" : undefined}
              className={cn("py-(--mw-cell-y) whitespace-nowrap", align, cut && (c.width == null ? "max-w-0 min-w-32" : "max-w-0"))}
              style={cut && c.width == null ? { width: `${100 / takers}%` } : undefined}
            >
              {/* As wide as the cell with its padding, so the text stands where the text of any other cell does. */}
              <div className="relative -mx-1.5">
                <button
                  type="button"
                  data-cell=""
                  data-col={c.key}
                  tabIndex={tab}
                  // Said with its column, for a person who came to it by Tab
                  // and not by reading the table.
                  aria-label={`${label}: ${text}`}
                  title={cut ? text : undefined}
                  onClick={() => cell("open", part, c.key, null)}
                  className={cn("mw-editable", waits && "mw-editable-sent", open && "invisible", cellTone_ && cellTone[cellTone_])}
                >
                  {shown}
                </button>
                {open ? (
                  <CellField
                    start={open.initial ?? fieldText(value, format, locale())}
                    typedOver={open.initial !== null}
                    label={label}
                    close={(text, how) => cell("close", part, c.key, text, how)}
                  />
                ) : null}
              </div>
            </TableCell>
          );
        }
        const content = formatCell(row[c.key], c.format ?? "text", cellTone_);
        const shown = cellTone_ && c.format !== "badge" && cellTone[cellTone_] ? <span className={cellTone[cellTone_]}>{content}</span> : content;
        const lines = cutTo(c);
        const value = row[c.key];
        const whole = typeof content === "string" ? content : typeof value === "string" || typeof value === "number" ? String(value) : undefined;
        return (
          <TableCell
            key={c.key}
            // A column that is cut keeps no width for its text, in a long
            // table too.
            data-free={lines > 0 ? "" : undefined}
            className={cn(
              "py-(--mw-cell-y)",
              c.align === "right" && "text-right tabular-nums",
              c.align === "center" && "text-center",
              c.wrap || lines > 1 ? "whitespace-normal" : "whitespace-nowrap",
              // A cell that is cut asks for no width of its own, so its text
              // cannot widen the column. The column is as wide as it says,
              // or takes what the others leave.
              lines > 0 && (c.width == null ? "max-w-0 min-w-32" : "max-w-0"),
            )}
            // Columns that take what is left share it.
            style={lines > 0 && c.width == null ? { width: `${100 / takers}%` } : undefined}
          >
            {lines > 0 ? (
              <div title={whole} className={lines === 1 ? "truncate" : "mw-lines"} style={lines > 1 ? ({ "--mw-lines": lines } as CSSProperties) : undefined}>
                {shown}
              </div>
            ) : (
              shown
            )}
          </TableCell>
        );
      })}
      {actions.length ? (
        <TableCell data-free="" className="py-(--mw-cell-y) whitespace-nowrap">
          <RowActions items={actions} onPick={(id) => act("action", rowKey, id)} />
        </TableCell>
      ) : null}
    </TableRow>
  );
});

// How a row that can be pressed shows that the keyboard is on it: the ring of
// a focused button, drawn inside the row, over whatever fill the row has. A
// scroll that brings the row into view leaves room for the header over the rows.
const rowFocus = "cursor-pointer scroll-mt-(--mw-head) focus-visible:outline-3 focus-visible:-outline-offset-3 focus-visible:outline-ring/50";

type Head = { id: string; header: ReactNode; sortable: boolean; filterable: boolean; size?: number | string; column?: Column; group?: string | null; edge?: boolean };

// The cells of the row over the headers, when columns are grouped: one
// over each run of columns of the same group, and an empty one over each
// run of columns that have none. A head where another group begins, or
// where one ends, is marked as an edge, which draws a line there.
function bandsOf(heads: Head[]): { label: string | null; span: number; edge: boolean }[] {
  const bands: { label: string | null; span: number; edge: boolean }[] = [];
  heads.forEach((head, i) => {
    const group = head.group || null;
    const before = i > 0 ? heads[i - 1].group || null : null;
    if (i > 0 && group === before) {
      bands[bands.length - 1].span++;
      return;
    }
    head.edge = i > 0;
    bands.push({ label: group, span: 1, edge: i > 0 });
  });
  return bands;
}

export const Table: Renderer = ({ node, props, emit }) => {
  const rows = (Array.isArray(props.rows) ? (props.rows as Record<string, unknown>[]) : NONE);
  const keys = (Array.isArray(props.keys) ? (props.keys as unknown[]) : NONE);
  const columns = (Array.isArray(props.columns) ? (props.columns as Column[]) : NONE);
  const toneRows = (Array.isArray(props.tone_rows) ? (props.tone_rows as (string | null)[]) : NONE);
  const toneCells = (Array.isArray(props.tone_cells) ? (props.tone_cells as (Record<string, string> | null)[]) : NONE);
  const selection = String(props.selection ?? "none");
  const selected = (Array.isArray(props.selected) ? (props.selected as unknown[]) : NONE);
  const actions = (Array.isArray(props.row_actions) ? (props.row_actions as MenuItem[]) : NONE);
  const pageSize = typeof props.page_size === "number" ? props.page_size : null;

  const entries = useMemo<Entry[]>(() => rows.map((row, i) => ({ row, i, key: keys[i], id: JSON.stringify(keys[i]) })), [rows, keys]);
  // A row is known to React by its key, so one that moves is moved and not
  // drawn again; rows that share a key go by their place instead.
  const distinct = useMemo(() => new Set(entries.map((e) => e.id)).size === entries.length, [entries]);
  const visible = useMemo(() => columns.filter((c) => !c.hidden), [columns]);

  const [sorting, setSorting] = useState<Sort[]>(() =>
    (Array.isArray(props.default_sort) ? (props.default_sort as [string, string][]) : []).map(([id, dir]) => ({ id, desc: dir === "desc" })),
  );
  const [filters, setFilters] = useState<Record<string, unknown>>({});
  const [globalFilter, setGlobalFilter] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  // What kind of filter each column gets is read off every row, so it is only
  // worked out for a table that shows filters.
  const filtered = Boolean(props.filters);
  const kinds = useMemo(
    () => (filtered ? (Object.fromEntries(columns.map((c) => [c.key, filterKind(c, rows)])) as Record<string, FilterKind>) : {}),
    [filtered, columns, rows],
  );

  // The initial sort and the empty filter are the server's own: only a change
  // made here is reported.
  const settled = useRef(false);
  useEffect(() => {
    if (settled.current && props.on_sort) emit("sort", sorting.map((s) => [s.id, s.desc ? "desc" : "asc"]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sorting]);
  useEffect(() => {
    if (settled.current && props.on_filter) emit("filter", { columns: filters, search: globalFilter });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, globalFilter]);
  useEffect(() => {
    settled.current = true;
  }, []);

  const setFilter = (id: string, value: unknown) =>
    setFilters((old) => {
      const next = { ...old };
      if (emptyFilter(value)) delete next[id];
      else next[id] = value;
      return next;
    });

  // A click sorts by that column, again reverses it, a third time clears it;
  // with shift the column joins the sort, or turns in its place.
  const toggleSort = (id: string, multi: boolean) =>
    setSorting((old) => {
      const current = old.find((s) => s.id === id) ?? null;
      const next: Sort | null = current === null ? { id, desc: false } : current.desc ? null : { id, desc: true };
      if (!multi) return next ? [next] : [];
      if (current === null) return next ? [...old, next] : old;
      return next ? old.map((s) => (s.id === id ? next : s)) : old.filter((s) => s.id !== id);
    });

  const selectedSet = useMemo(() => new Set(selected.map((k) => JSON.stringify(k))), [selected]);

  // What a row does when it is used. The rows hold one function for the table's
  // life, which reads the table as it is now, so a row is not drawn again
  // because the selection or a handler changed elsewhere.
  const now = useRef({ selection, selected, selectedSet, emit, onSelect: Boolean(props.on_select), onRowClick: Boolean(props.on_row_click), page: NONE as Entry[] });
  now.current = { ...now.current, selection, selected, selectedSet, emit, onSelect: Boolean(props.on_select), onRowClick: Boolean(props.on_row_click) };
  // The row whose checkbox was used last, where a range starts.
  const anchor = useRef<string | null>(null);
  const act = useCallback<Act>((what, key, id) => {
    const { selection, selected, selectedSet, emit, onSelect, onRowClick, page } = now.current;
    const select = (range: boolean) => {
      if (selection === "none" || !onSelect) return;
      const text = JSON.stringify(key);
      const on = selectedSet.has(text);
      if (selection === "row") {
        emit("select", on ? [] : [key]);
        return;
      }
      // With shift, the rows from the last one used to this one all get what
      // this one gets, in the order they are shown. The rows are those of the
      // page in view, so a range never takes in a row the person cannot see,
      // and it starts from a selection: with none there is nothing to extend.
      const from = range && selected.length ? page.findIndex((e) => e.id === anchor.current) : -1;
      const to = from < 0 ? -1 : page.findIndex((e) => e.id === text);
      anchor.current = text;
      const span = to < 0 ? [{ id: text, key }] : page.slice(Math.min(from, to), Math.max(from, to) + 1);
      const ids = new Set(span.map((e) => e.id));
      const next = selected.filter((k) => !ids.has(JSON.stringify(k)));
      if (!on) next.push(...span.map((e) => e.key));
      emit("select", next);
    };
    if (what === "action") emit("action", [id, key]);
    else if (what === "select" || what === "range") select(what === "range");
    else {
      if (onRowClick) emit("row_click", key);
      if (selection === "row") select(false);
    }
  }, []);

  const shown = useMemo(() => {
    const needle = globalFilter.trim().toLowerCase();
    const active = Object.entries(filters).filter(([id]) => kinds[id]);
    // A filter on a column the server has since dropped filters nothing.
    const kept =
      !needle && !active.length
        ? entries
        : entries.filter(({ row }) => {
            for (const [id, value] of active) {
              const kind = kinds[id].kind;
              const ok = kind === "number" ? rangeFilter(row[id], value) : kind === "select" ? equalsFilter(row[id], value) : includesFilter(row[id], value);
              if (!ok) return false;
            }
            if (!needle) return true;
            return visible.some((c) => includesFilter(row[c.key], needle));
          });
    return sortRows(kept, sorting, (e, id) => e.row[id]);
  }, [entries, visible, filters, globalFilter, kinds, sorting]);

  // A rows patch (a task updating a column) must not bounce the reader to page
  // 1; a page that no longer exists falls back to the last one.
  const pageCount = pageSize ? Math.max(1, Math.ceil(shown.length / pageSize)) : 1;
  useEffect(() => {
    if (pageIndex >= pageCount) setPageIndex(pageCount - 1);
  }, [pageIndex, pageCount]);
  const given = useMemo(
    () => (pageSize ? shown.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize) : shown),
    [shown, pageSize, pageIndex],
  );

  const body = useRef<HTMLTableSectionElement>(null);
  const headRow = useRef<HTMLTableRowElement>(null);
  // How tall the header that stays over the rows is, filters and all.
  const [head, setHead] = useState(0);
  // Rows go by their key where keys tell them apart, by their place otherwise.
  const givenNames = useMemo(() => given.map((e) => (distinct ? e.id : `#${e.i}`)), [given, distinct]);
  // Rows that are dragged into another order. Such a table shows its rows
  // as the page gave them, with nothing sorted, filtered or paged, and
  // after a drop in the dropped order until the page has answered. That
  // is the order everything below goes by: a range of rows selected with
  // shift, the keyboard, the rows as they are drawn.
  const movable = Boolean(props.on_move);
  // A table whose rows stay put, which may be a very long one, pays
  // nothing for this: no names are handed over and none are looked up.
  const byName = useMemo(() => new Map(movable ? given.map((e, i) => [givenNames[i], e]) : []), [movable, given, givenNames]);
  const drag = useRowDrag({
    keys: movable ? givenNames : NONE,
    onMove: (name, to) => {
      const moved = byName.get(name);
      return moved ? emitHeard(node.id, "move", { key: moved.key, to }) : undefined;
    },
    disabled: !movable,
    list: body,
    // The header covers the top of the box only where the box is what
    // scrolls. A table as high as its rows scrolls with the page.
    inset: { top: props.height || props.fill ? head : 0 },
  });
  const names = movable ? drag.order : givenNames;
  const page = useMemo(
    () => (movable ? names.map((name) => byName.get(name)).filter((e): e is Entry => e !== undefined) : given),
    [movable, names, byName, given],
  );
  now.current.page = page;
  const view = useRowWindow(body, names);
  const drawn = useMemo(
    () => (view.windowed ? page.slice(view.first, view.last) : page),
    [page, view.windowed, view.first, view.last],
  );
  useSteadyColumns(headRow, body, view.windowed, visible, drawn);

  const clickable = selection === "row" || Boolean(props.on_row_click);
  // The rows of a table that can be pressed are one stop for Tab: the row
  // the keyboard was on last, or the first one drawn. The arrow keys, Home
  // and End move between the rows of the page, and Enter or Space presses.
  const [stop, setStop] = useState<string | null>(null);
  const held = stop === null ? -1 : names.indexOf(stop);
  const stopAt = held >= view.first && held < view.last ? held : view.first;
  const spacer = view.before > 0 ? 1 : 0;
  // Which row of the page an element is, when it is one of the rows.
  const placeOf = (el: EventTarget | null): number => {
    const rowsEl = body.current;
    if (!clickable || !rowsEl || !(el instanceof HTMLElement) || el.parentElement !== rowsEl || el.dataset.part === undefined) return -1;
    return view.first + Array.prototype.indexOf.call(rowsEl.children, el) - spacer;
  };
  const rowAt = (at: number) => body.current?.children[at - view.first + spacer] as HTMLElement | undefined;
  // The row the keyboard is going to, while it is still to be drawn.
  const aimed = useRef<string | null>(null);
  // The row the keyboard is on, and its place on the page.
  const on = useRef<{ name: string; at: number } | null>(null);
  useLayoutEffect(() => {
    // A row that goes while the keyboard is on it, as one that is pressed
    // to be dismissed does, would take the keyboard off the page with it.
    // The row that took its place gets it, or the last one.
    const was = on.current;
    if (was) {
      const at = names.indexOf(was.name);
      if (at >= view.first && at < view.last) was.at = at;
      else if (at >= 0) on.current = null;
      else {
        on.current = null;
        const lost = !document.activeElement || document.activeElement === document.body;
        const to = Math.min(was.at, names.length - 1);
        if (lost && to >= view.first && to < view.last) rowAt(to)?.focus();
      }
    }
    if (aimed.current === null) return;
    const at = names.indexOf(aimed.current);
    if (at >= 0 && (at < view.first || at >= view.last)) return;
    aimed.current = null;
    if (at >= 0) rowAt(at)?.focus();
  });
  // Cells that are typed over. The columns that are, in the order they
  // are shown; the cell that is open; the cell Tab stops at; and what was
  // typed and not yet answered by the page, a row's cells by column.
  const editable = Boolean(props.on_edit);
  const typedCols = useMemo(() => (editable ? visible.filter((c) => c.editable).map((c) => c.key) : NONE), [editable, visible]);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [stopCell, setStopCell] = useState<{ name: string; col: string } | null>(null);
  const [sent, setSent] = useState<Map<string, Record<string, unknown>>>(() => new Map());
  // The last word sent of each cell, so an answer to an older one does
  // not take away what was typed since.
  const said = useRef(new Map<string, number>());
  // The cell the keyboard is going to, once it is drawn and no field is open.
  const aimedCell = useRef<{ name: string; col: string } | null>(null);
  const cellAt = (at: number, col: string) => rowAt(at)?.querySelector<HTMLElement>(`[data-cell][data-col="${CSS.escape(col)}"]`);
  const goTo = (to: { name: string; col: string }) => {
    setStopCell(to);
    aimedCell.current = to;
    const at = names.indexOf(to.name);
    if (at >= 0 && (at < view.first || at >= view.last)) view.bring(at);
  };
  useLayoutEffect(() => {
    const aim = aimedCell.current;
    if (!aim || opened) return;
    const at = names.indexOf(aim.name);
    if (at < 0) aimedCell.current = null;
    if (at < view.first || at >= view.last) return;
    const el = cellAt(at, aim.col);
    if (!el) return;
    aimedCell.current = null;
    el.focus();
  });
  // A row that went away with its cell open takes the field with it, and
  // so does one that a long table no longer draws.
  useEffect(() => {
    if (!opened) return;
    const at = names.indexOf(opened.name);
    if (at < view.first || at >= view.last) setOpened(null);
  }, [opened, names, view.first, view.last]);
  // The cell the keyboard is on, and its place. A row that goes while the
  // keyboard is on one of its cells would take the keyboard off the page
  // with it: the row is filtered out by what was just typed, or the page
  // took it away or gave it another key. The cell in its place gets the
  // keyboard, or the last one. A row that a long table no longer draws is
  // left alone, or the table would scroll back to it.
  const onCell = useRef<{ name: string; col: string; at: number } | null>(null);
  useLayoutEffect(() => {
    const was = onCell.current;
    if (!was || opened || aimedCell.current) return;
    const lost = !document.activeElement || document.activeElement === document.body;
    if (!lost) return;
    const at = names.indexOf(was.name);
    onCell.current = null;
    if (at >= 0 && (at < view.first || at >= view.last)) return;
    const to = at >= 0 ? at : Math.min(was.at, names.length - 1);
    if (to >= view.first && to < view.last) cellAt(to, was.col)?.focus();
  });
  const tell = (entry: Entry, name: string, col: string, value: unknown) => {
    const id = `${name}\n${col}`;
    const mine = (said.current.get(id) ?? 0) + 1;
    said.current.set(id, mine);
    setSent((old) => new Map(old).set(name, { ...old.get(name), [col]: value }));
    // The page has answered: what it gave the row is what the cell shows.
    const answered = () => {
      if (said.current.get(id) !== mine) return;
      said.current.delete(id);
      setSent((old) => {
        const row = old.get(name);
        if (!row || !(col in row)) return old;
        const next = new Map(old);
        const { [col]: _gone, ...rest } = row;
        if (Object.keys(rest).length) next.set(name, rest);
        else next.delete(name);
        return next;
      });
    };
    void emitHeard(node.id, "edit", { key: entry.key, column: col, value }).then(answered, answered);
  };
  const cellNow: CellAct = (what, name, col, payload, how) => {
    const at = names.indexOf(name);
    const entry = page[at];
    const column = visible.find((c) => c.key === col);
    if (!entry || !column) {
      // The row or the column went while its cell was open.
      setOpened(null);
      return "left";
    }
    if (what === "open") {
      setStopCell({ name, col });
      setOpened({ name, col, initial: typeof payload === "string" ? payload : null });
      return "left";
    }
    const shown = () => {
      const waits = sent.get(name);
      return waits && col in waits ? waits[col] : entry.row[col];
    };
    if (what === "set") {
      if (!same(payload, shown())) tell(entry, name, col, payload);
      return "left";
    }
    if (payload !== null) {
      const got = typed(String(payload), column.format ?? "text", locale());
      if (!got.ok) return "wrong";
      if (!same(got.value, shown())) tell(entry, name, col, got.value);
    }
    setOpened(null);
    if (how === undefined || how === "blur") return "left";
    const to = how === "stay" ? null : neighbor(names.length, typedCols.length, at, typedCols.indexOf(col), how);
    // With no cell to go on to, the keyboard is on this one again.
    goTo(to ? { name: names[to[0]], col: typedCols[to[1]] } : { name, col });
    return "placed";
  };
  const cellLive = useRef(cellNow);
  cellLive.current = cellNow;
  const cell = useCallback<CellAct>((what, name, col, payload, how) => cellLive.current(what, name, col, payload, how), []);
  // The cell an element is, when it is one that is typed over.
  const cellOf = (el: EventTarget | null): { el: HTMLElement; name: string; col: string } | null => {
    if (!(el instanceof HTMLElement) || el.dataset.cell === undefined) return null;
    const name = el.closest<HTMLElement>("tr[data-part]")?.dataset.part;
    const col = el.dataset.col;
    return name !== undefined && col !== undefined ? { el, name, col } : null;
  };
  const cellKeys = (e: KeyPress) => {
    const on = cellOf(e.target);
    if (!on || e.ctrlKey || e.metaKey || e.altKey || e.nativeEvent.isComposing) return;
    const way = ({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" } as Record<string, Way | undefined>)[e.key];
    if (way) {
      e.preventDefault();
      const to = neighbor(names.length, typedCols.length, names.indexOf(on.name), typedCols.indexOf(on.col), way);
      if (to) goTo({ name: names[to[0]], col: typedCols[to[1]] });
      return;
    }
    // A yes or no has no field: Space sets it, as it does any checkbox.
    // Tab goes on from it to the next cell, as it does from a field, so a
    // row that is filled in with Tab is not left at a yes or no in the
    // middle of it. From the last cell Tab leaves the table.
    if (on.el.getAttribute("role") === "checkbox") {
      if (e.key !== "Tab") return;
      const to = neighbor(names.length, typedCols.length, names.indexOf(on.name), typedCols.indexOf(on.col), e.shiftKey ? "prev" : "next");
      if (!to) return;
      e.preventDefault();
      goTo({ name: names[to[0]], col: typedCols[to[1]] });
      return;
    }
    if (e.key === "Enter" || e.key === "F2") {
      e.preventDefault();
      cell("open", on.name, on.col, null);
    } else if (e.key === "Backspace" || e.key === "Delete") {
      e.preventDefault();
      cell("open", on.name, on.col, "");
    } else if (e.key.length === 1 && e.key !== " ") {
      // A character typed on a cell opens it and is the first one in it.
      e.preventDefault();
      cell("open", on.name, on.col, e.key);
    }
  };
  // The one cell Tab stops at: the one the keyboard was on last, while it
  // is drawn, and the first one drawn otherwise.
  const stopAtCell = (() => {
    if (!editable || !typedCols.length) return null;
    const at = stopCell ? names.indexOf(stopCell.name) : -1;
    if (stopCell && at >= view.first && at < view.last && typedCols.includes(stopCell.col)) return stopCell;
    return names.length ? { name: names[view.first], col: typedCols[0] } : null;
  })();

  const rowKeys = (e: KeyPress) => {
    const at = placeOf(e.target);
    if (at < 0 || e.altKey || e.ctrlKey || e.metaKey) return;
    const to = e.key === "ArrowDown" ? at + 1 : e.key === "ArrowUp" ? at - 1 : e.key === "Home" ? 0 : e.key === "End" ? page.length - 1 : null;
    if (to !== null) {
      e.preventDefault();
      if (to < 0 || to >= page.length || to === at) return;
      setStop(names[to]);
      if (to >= view.first && to < view.last) rowAt(to)?.focus();
      else {
        aimed.current = names[to];
        view.bring(to);
      }
    } else if (e.key === "Enter" || e.key === " ") {
      // Space would scroll the page, and a key held down is one press.
      e.preventDefault();
      if (!e.repeat) act("click", page[at].key);
    }
  };
  useLayoutEffect(() => {
    if (clickable || movable) setHead(props.sticky_header !== false ? (headRow.current?.parentElement?.offsetHeight ?? 0) : 0);
  });

  // A highlight on a row that asks to be brought into view: the table
  // turns to the row's page, and one that draws a window of its rows
  // scrolls to where the row is. The highlight itself does the rest once
  // the row is drawn. Each is brought once, so the person can leave again.
  const pointed = usePartMarks(node.id);
  const brought = useRef(new Set<number>());
  const [wanted, setWanted] = useState<string | null>(null);
  useEffect(() => {
    for (const mark of pointed) {
      if (!mark.scroll || mark.waits || brought.current.has(mark.n)) continue;
      const name = partName(mark.part);
      const at = shown.findIndex((e) => e.id === name);
      if (at < 0) {
        // A row the person filtered out is left there, also once it is
        // back. One that is not in the table yet is waited for.
        if (entries.some((e) => e.id === name)) brought.current.add(mark.n);
        continue;
      }
      brought.current.add(mark.n);
      if (pageSize) setPageIndex(Math.floor(at / pageSize));
      setWanted(name);
      break;
    }
  }, [pointed, shown, entries, pageSize]);
  const bring = view.bring;
  useEffect(() => {
    if (wanted === null || !distinct) return;
    const at = names.indexOf(wanted);
    if (at < 0) return;
    setWanted(null);
    bring(at);
  }, [wanted, names, distinct, bring]);

  const heads: Head[] = [];
  if (movable) heads.push({ id: "__grip", sortable: false, filterable: false, header: "", size: 28 });
  if (selection === "rows") {
    heads.push({
      id: "__select",
      sortable: false,
      filterable: false,
      size: 32,
      header: (
        <Checkbox
          checked={page.length > 0 && page.every((e) => selectedSet.has(e.id))}
          onCheckedChange={(checked) => {
            const here = new Set(page.map((e) => e.id));
            const others = selected.filter((k) => !here.has(JSON.stringify(k)));
            emit("select", checked ? [...others, ...page.map((e) => e.key)] : others);
          }}
          aria-label={t("select_all")}
        />
      ),
    });
  }
  const takes = visible.some(takesTheRest);
  for (const c of visible) {
    heads.push({
      id: c.key,
      header: c.header ?? c.key,
      sortable: c.sortable !== false && props.sortable !== false && !movable,
      filterable: c.filterable !== false,
      // A number is pixels, and text is a length as CSS writes one.
      size: typeof c.width === "number" || (typeof c.width === "string" && c.width) ? c.width : undefined,
      column: c,
      group: c.group,
    });
  }
  if (actions.length) heads.push({ id: "__actions", sortable: false, filterable: false, header: "", size: 40 });
  const bands = heads.some((h) => h.group) ? bandsOf(heads) : null;

  const total = entries.length;
  const summary = props.summary === false ? null : typeof props.summary === "string" ? props.summary : shown.length !== total ? t("rows_of", { shown: shown.length, n: total }) : total === 1 ? t("one_row") : t("rows", { n: total });

  return (
    <div className={cn("flex flex-col gap-2", props.fill ? "mw-fill min-h-24 grow" : undefined, props.cls as string)}>
      {props.search ? (
        <Input value={globalFilter} onChange={(e) => setGlobalFilter(e.target.value)} placeholder={t("search")} className="max-w-xs" />
      ) : null}
      <div
        // One that fills is as high as its rows, up to what the column it is
        // in has left, and scrolls from there.
        className={cn("mw-scroll overflow-auto rounded-lg border", props.height || props.fill ? "min-h-0" : undefined)}
        style={props.height ? { maxHeight: typeof props.height === "number" ? `${props.height}px` : String(props.height) } : undefined}
      >
        {/* The box above is the one scroller, both ways, so the header sticks to
            it: a scroller of the table's own in between would hold the header
            instead and never move. */}
        <div data-slot="table-container" className="relative w-full">
        <table data-slot="table" className="w-full caption-bottom text-sm">
          <TableHeader className={cn(props.sticky_header !== false && "sticky top-0 z-10 bg-background shadow-[0_1px_0_var(--border)]")}>
            {bands ? (
              // The row of the headers under it stays one cell a column,
              // which a long table measures its columns by.
              <TableRow className="border-b-0! hover:bg-transparent">
                {bands.map((band, i) =>
                  band.label ? (
                    // A header of every column it is over, which a screen
                    // reader then says before the column's own.
                    <TableHead key={i} colSpan={band.span} scope="col" className={cn("h-8 border-b text-center", band.edge && "border-l")}>
                      {band.label}
                    </TableHead>
                  ) : (
                    // Nothing to read out over columns that have no group.
                    <td key={i} colSpan={band.span} className={cn("h-8", band.edge && "border-l")} />
                  ),
                )}
              </TableRow>
            ) : null}
            <TableRow ref={headRow} className={bands ? "hover:bg-transparent" : undefined}>
              {heads.map((c) => {
                const sorted = sorting.find((s) => s.id === c.id);
                const Arrow = sorted ? icon(sorted.desc ? "arrow-down" : "arrow-up") : icon("arrow-up-down");
                return (
                  <TableHead
                    key={c.id}
                    // Beside a column that takes what is left, a width is
                    // kept: the room comes out of that column first. It is
                    // kept as a variable, which a long table's own hold on
                    // its columns reads and does not write over.
                    style={c.size !== undefined ? ({ width: c.size, "--mw-keep": takes ? (typeof c.size === "number" ? `${c.size}px` : c.size) : undefined } as CSSProperties) : undefined}
                    className={cn(takes && c.size !== undefined && "min-w-(--mw-keep)", c.column?.align === "right" && "text-right", c.column?.align === "center" && "text-center", c.edge && "border-l")}
                    aria-sort={sorted ? (sorted.desc ? "descending" : "ascending") : undefined}
                  >
                    {c.sortable ? (
                      <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={(e) => toggleSort(c.id, e.shiftKey)}>
                        {c.header}
                        {Arrow ? <Arrow className={cn("size-3", !sorted && "opacity-40")} /> : null}
                      </button>
                    ) : (
                      c.header
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
            {props.filters ? (
              <TableRow>
                {heads.map((c) => (
                  <TableHead key={c.id} className={cn("py-1", c.edge && "border-l")}>
                    {c.filterable ? <FilterCell kind={kinds[c.id] ?? { kind: "text" }} value={filters[c.id]} onChange={(v) => setFilter(c.id, v)} /> : null}
                  </TableHead>
                ))}
              </TableRow>
            ) : null}
          </TableHeader>
          <TableBody
            ref={body}
            style={clickable && head ? ({ "--mw-head": `${head}px` } as CSSProperties) : undefined}
            onKeyDown={clickable ? rowKeys : editable ? cellKeys : undefined}
            onFocus={
              clickable
                ? (e) => {
                    const at = placeOf(e.target);
                    if (at < 0) return;
                    setStop(names[at]);
                    on.current = { name: names[at], at };
                  }
                : editable
                  ? (e) => {
                      const at = cellOf(e.target);
                      if (!at) return;
                      onCell.current = { name: at.name, col: at.col, at: names.indexOf(at.name) };
                      if (stopCell?.name !== at.name || stopCell.col !== at.col) setStopCell({ name: at.name, col: at.col });
                    }
                  : undefined
            }
            onBlur={
              clickable
                ? (e) => {
                    if (placeOf(e.target) >= 0) on.current = null;
                  }
                : editable
                  ? (e) => {
                      // The keyboard was taken elsewhere, the field of this
                      // very cell included.
                      if (cellOf(e.target)) onCell.current = null;
                    }
                  : undefined
            }
          >
            {view.before > 0 ? (
              <tr aria-hidden="true">
                <td colSpan={heads.length} className="p-0" style={{ height: view.before }} />
              </tr>
            ) : null}
            {page.length ? (
              drawn.map((e, n) => (
                <Row
                  key={names[view.first + n]}
                  row={e.row}
                  rowKey={e.key}
                  part={e.id}
                  tone={toneRows[e.i]}
                  cellTones={toneCells[e.i]}
                  selected={selectedSet.has(e.id)}
                  columns={visible}
                  checkbox={selection === "rows"}
                  actions={actions}
                  clickable={clickable}
                  stop={view.first + n === stopAt}
                  act={act}
                  mark={movable ? drag.row(names[view.first + n]) : undefined}
                  grip={movable ? drag.grip(names[view.first + n]) : undefined}
                  cell={editable ? cell : undefined}
                  stopCol={stopAtCell && stopAtCell.name === e.id ? stopAtCell.col : null}
                  opened={opened && opened.name === e.id ? opened : null}
                  sent={sent.get(e.id) ?? null}
                />
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={heads.length} className="h-20 text-center text-muted-foreground">
                  {String(props.empty || "No rows")}
                </TableCell>
              </TableRow>
            )}
            {view.after > 0 ? (
              <tr aria-hidden="true">
                <td colSpan={heads.length} className="p-0" style={{ height: view.after }} />
              </tr>
            ) : null}
          </TableBody>
        </table>
        </div>
      </div>
      {summary || pageSize ? (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{summary}</span>
          {pageSize && pageCount > 1 ? (
            <span className="inline-flex items-center gap-1">
              <Button variant="ghost" size="xs" onClick={() => setPageIndex((i) => Math.max(0, i - 1))} disabled={pageIndex === 0}>
                {t("previous")}
              </Button>
              {pageIndex + 1} / {pageCount}
              <Button variant="ghost" size="xs" onClick={() => setPageIndex((i) => Math.min(pageCount - 1, i + 1))} disabled={pageIndex >= pageCount - 1}>
                {t("next")}
              </Button>
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

function RowActions({ items, onPick }: { items: MenuItem[]; onPick: (id: string) => void }) {
  const More = icon("more-horizontal");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" aria-label={t("actions")} />}>
        {More ? <More /> : "…"}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {items.map((it) => {
          const Icon = icon(it.icon);
          return (
            <div key={it.id}>
              <DropdownMenuItem disabled={Boolean(it.disabled)} variant={it.destructive ? "destructive" : "default"} onClick={() => onPick(it.id)}>
                {Icon ? <Icon /> : null}
                {it.label}
              </DropdownMenuItem>
              {it.separator_after ? <DropdownMenuSeparator /> : null}
            </div>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
