// The Table: every row in the browser, sorted, filtered and paged here;
// selection reported to the server, tones instead of styles. A long table
// draws the rows in view, and a row is drawn again only when it changed.

import { dateFormat, dateTimeFormat, formatNumber } from "../format";
import { t } from "../theme";
import { type ReactNode, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
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


function formatCell(value: unknown, format: string, tone?: string) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">–</span>;
  switch (format) {
    case "number":
    case "integer":
    case "percent":
    case "currency":
      return formatNumber(value, format);
    case "date":
      return dateFormat.format(new Date(String(value)));
    case "datetime":
      return dateTimeFormat.format(new Date(String(value)));
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

type Act = (what: "select" | "click" | "action", key: unknown, id?: string) => void;

const NONE: never[] = [];

interface RowProps {
  row: Record<string, unknown>;
  rowKey: unknown;
  tone: string | null | undefined;
  cellTones: Record<string, string> | null | undefined;
  selected: boolean;
  columns: Column[];
  checkbox: boolean;
  actions: MenuItem[];
  clickable: boolean;
  act: Act;
}

// One row, drawn again only when something it shows changed: the record is the
// same object from one patch to the next unless the patch touched it, and
// everything else here is a plain value or stable for the table's life.
const Row = memo(function Row({ row, rowKey, tone, cellTones, selected, columns, checkbox, actions, clickable, act }: RowProps) {
  return (
    <TableRow
      data-state={selected ? "selected" : undefined}
      className={cn(tone && rowTone[tone], clickable && "cursor-pointer")}
      onClick={(e) => {
        // Clicks inside a portal (the actions menu) bubble through React, not the DOM.
        if (!e.currentTarget.contains(e.target as Node)) return;
        if ((e.target as HTMLElement).closest("button, a, [role=checkbox], [data-slot=dropdown-menu-trigger]")) return;
        act("click", rowKey);
      }}
    >
      {checkbox ? (
        <TableCell className="py-(--mw-cell-y) whitespace-nowrap">
          <Checkbox checked={selected} onCheckedChange={() => act("select", rowKey)} aria-label={t("select_row")} />
        </TableCell>
      ) : null}
      {columns.map((c) => {
        const cellTone_ = cellTones?.[c.key];
        const content = formatCell(row[c.key], c.format ?? "text", cellTone_);
        return (
          <TableCell
            key={c.key}
            className={cn(
              "py-(--mw-cell-y)",
              c.align === "right" && "text-right tabular-nums",
              c.align === "center" && "text-center",
              c.wrap ? "whitespace-normal" : "whitespace-nowrap",
            )}
          >
            {cellTone_ && c.format !== "badge" && cellTone[cellTone_] ? <span className={cellTone[cellTone_]}>{content}</span> : content}
          </TableCell>
        );
      })}
      {actions.length ? (
        <TableCell className="py-(--mw-cell-y) whitespace-nowrap">
          <RowActions items={actions} onPick={(id) => act("action", rowKey, id)} />
        </TableCell>
      ) : null}
    </TableRow>
  );
});

type Head = { id: string; header: ReactNode; sortable: boolean; filterable: boolean; size?: number; column?: Column };

export const Table: Renderer = ({ props, emit }) => {
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
  const now = useRef({ selection, selected, selectedSet, emit, onSelect: Boolean(props.on_select), onRowClick: Boolean(props.on_row_click) });
  now.current = { selection, selected, selectedSet, emit, onSelect: Boolean(props.on_select), onRowClick: Boolean(props.on_row_click) };
  const act = useCallback<Act>((what, key, id) => {
    const { selection, selected, selectedSet, emit, onSelect, onRowClick } = now.current;
    const select = () => {
      if (selection === "none" || !onSelect) return;
      const text = JSON.stringify(key);
      const on = selectedSet.has(text);
      if (selection === "row") {
        emit("select", on ? [] : [key]);
        return;
      }
      const next = selected.filter((k) => JSON.stringify(k) !== text);
      if (!on) next.push(key);
      emit("select", next);
    };
    if (what === "action") emit("action", [id, key]);
    else if (what === "select") select();
    else {
      if (onRowClick) emit("row_click", key);
      if (selection === "row") select();
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
  for (const c of visible) {
    heads.push({
      id: c.key,
      header: c.header ?? c.key,
      sortable: c.sortable !== false && props.sortable !== false,
      filterable: c.filterable !== false,
      size: typeof c.width === "number" ? c.width : undefined,
      column: c,
    });
  }
  if (actions.length) heads.push({ id: "__actions", sortable: false, filterable: false, header: "", size: 40 });

  const clickable = selection === "row" || Boolean(props.on_row_click);
  const total = entries.length;
  const summary = props.summary === false ? null : typeof props.summary === "string" ? props.summary : shown.length === total ? `${total} rows` : `${shown.length} of ${total} rows`;

  return (
    <div className={cn("flex flex-col gap-2", props.cls as string)}>
      {props.search ? (
        <Input value={globalFilter} onChange={(e) => setGlobalFilter(e.target.value)} placeholder={t("search")} className="max-w-xs" />
      ) : null}
      <div
        className={cn("overflow-auto rounded-lg border", props.height && "min-h-0")}
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
                    style={c.size !== undefined ? { width: c.size } : undefined}
                    aria-sort={sorted ? (sorted.desc ? "descending" : "ascending") : undefined}
                    className={cn(c.column?.align === "right" && "text-right", c.column?.align === "center" && "text-center")}
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
          <TableBody ref={body}>
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
                  tone={toneRows[e.i]}
                  cellTones={toneCells[e.i]}
                  selected={selectedSet.has(e.id)}
                  columns={visible}
                  checkbox={selection === "rows"}
                  actions={actions}
                  clickable={clickable}
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
