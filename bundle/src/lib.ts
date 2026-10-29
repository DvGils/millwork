// Small shared helpers.

// Only URLs a browser may navigate to or embed: http(s), mailto, same-origin
// paths, and blob/data images where the caller allows them. Anything else
// (javascript:, vbscript:, data:text/html) becomes "about:blank".
export function safeUrl(value: unknown, opts: { image?: boolean } = {}): string {
  if (typeof value !== "string") return "about:blank";
  const v = value.trim();
  if (v.startsWith("/") && !v.startsWith("//") && !v.includes("\\")) return v;
  const lower = v.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://") || lower.startsWith("mailto:")) return v;
  if (opts.image && (lower.startsWith("blob:") || lower.startsWith("data:image/"))) return v;
  return "about:blank";
}

// A heading's anchor: what the server computes for the manual's search links.
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function isInternalPath(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") && !value.startsWith("/_mw/") && !value.startsWith("/public/");
}

// Controlled when the server put the key on the wire (an explicit None arrives as null).
export function has(props: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(props, key);
}
