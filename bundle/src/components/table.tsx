// The Table on TanStack Table: every row in the browser, sort and filter here,
// selection reported to the server, tones instead of styles.

import { dateFormat, dateTimeFormat, formatNumber } from "../format";
import { t } from "../theme";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import type { Renderer } from "../render";
import { cn } from "cn";
import { icon } from "../icons";
import { safeUrl } from "../lib";
import {
  Table as UiTable,
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

type RowData = Record<string, unknown> & { __i: number; __key: unknown };

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

function rangeFilter(row: { getValue: (id: string) => unknown }, id: string, filter: unknown): boolean {
  const [min, max] = (Array.isArray(filter) ? filter : [null, null]) as [number | null, number | null];
  const v = row.getValue(id);
  if (min === null && max === null) return true;
  if (v === null || v === undefined || v === "") return false;
  const n = Number(v);
  if (Number.isNaN(n)) return false;
  return (min === null || n >= min) && (max === null || n <= max);
}

function equalsFilter(row: { getValue: (id: string) => unknown }, id: string, filter: unknown): boolean {
  if (filter === null || filter === undefined || filter === "") return true;
  const v = row.getValue(id);
  return v !== null && v !== undefined && String(v) === String(filter);
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
      return Icon ? <Icon className={cn("size-4", value ? "text-success" : "text-muted-foreground")} /> : String(value);
    }
    case "badge":
      return <Badge variant={badgeByTone[tone ?? "default"]}>{String(value)}</Badge>;
    case "link":
      return (
        <a href={safeUrl(value)} target="_blank" rel="noreferrer" className="text-primary underline-offset-4 hover:underline">
          {String(value)}
        </a>
      );
    case "code":
      return <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{String(value)}</code>;
    default:
      return String(value);
  }
}

