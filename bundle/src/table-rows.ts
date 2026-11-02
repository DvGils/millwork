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

// Numbers by value, everything else as text with numeric runs in order.
export function compare(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function sortRows<R extends Record<string, unknown>>(rows: R[], sorting: Sort[]): R[] {
  if (!sorting.length) return rows;
  return rows
    .map((r, i) => [r, i] as const)
    .sort(([a, ia], [b, ib]) => {
      for (const s of sorting) {
        // An empty cell goes last whichever way the column is sorted.
        const ea = empty(a[s.id]), eb = empty(b[s.id]);
        if (ea || eb) {
          if (ea === eb) continue;
          return ea ? 1 : -1;
        }
        const c = compare(a[s.id], b[s.id]);
        if (c) return s.desc ? -c : c;
      }
      return ia - ib;
    })
    .map(([r]) => r);
}
