// Small shared helpers.

// Only URLs a browser may navigate to or embed: http(s), mailto, same-origin
// paths, and blob/data images where the caller allows them. Anything else
// (javascript:, vbscript:, data:text/html) becomes "about:blank".
// A URL the page may render: a same-origin path, under the app's prefix; an
// absolute http(s) or mailto URL; for an image a blob or data URL. Anything
// else, including a path with a dot segment that could climb out of the
// prefix, is about:blank.
export function safeUrl(value: unknown, opts: { image?: boolean } = {}): string {
  if (typeof value !== "string") return "about:blank";
  const v = value.trim();
  if (v.startsWith("/") && !v.startsWith("//") && !v.includes("\\") && !hasDotSegment(v)) return toBrowser(v);
  const lower = v.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://") || lower.startsWith("mailto:")) return v;
  // A fragment, or a path relative to the page: the browser resolves it under
  // the page's own URL, prefix included, so it needs no mapping. A scheme would
  // show as a colon before any slash.
  if (v.startsWith("#")) return v;
  if (!v.startsWith("/") && !v.includes("\\") && !/^[^/?#]*:/.test(v) && !hasDotSegment(v)) return v;
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

// The path prefix the app runs under, from the boot object the server wrote:
// "" at the root, else "/prefix". Paths inside the app (pages, links, the
// session's navigate) never carry it; only the browser's URLs and the
// framework's own routes do.
export function base(): string {
  if (typeof window === "undefined") return "";
  const b = (window as unknown as { __mw?: { base?: unknown } }).__mw?.base;
  return typeof b === "string" ? b.replace(/\/+$/, "") : "";
}

// An app path as the browser must ask for it. Anything that is not a path is
// returned as it is, so a checked URL stays checked.
export function toBrowser(path: string, prefix: string = base()): string {
  return prefix && path.startsWith("/") && !path.startsWith("//") ? prefix + path : path;
}

// The app path behind a browser pathname: the prefix removed when it is there.
export function toApp(pathname: string, prefix: string = base()): string {
  if (!prefix) return pathname;
  if (pathname === prefix) return "/";
  if (pathname.startsWith(prefix + "/")) return pathname.slice(prefix.length);
  return pathname;
}

// Where sign-out lands: the proxy's own sign-out page when one signed the
// person in (the server puts its URL on the boot user), otherwise millwork's
// login page.
export function signOutUrl(): string {
  const user = (window as unknown as { __mw?: { user?: { sign_out?: string | null } | null } }).__mw?.user;
  return user?.sign_out || mw("/login");
}

// One of the framework's own routes, under the prefix: mw("/auth/logout").
export function mw(path: string): string {
  return `${base()}/_mw${path}`;
}

// A "." or ".." segment in any spelling, which a browser resolves before it
// asks the server and which could climb out of the app's prefix. A segment
// that does not decode counts as one.
export function hasDotSegment(path: string): boolean {
  return path.split(/[?#]/, 1)[0].split("/").some((seg) => {
    let plain = seg;
    try {
      plain = decodeURIComponent(seg);
    } catch {
      return true;
    }
    return plain === "." || plain === "..";
  });
}

// A path inside the app's origin: no scheme, no host, no backslash, no dot segment.
export function isSameOriginPath(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") && !hasDotSegment(value);
}

// A path the session navigates to: inside the app, not a framework route or a
// static file.
export function isInternalPath(value: unknown): value is string {
  return isSameOriginPath(value) && !/^\/_mw(\/|$)/.test(value) && !/^\/public(\/|$)/.test(value);
}

// Controlled when the server put the key on the wire (an explicit None arrives as null).
export function has(props: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(props, key);
}
