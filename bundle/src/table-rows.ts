// Sorting and filtering the rows of a Table, in the browser: plain functions
// over plain rows, so the Table renderer only decides what to show.

export function rangeFilter(v: unknown, filter: unknown): boolean {
  const [min, max] = (Array.isArray(filter) ? filter : [null, null]) as [number | null, number | null];
  if (min === null && max === null) return true;
  if (v === null || v === undefined || v === "") return false;
  const n = Number(v);
  if (Number.isNaN(n)) return false;
  return (min === null || n >= min) && (max === null || n <= max);
}

export function equalsFilter(v: unknown, filter: unknown): boolean {
  if (filter === null || filter === undefined || filter === "") return true;
  return v !== null && v !== undefined && String(v) === String(filter);
}

export function includesFilter(v: unknown, filter: unknown): boolean {
  const needle = typeof filter === "string" ? filter.trim().toLowerCase() : "";
  if (!needle) return true;
  return v !== null && v !== undefined && String(v).toLowerCase().includes(needle);
}

// A filter with nothing in it is no filter: it leaves the state, as it leaves the report to the server.
export function emptyFilter(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return true;
  return Array.isArray(value) && value.every((x) => x === null || x === undefined || x === "");
}

export type Sort = { id: string; desc: boolean };

function empty(v: unknown): boolean {
  return v === null || v === undefined || v === "";
}

// One collator for every comparison: a sort of thousands of rows compares
// text tens of thousands of times, and building the rules each time is most
// of what that costs.
const text = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

// Numbers by value, everything else as text with numeric runs in order.
export function compare(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  return text.compare(String(a), String(b));
}

// `cell` reads a column of a row, for rows that are not the plain record.
export function sortRows<R>(
  rows: R[],
  sorting: Sort[],
  cell: (row: R, id: string) => unknown = (row, id) => (row as Record<string, unknown>)[id],
): R[] {
  if (!sorting.length) return rows;
  return rows
    .map((r, i) => [r, i] as const)
    .sort(([a, ia], [b, ib]) => {
      for (const s of sorting) {
        // An empty cell goes last whichever way the column is sorted.
        const va = cell(a, s.id), vb = cell(b, s.id);
        const ea = empty(va), eb = empty(vb);
        if (ea || eb) {
          if (ea === eb) continue;
          return ea ? 1 : -1;
        }
        const c = compare(va, vb);
        if (c) return s.desc ? -c : c;
      }
      return ia - ib;
    })
    .map(([r]) => r);
}
