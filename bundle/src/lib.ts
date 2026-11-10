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

// Where sign-out lands. The proxy's own sign-out page comes first when one
// signed the person in (the server puts its URL on the boot user), since only
// going there signs them out. Otherwise it is where the app's on_logout said,
// which the server's answer to the sign-out carries, or millwork's login page.
export function signOutUrl(next?: unknown): string {
  const user = (window as unknown as { __mw?: { user?: { sign_out?: string | null } | null } }).__mw?.user;
  if (user?.sign_out) return user.sign_out;
  return typeof next === "string" && next ? safeUrl(next) : mw("/login");
}

// Sign out, then leave the page whether or not the server answered.
export async function signOut(): Promise<void> {
  let next: unknown = null;
  try {
    const response = await fetch(mw("/auth/logout"), { method: "POST" });
    next = ((await response.json()) as { next?: unknown }).next;
  } catch {
    next = null;
  }
  window.location.assign(signOutUrl(next));
}

// Whether two paths name the same page. One may be spelled as the address bar
// has it, percent signs and all, and the other as the app wrote it, so both
// are decoded before they are compared. A path that does not decode is its
// own spelling.
export function samePath(a: string, b: string): boolean {
  const plain = (p: string) => {
    try {
      return decodeURI(p);
    } catch {
      return p;
    }
  };
  return plain(a) === plain(b);
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

// How a link in running text looks. It is underlined, faintly, since under a
// theme whose primary is the color of the text nothing else tells it from
// the words around it, and the line firms up under the pointer.
export const linkLook = "underline decoration-current/35 underline-offset-4 hover:decoration-current";

// The login page has no session and no socket: a link there is the browser's
// to follow, where on a page of the app the session changes page.
export function hasSession(): boolean {
  return !(window as unknown as { __mw?: { login?: unknown } }).__mw?.login;
}

// Controlled when the server put the key on the wire (an explicit None arrives as null).
export function has(props: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(props, key);
}

// Above this many characters a text field stops being spellchecked. The
// browser's spellchecker marks every word of a change, and on a long paste
// that takes seconds and freezes the tab; a field this long is not prose
// anyone is proofreading in place. Back under it, checking resumes.
export const LONG_TEXT = 5000;
export function spellcheckForLength(field: { value: string; spellcheck: boolean }) {
  const wanted = field.value.length <= LONG_TEXT;
  if (field.spellcheck !== wanted) field.spellcheck = wanted;
}

// The classes of a component that gets a box put around it, in two parts:
// those that place it among its neighbours, which the box takes over, and
// the rest, which stay on the component. Its width, its margins, how it
// grows and shrinks, where it sits in a grid or on the page, and whether it
// shows at all are the box's. A height, a color, a font and anything not
// known here stay where they were.
const PLACES =
  /^-?(?:w|min-w|max-w|m[trblxyse]?|grow|shrink|basis|self|justify-self|place-self|order|col-span|col-start|col-end|row-span|row-start|row-end|inset|inset-x|inset-y|top|right|bottom|left|start|end|z)(?:-.+)?$/;
const PLACES_WHOLE = new Set([
  "hidden", "block", "inline-block", "inline", "flex", "inline-flex", "grid", "inline-grid", "contents",
  "absolute", "relative", "fixed", "sticky", "static",
  "flex-1", "flex-auto", "flex-initial", "flex-none", "col-auto", "row-auto",
  "visible", "invisible", "collapse",
]);

// A class without the conditions in front of it ("md:hover:w-64" is "w-64"),
// where a colon inside brackets belongs to a value and not to a condition.
function utility(name: string): string {
  let depth = 0;
  let from = 0;
  for (let i = 0; i < name.length; i++) {
    const c = name[i];
    if (c === "[" || c === "(") depth++;
    else if (c === "]" || c === ")") depth--;
    else if (c === ":" && depth === 0) from = i + 1;
  }
  return name.slice(from).replace(/^!|!$/g, "");
}

export function placed(cls: unknown): { box: string; rest: string } {
  const box: string[] = [];
  const rest: string[] = [];
  for (const name of typeof cls === "string" ? cls.split(/\s+/).filter(Boolean) : []) {
    const base = utility(name);
    (PLACES_WHOLE.has(base) || PLACES.test(base) ? box : rest).push(name);
  }
  return { box: box.join(" "), rest: rest.join(" ") };
}
