// Number and date formats shared by the Table, the Stat and the charts, in the
// theme's locale and currency. Percent takes a fraction, so 0.12 reads as 12%.

import { currency, locale } from "./theme";

const formats = new Map<string, Intl.NumberFormat>();

function numberFormat(key: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  let f = formats.get(key);
  if (!f) {
    f = new Intl.NumberFormat(locale(), options);
    formats.set(key, f);
  }
  return f;
}

let dates: { date: Intl.DateTimeFormat; dateTime: Intl.DateTimeFormat } | null = null;
function dateFormats() {
  if (!dates) {
    dates = {
      date: new Intl.DateTimeFormat(locale(), { dateStyle: "medium" }),
      dateTime: new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" }),
    };
  }
  return dates;
}

export const dateFormat = { format: (d: Date) => dateFormats().date.format(d) };
export const dateTimeFormat = { format: (d: Date) => dateFormats().dateTime.format(d) };

// `axis` is for a tick: a currency in whole units, since a scale needs no cents.
export function formatNumber(value: unknown, format?: string | null, axis = false): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  switch (format) {
    case "integer":
      return numberFormat("integer", { maximumFractionDigits: 0 }).format(n);
    case "percent":
      return numberFormat("percent", { style: "percent", maximumFractionDigits: 1 }).format(n);
    case "currency":
      return axis
        ? numberFormat("currency-axis", { style: "currency", currency: currency(), maximumFractionDigits: 0 }).format(n)
        : numberFormat("currency", { style: "currency", currency: currency() }).format(n);
    default:
      return numberFormat("number", {}).format(n);
  }
}
