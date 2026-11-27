// The Table: every row in the browser, sorted, filtered and paged here;
// selection reported to the server, tones instead of styles. A long table
// draws the rows in view, and a row is drawn again only when it changed.

import { partName, usePartMarks } from "../marks";
import { asDate, dateFormat, dateTimeFormat, formatNumber } from "../format";
import { t } from "../theme";
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
  width?: number | string | null;
  align?: "left" | "center" | "right";
  format?: string;
  sortable?: boolean;
  filterable?: boolean;
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
}

// One row, drawn again only when something it shows changed: the record is the
// same object from one patch to the next unless the patch touched it, and
// everything else here is a plain value or stable for the table's life.
const Row = memo(function Row({ row, rowKey, part, tone, cellTones, selected, columns, checkbox, actions, clickable, stop, act }: RowProps) {
  const takers = columns.filter(takesTheRest).length;
  // Whether shift was down for the press that is changing the checkbox. The
  // change itself does not say, and it comes during the click that does.
  const shift = useRef(false);
  return (
    <TableRow
      data-part={part}
      data-state={selected ? "selected" : undefined}
      data-press={clickable ? "" : undefined}
      tabIndex={clickable ? (stop ? 0 : -1) : undefined}
      className={cn(tone && rowTone[tone], clickable && rowFocus)}
      onClick={(e) => {
        if (ownPress(e)) act("click", rowKey);
      }}
    >
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

type Head = { id: string; header: ReactNode; sortable: boolean; filterable: boolean; size?: number | string; column?: Column };

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
  const page = useMemo(
    () => (pageSize ? shown.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize) : shown),
    [shown, pageSize, pageIndex],
  );
  now.current.page = page;

  const body = useRef<HTMLTableSectionElement>(null);
  const headRow = useRef<HTMLTableRowElement>(null);
  // Rows go by their key where keys tell them apart, by their place otherwise.
  const names = useMemo(() => page.map((e) => (distinct ? e.id : `#${e.i}`)), [page, distinct]);
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
  // How tall the header that stays over the rows is, filters and all.
  const [head, setHead] = useState(0);
  useLayoutEffect(() => {
    if (clickable) setHead(props.sticky_header !== false ? (headRow.current?.parentElement?.offsetHeight ?? 0) : 0);
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
      sortable: c.sortable !== false && props.sortable !== false,
      filterable: c.filterable !== false,
      // A number is pixels, and text is a length as CSS writes one.
      size: typeof c.width === "number" || (typeof c.width === "string" && c.width) ? c.width : undefined,
      column: c,
    });
  }
  if (actions.length) heads.push({ id: "__actions", sortable: false, filterable: false, header: "", size: 40 });

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
            <TableRow ref={headRow}>
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
                    className={cn(takes && c.size !== undefined && "min-w-(--mw-keep)", c.column?.align === "right" && "text-right", c.column?.align === "center" && "text-center")}
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
                  <TableHead key={c.id} className="py-1">
                    {c.filterable ? <FilterCell kind={kinds[c.id] ?? { kind: "text" }} value={filters[c.id]} onChange={(v) => setFilter(c.id, v)} /> : null}
                  </TableHead>
                ))}
              </TableRow>
            ) : null}
          </TableHeader>
          <TableBody
            ref={body}
            style={clickable && head ? ({ "--mw-head": `${head}px` } as CSSProperties) : undefined}
            onKeyDown={clickable ? rowKeys : undefined}
            onFocus={
              clickable
                ? (e) => {
                    const at = placeOf(e.target);
                    if (at < 0) return;
                    setStop(names[at]);
                    on.current = { name: names[at], at };
                  }
                : undefined
            }
            onBlur={
              clickable
                ? (e) => {
                    if (placeOf(e.target) >= 0) on.current = null;
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
