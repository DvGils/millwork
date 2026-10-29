// Number and date formats shared by the Table and the charts. Percent takes a
// fraction, so 0.12 reads as 12%.

const numberFormat = new Intl.NumberFormat(undefined);
const integerFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const percentFormat = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });
const currencyFormat = new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR" });
export const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
export const dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function formatNumber(value: unknown, format?: string | null): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  switch (format) {
    case "integer":
      return integerFormat.format(n);
    case "percent":
      return percentFormat.format(n);
    case "currency":
      return currencyFormat.format(n);
    default:
      return numberFormat.format(n);
  }
}