export const Table: Renderer = ({ props, emit }) => {
  const rows = (Array.isArray(props.rows) ? (props.rows as Record<string, unknown>[]) : []);
  const keys = (Array.isArray(props.keys) ? (props.keys as unknown[]) : []);
  const columns = (Array.isArray(props.columns) ? (props.columns as Column[]) : []);
  const toneRows = (props.tone_rows ?? {}) as Record<string, string>;
  const toneCells = (props.tone_cells ?? {}) as Record<string, Record<string, string>>;
  const selection = String(props.selection ?? "none");
  const selected = (Array.isArray(props.selected) ? (props.selected as unknown[]) : []);
  const actions = (Array.isArray(props.row_actions) ? (props.row_actions as MenuItem[]) : []);
  const pageSize = typeof props.page_size === "number" ? props.page_size : null;

  const data = useMemo<RowData[]>(() => rows.map((r, i) => ({ ...r, __i: i, __key: keys[i] })), [rows, keys]);

  const [sorting, setSorting] = useState<SortingState>(() =>
    (Array.isArray(props.default_sort) ? (props.default_sort as [string, string][]) : []).map(([id, dir]) => ({ id, desc: dir === "desc" })),
  );
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const kinds = useMemo(() => Object.fromEntries(columns.map((c) => [c.key, filterKind(c, rows)])) as Record<string, FilterKind>, [columns, rows]);

  // The initial sort and the empty filter are the server's own: only a change
  // made here is reported.
  const settled = useRef(false);
  useEffect(() => {
    if (settled.current && props.on_sort) emit("sort", sorting.map((s) => [s.id, s.desc ? "desc" : "asc"]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sorting]);
  useEffect(() => {
    if (settled.current && props.on_filter) emit("filter", { columns: Object.fromEntries(columnFilters.map((f) => [f.id, f.value])), search: globalFilter });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columnFilters, globalFilter]);
  useEffect(() => {
    settled.current = true;
  }, []);

  const selectedSet = useMemo(() => new Set(selected.map((k) => JSON.stringify(k))), [selected]);
  const isSelected = (row: RowData) => selectedSet.has(JSON.stringify(row.__key));

  const select = (row: RowData, additive: boolean) => {
    if (selection === "none" || !props.on_select) return;
    const key = row.__key;
    if (selection === "row") {
      emit("select", isSelected(row) ? [] : [key]);
      return;
    }
    const next = selected.filter((k) => JSON.stringify(k) !== JSON.stringify(key));
    if (!isSelected(row)) next.push(key);
    emit("select", additive ? next : next);
  };

  const columnDefs = useMemo<ColumnDef<RowData>[]>(() => {
    const defs: ColumnDef<RowData>[] = [];
    if (selection === "rows") {
      defs.push({
        id: "__select",
        enableSorting: false,
        enableColumnFilter: false,
        header: ({ table }) => (
          <Checkbox
            checked={table.getRowModel().rows.length > 0 && table.getRowModel().rows.every((r) => isSelected(r.original))}
            onCheckedChange={(checked) => {
              const visible = table.getRowModel().rows.map((r) => r.original.__key);
              const visibleSet = new Set(visible.map((k) => JSON.stringify(k)));
              const others = selected.filter((k) => !visibleSet.has(JSON.stringify(k)));
              emit("select", checked ? [...others, ...visible] : others);
            }}
            aria-label={t("select_all")}
          />
        ),
        cell: ({ row }) => (
          <Checkbox checked={isSelected(row.original)} onCheckedChange={() => select(row.original, true)} aria-label={t("select_row")} />
        ),
        size: 32,
      });
    }
    for (const c of columns) {
      if (c.hidden) continue;
      defs.push({
        id: c.key,
        accessorFn: (r) => r[c.key],
        header: c.header ?? c.key,
        enableSorting: c.sortable !== false && props.sortable !== false,
        enableColumnFilter: c.filterable !== false,
        filterFn: kinds[c.key]?.kind === "number" ? rangeFilter : kinds[c.key]?.kind === "select" ? equalsFilter : "includesString",
        size: typeof c.width === "number" ? c.width : undefined,
        cell: ({ row, getValue }) => {
          const tone = toneCells[String(row.original.__i)]?.[c.key];
          return formatCell(getValue(), c.format ?? "text", tone);
        },
        meta: { column: c },
      });
    }
    if (actions.length) {
      defs.push({
        id: "__actions",
        enableSorting: false,
        enableColumnFilter: false,
        header: "",
        size: 40,
        cell: ({ row }) => <RowActions items={actions} onPick={(id) => emit("action", [id, row.original.__key])} />,
      });
    }
    return defs;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns, selection, actions, selected, toneCells, kinds]);

  const table = useReactTable({
    data,
    columns: columnDefs,
    state: { sorting, columnFilters, globalFilter },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: pageSize ? getPaginationRowModel() : undefined,
    initialState: pageSize ? { pagination: { pageSize } } : undefined,
    globalFilterFn: "includesString",
    // A rows patch (a task updating a column) must not bounce the user to page 1.
    autoResetPageIndex: false,
  });
  const pageCount = table.getPageCount();
  const pageIndex = table.getState().pagination.pageIndex;
  useEffect(() => {
    if (pageSize && pageCount > 0 && pageIndex >= pageCount) table.setPageIndex(pageCount - 1);
  }, [pageSize, pageCount, pageIndex, table]);

  const total = data.length;
  const shown = table.getFilteredRowModel().rows.length;
  const summary = props.summary === false ? null : typeof props.summary === "string" ? props.summary : shown === total ? `${total} rows` : `${shown} of ${total} rows`;

  return (
    <div className={cn("flex flex-col gap-2", props.cls as string)}>
      {props.search ? (
        <Input value={globalFilter} onChange={(e) => setGlobalFilter(e.target.value)} placeholder={t("search")} className="max-w-xs" />
      ) : null}
      <div
        className={cn("overflow-auto rounded-lg border", props.height && "min-h-0")}
        style={props.height ? { maxHeight: typeof props.height === "number" ? `${props.height}px` : String(props.height) } : undefined}
      >
        <UiTable>
          <TableHeader className={cn(props.sticky_header !== false && "sticky top-0 z-10 bg-background")}>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((h) => {
                  const col = (h.column.columnDef.meta as { column?: Column } | undefined)?.column;
                  const sorted = h.column.getIsSorted();
                  const Arrow = sorted ? icon(sorted === "asc" ? "arrow-up" : "arrow-down") : icon("arrow-up-down");
                  return (
                    <TableHead
                      key={h.id}
                      style={h.column.getSize() !== 150 ? { width: h.column.getSize() } : undefined}
                      className={cn(col?.align === "right" && "text-right", col?.align === "center" && "text-center")}
                    >
                      {h.isPlaceholder ? null : h.column.getCanSort() ? (
                        <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={h.column.getToggleSortingHandler()}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {Arrow ? <Arrow className={cn("size-3", !sorted && "opacity-40")} /> : null}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
            {props.filters ? (
              <TableRow>
                {table.getHeaderGroups()[0]?.headers.map((h) => (
                  <TableHead key={h.id} className="py-1">
                    {h.column.getCanFilter() ? (
                      <FilterCell kind={kinds[h.column.id] ?? { kind: "text" }} value={h.column.getFilterValue()} onChange={(v) => h.column.setFilterValue(v)} />
                    ) : null}
                  </TableHead>
                ))}
              </TableRow>
            ) : null}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => {
                const tone = toneRows[String(row.original.__i)];
                const clickable = selection === "row" || Boolean(props.on_row_click);
                return (
                  <TableRow
                    key={row.id}
                    data-state={isSelected(row.original) ? "selected" : undefined}
                    className={cn(tone && rowTone[tone], clickable && "cursor-pointer")}
                    onClick={(e) => {
                      // Clicks inside a portal (the actions menu) bubble through React, not the DOM.
                      if (!e.currentTarget.contains(e.target as Node)) return;
                      if ((e.target as HTMLElement).closest("button, a, [role=checkbox], [data-slot=dropdown-menu-trigger]")) return;
                      if (props.on_row_click) emit("row_click", row.original.__key);
                      if (selection === "row") select(row.original, false);
                    }}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const col = (cell.column.columnDef.meta as { column?: Column } | undefined)?.column;
                      return (
                        <TableCell
                          key={cell.id}
                          className={cn(
                            "py-(--mw-cell-y)",
                            col?.align === "right" && "text-right tabular-nums",
                            col?.align === "center" && "text-center",
                            !col?.wrap && "whitespace-nowrap",
                          )}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })
            ) : (
              <TableRow>
                <TableCell colSpan={columnDefs.length} className="h-20 text-center text-muted-foreground">
                  {String(props.empty || "No rows")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </UiTable>
      </div>
      {summary || pageSize ? (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{summary}</span>
          {pageSize && table.getPageCount() > 1 ? (
            <span className="inline-flex items-center gap-1">
              <Button variant="ghost" size="xs" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
                Previous
              </Button>
              {table.getState().pagination.pageIndex + 1} / {table.getPageCount()}
              <Button variant="ghost" size="xs" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
                Next
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
