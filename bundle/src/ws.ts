// The session socket: hello, resume, events, and the server's messages.
//
// Messages sent while the socket is not open are queued and flushed right
// after the next hello, so a click during a reconnect is delayed, not lost.

import { useEffect, useState } from "react";
import { applyTheme, t, type ThemeBoot } from "./theme";
import { store, type Node, type PatchOp } from "./store";
import { samePath, safeUrl, signOut, toApp, toBrowser } from "./lib";
import { toast } from "@/components/ui/toast";
import { invalidate, syncVersions } from "./custom";
import { ensureTailwindRuntime, needsRuntime, runtimeLoaded } from "./tailwind-runtime";
import { markdownLoaded, needsMarkdown, preloadMarkdown } from "./components/markdown";
import { keepScrollInHistory, restoreScroll, scrollFromHistory, watchScroll } from "./scroll";

interface Boot {
  path: string;
  protocol: number;
  ws: string;
  keep_alive?: boolean;
}

type ServerMessage =
  | { type: "mount"; root: string; nodes: Record<string, Node>; title: string | null }
  | { type: "patch"; ops: PatchOp[] }
  | { type: "stream"; node: string; chunk: Record<string, unknown> }
  | { type: "command"; name: string; args: Record<string, unknown> }
  | { type: "session"; id: string; resume: string; protocol: number; components?: Record<string, string> }
  | { type: "ask"; request: string; node: string; timeout: number | null }
  | { type: "error"; message: string; fatal: boolean }
  | { type: "head"; request: string; payload: unknown }
  | { type: "reply"; request: string; payload: unknown; error: string | null };

type Envelope<T> = { seq: number; msg: T };

export type Status = "connecting" | "open" | "reconnecting" | "closed";

const listeners = new Set<(s: Status) => void>();
const streamListeners = new Map<string, Set<(chunk: Record<string, unknown>) => void>>();

let socket: WebSocket | null = null;
let status: Status = "connecting";
// Why the session is over, once it is: shown with the reload offer.
let endReason: string | null = null;
let sessionId: string | null = null;
let resumeToken: string | null = null;
let lastSeq = 0;
let outSeq = 0;
let retry = 0;
let closedForGood = false;
const queue: Record<string, unknown>[] = [];

// Outside a browser (the unit tests import this module) there is no boot object.
const boot: Boot =
  typeof window !== "undefined" && (window as unknown as { __mw?: Boot }).__mw
    ? (window as unknown as { __mw: Boot }).__mw
    : { path: "/", protocol: 1, ws: "/_mw/ws" };

// Keep-alive: a host that scales to zero on idle HTTP does not count the
// websocket, so the tab touches the health route every 30 s while the session
// has work running (the server says so) or, with App(keep_alive=True), always.
let busy = false;
const KEEP_ALIVE_MS = 30_000;
if (typeof window !== "undefined") {
  setInterval(() => {
    if (!(boot.keep_alive || busy)) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const health = boot.ws.replace(/\/ws$/, "/health");
    void fetch(health, { cache: "no-store", credentials: "same-origin" }).catch(() => undefined);
  }, KEEP_ALIVE_MS);
}

function setStatus(s: Status) {
  status = s;
  for (const l of listeners) l(s);
}

export function closedReason(): string | null {
  return endReason;
}

// The connection status as React state; overlays close themselves once the
// session has ended, since nothing behind them can answer any more.
export function useStatus(): Status {
  const [s, setS] = useState<Status>(status);
  useEffect(() => onStatus(setS), []);
  return s;
}

export function onStatus(l: (s: Status) => void): () => void {
  listeners.add(l);
  l(status);
  return () => {
    listeners.delete(l);
  };
}

export function onStream(node: string, l: (chunk: Record<string, unknown>) => void): () => void {
  let set = streamListeners.get(node);
  if (!set) {
    set = new Set();
    streamListeners.set(node, set);
  }
  set.add(l);
  return () => {
    set!.delete(l);
  };
}

export function getSessionId(): string | null {
  return sessionId;
}

export function getResumeToken(): string | null {
  return resumeToken;
}

function sendNow(msg: Record<string, unknown>) {
  outSeq += 1;
  socket!.send(JSON.stringify({ seq: outSeq, msg }));
}

function send(msg: Record<string, unknown>) {
  if (socket && socket.readyState === WebSocket.OPEN && status === "open") sendNow(msg);
  else if (!closedForGood) queue.push(msg);
}

export function emit(node: string, name: string, payload: unknown = null) {
  send({ type: "event", node, name, payload });
}
if (typeof window !== "undefined") (window as unknown as { __mwEmit?: typeof emit }).__mwEmit = emit;

export function answer(request: string, payload: unknown) {
  send({ type: "answer", request, payload });
}

// ---------------------------------------------------------------- requests
//
// A request is something the session answers over the socket without a render:
// a handler's return value (a Combobox search), one of the session's files, or
// an upload. Bytes travel as binary frames tagged with the request id. A request
// lives within one socket connection: when the socket goes, every pending
// request rejects, and the component asks again if it still wants to.

const CHUNK = 256 * 1024;
const BUFFER_HIGH = 1024 * 1024;

interface Pending {
  resolve: (v: unknown) => void;
  reject: (e: Error) => void;
  onHead?: (meta: unknown) => void;
  onChunk?: (data: Uint8Array) => void;
}
const pending = new Map<string, Pending>();

export interface RequestOptions {
  /** Bytes to send after the message; `size` is announced so the server can refuse early. */
  body?: Blob;
  onProgress?: (fraction: number) => void;
  onHead?: (meta: unknown) => void;
  onChunk?: (data: Uint8Array) => void;
}

export interface Ongoing<T> extends Promise<T> {
  cancel: () => void;
}

function packFrame(request: string, data: Uint8Array): Uint8Array {
  const id = new TextEncoder().encode(request);
  const out = new Uint8Array(1 + id.length + data.length);
  out[0] = id.length;
  out.set(id, 1);
  out.set(data, 1 + id.length);
  return out;
}

function unpackFrame(buffer: ArrayBuffer): [string, Uint8Array] | null {
  const bytes = new Uint8Array(buffer);
  if (!bytes.length) return null;
  const n = bytes[0];
  if (n === 0 || n > 32 || bytes.length < 1 + n) return null;
  return [new TextDecoder().decode(bytes.subarray(1, 1 + n)), bytes.subarray(1 + n)];
}

function requestId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function request(node: string, name: string, payload: unknown = null, opts: RequestOptions = {}): Ongoing<unknown> {
  const id = requestId();
  let settled = false;
  const promise = new Promise<unknown>((resolve, reject) => {
    pending.set(id, {
      resolve: (v) => {
        settled = true;
        resolve(v);
      },
      reject: (e) => {
        settled = true;
        reject(e);
      },
      onHead: opts.onHead,
      onChunk: opts.onChunk,
    });
    const msg: Record<string, unknown> = { type: "request", node, name, request: id, payload };
    if (opts.body) msg.size = opts.body.size;
    if (!socket || socket.readyState !== WebSocket.OPEN || status !== "open") {
      pending.delete(id);
      reject(new Error("not connected"));
      return;
    }
    sendNow(msg);
    if (opts.body) void stream(id, opts.body, opts.onProgress, () => settled);
  }) as Ongoing<unknown>;
  promise.cancel = () => {
    const p = pending.get(id);
    if (!p) return;
    pending.delete(id);
    if (socket && socket.readyState === WebSocket.OPEN) sendNow({ type: "cancel", request: id });
    p.reject(new Error("cancelled"));
  };
  return promise;
}

// The body in frames, holding back while the socket's buffer is full so a big
// file never sits in memory twice.
async function stream(id: string, body: Blob, onProgress: ((f: number) => void) | undefined, done: () => boolean) {
  const total = body.size;
  let sent = 0;
  while (sent < total && !done()) {
    const s = socket;
    if (!s || s.readyState !== WebSocket.OPEN) return;
    if (s.bufferedAmount > BUFFER_HIGH) {
      await new Promise((r) => setTimeout(r, 20));
      continue;
    }
    const slice = body.slice(sent, Math.min(total, sent + CHUNK));
    const bytes = new Uint8Array(await slice.arrayBuffer());
    const again = socket;
    if (!again || again !== s || again.readyState !== WebSocket.OPEN) return;
    again.send(packFrame(id, bytes));
    sent += bytes.length;
    onProgress?.(sent / total);
  }
}

function rejectPending(why: string) {
  const all = Array.from(pending.values());
  pending.clear();
  for (const p of all) p.reject(new Error(why));
}

// One of the session's files, as a blob URL the tab keeps for the session.
const fileUrls = new Map<string, Promise<string>>();
export function fileUrl(id: string): Promise<string> {
  let p = fileUrls.get(id);
  if (p) return p;
  const parts: Uint8Array[] = [];
  let mime = "application/octet-stream";
  p = request("", "file", { id }, {
    onHead: (meta) => {
      mime = String((meta as { mime?: string })?.mime ?? mime);
    },
    onChunk: (data) => parts.push(data.slice()),
  }).then(() => URL.createObjectURL(new Blob(parts as BlobPart[], { type: mime })));
  p.catch(() => fileUrls.delete(id));
  fileUrls.set(id, p);
  return p;
}

export function saveFile(id: string, filename: string): Promise<void> {
  return fileUrl(id).then((url) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  });
}

function forgetFiles() {
  for (const p of fileUrls.values()) void p.then((url) => URL.revokeObjectURL(url)).catch(() => undefined);
  fileUrls.clear();
}

// A hash names a heading on the page being opened: the server never sees it,
// the tab scrolls there once the page has mounted. Without one, the page
// opens at the top, or where the reader left it when the history brings it back.
let pendingHash: string | null = null;
let pendingScroll: number | null = null;
let poppedScroll: number | null = null;
export function navigate(path: string) {
  const [bare, hash] = path.split("#", 2);
  pendingHash = hash || null;
  send({ type: "navigate", path: bare });
}

// Settles when the promise does, or after the wait, whichever comes first,
// and says which it was.
function within(p: Promise<unknown>, ms: number): Promise<boolean> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(false), ms);
    const done = () => {
      window.clearTimeout(timer);
      resolve(true);
    };
    p.then(done, done);
  });
}

function scrollToHash(hash: string, tries = 20) {
  const el = document.getElementById(hash);
  if (el) {
    el.scrollIntoView({ block: "start" });
    return;
  }
  // The heading may be inside a lazy chunk still loading.
  if (tries > 0) window.setTimeout(() => scrollToHash(hash, tries - 1), 100);
}

function storeSession() {
  try {
    sessionStorage.setItem("mw:session", JSON.stringify({ id: sessionId, resume: resumeToken, path: boot.path }));
  } catch {
    // storage may be unavailable; a reload then starts a fresh session
  }
}

// Two things a page may need that arrive after the bundle: the runtime
// compiler for a class the precompiled stylesheet lacks, and the Markdown
// renderer's chunk. Drawn before they have loaded, the page would paint
// without them and then jump, so the first page that needs one waits, parked
// with everything about the page that follows it, while the page before stays
// on screen. The wait is bounded, and after a wait that ran out the page is
// drawn as it is from then on.
let parked: ServerMessage[] | null = null;
let gaveUp = false;

function stillLoading(nodes: Record<string, Node>): Promise<unknown> | null {
  const waits: Promise<unknown>[] = [];
  if (!runtimeLoaded() && needsRuntime(nodes)) waits.push(ensureTailwindRuntime());
  if (!markdownLoaded() && needsMarkdown(nodes)) waits.push(preloadMarkdown());
  return waits.length ? Promise.all(waits) : null;
}

function park(m: ServerMessage): boolean {
  if (parked === null) return false;
  if (m.type === "mount" || m.type === "patch" || m.type === "stream" || m.type === "command") {
    parked.push(m);
    return true;
  }
  return false;
}

function handle(env: Envelope<ServerMessage>) {
  const m = env.msg;
  if (m.type !== "session") {
    // Numbered messages arrive once, in order: a duplicate from a replay that
    // overlapped a live send is dropped. Seq 0 is unnumbered (a reply, a head,
    // a message before any session) and leaves the counter alone.
    if (env.seq > 0) {
      if (env.seq <= lastSeq) return;
      lastSeq = env.seq;
    }
  }
  if (park(m)) return;
  apply(m);
}

function apply(m: ServerMessage) {
  switch (m.type) {
    case "session": {
      // The same session: what was queued while disconnected goes now, in order.
      // A new one: the old session's clicks and queries would land on fresh
      // state, so they are dropped, as are the files the old session held.
      const same = m.id === sessionId;
      if (!same) {
        lastSeq = 0;
        queue.length = 0;
        if (sessionId !== null) forgetFiles();
      }
      sessionId = m.id;
      resumeToken = m.resume;
      storeSession();
      if (m.components) syncVersions(m.components);
      setStatus("open");
      while (queue.length && socket && socket.readyState === WebSocket.OPEN) sendNow(queue.shift()!);
      break;
    }
    case "mount": {
      const loading = gaveUp ? null : stillLoading(m.nodes);
      if (loading) {
        parked = [m];
        void within(loading, 2000).then((inTime) => {
          gaveUp = !inTime;
          const queued = parked ?? [];
          parked = null;
          for (const q of queued) apply(q);
        });
        break;
      }
      store.mount(m.root, m.nodes, m.title);
      const hash = pendingHash ?? (window.location.hash ? window.location.hash.slice(1) : null);
      pendingHash = null;
      if (hash) window.setTimeout(() => scrollToHash(hash), 50);
      else if (pendingScroll !== null) restoreScroll(pendingScroll);
      pendingScroll = null;
      break;
    }
    case "patch":
      store.patch(m.ops);
      break;
    case "stream": {
      const set = streamListeners.get(m.node);
      if (set) for (const l of set) l(m.chunk);
      break;
    }
    case "command":
      command(m.name, m.args);
      break;
    case "error":
      if (m.fatal) {
        closedForGood = true;
        endReason = m.message;
        setStatus("closed");
      } else {
        toast.add({ title: m.message, type: "error" });
      }
      break;
    case "ask":
      window.dispatchEvent(new CustomEvent("mw:ask", { detail: m }));
      break;
    case "head": {
      pending.get(m.request)?.onHead?.(m.payload);
      break;
    }
    case "reply": {
      const p = pending.get(m.request);
      if (!p) break;
      pending.delete(m.request);
      if (m.error) p.reject(new Error(m.error));
      else p.resolve(m.payload);
      break;
    }
  }
}

function command(name: string, args: Record<string, unknown>) {
  switch (name) {
    case "toast": {
      const tone = String(args.tone ?? "default");
      const type = tone === "destructive" ? "error" : tone === "success" || tone === "warning" ? tone : tone === "primary" || tone === "accent" ? "info" : undefined;
      const message = String(args.message ?? "");
      const action = args.action as { id: string; label: string } | undefined;
      const actionProps = action
        ? { children: action.label, onClick: () => emit(`toast:${action.id}`, "action") }
        : undefined;
      toast.add(args.title ? { title: String(args.title), description: message, type, actionProps } : { title: message, type, actionProps });
      break;
    }
    case "navigate": {
      // The server already switched the session's page; the tab follows without a reload.
      const path = String(args.path);
      boot.path = path;
      storeSession();
      if (args.hash) pendingHash = String(args.hash);
      const browserPath = toBrowser(path);
      const target = pendingHash ? `${browserPath}#${pendingHash}` : browserPath;
      // Compared as app paths: the prefix with and without its slash is one page,
      // so a popped history entry is never pushed over.
      if (!samePath(toApp(window.location.pathname), path) || window.location.hash !== (pendingHash ? `#${pendingHash}` : "")) {
        keepScrollInHistory();
        window.history.pushState({ mw: true }, "", target);
      }
      if (args.title) document.title = String(args.title);
      // The mount that follows opens the page at the top, or where it was
      // left when the back or forward button brought it back.
      pendingScroll = poppedScroll ?? 0;
      poppedScroll = null;
      break;
    }
    case "title":
      document.title = String(args.title ?? "");
      break;
    case "clipboard":
      void navigator.clipboard?.writeText(String(args.text ?? ""));
      toast.add({ title: t("copied"), type: "success", timeout: 1500 });
      break;
    case "print":
      // After two frames: the patch that came just before has been drawn by then.
      requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
      break;
    case "reload":
      closedForGood = true;
      window.location.reload();
      break;
    case "theme":
      applyTheme(args as { css?: string; boot?: ThemeBoot });
      break;
    case "logout":
      closedForGood = true;
      void signOut();
      break;
    case "leave":
      // The sign-in behind this session is over: the page goes, not only its input.
      closedForGood = true;
      window.location.assign(safeUrl(String(args.to ?? "/")));
      break;
    case "reload_component":
      invalidate(args.name ? String(args.name) : undefined, args.version ? String(args.version) : undefined);
      window.dispatchEvent(new CustomEvent("mw:reload-component", { detail: { name: args.name } }));
      break;
    case "download": {
      void saveFile(String(args.id), String(args.filename ?? "")).catch(() => {
        toast.add({ title: t("download_failed"), type: "error" });
      });
      break;
    }
    case "activity":
      busy = Boolean(args.busy);
      break;
    case "form_issues":
      window.dispatchEvent(new CustomEvent("mw:form-issues", { detail: { node: String(args.node), issues: args.issues ?? [] } }));
      break;
    case "reset":
      store.reset(String(args.key));
      break;
    default:
      console.warn("millwork: unknown command", name, args);
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", () => {
    const path = toApp(window.location.pathname);
    if (!samePath(path, boot.path)) {
      poppedScroll = scrollFromHistory();
      navigate(path + window.location.hash);
    }
  });
  watchScroll();
}

export function connect() {
  if (closedForGood) return;
  const url = new URL(boot.ws, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  setStatus(sessionId ? "reconnecting" : "connecting");
  socket = new WebSocket(url.toString());
  socket.binaryType = "arraybuffer";

  socket.onopen = () => {
    retry = 0;
    let stored: { id: string; resume: string; path: string } | null = null;
    try {
      const raw = sessionStorage.getItem("mw:session");
      stored = raw ? JSON.parse(raw) : null;
    } catch {
      stored = null;
    }
    const resumable = stored && samePath(stored.path, boot.path) ? stored : null;
    sendNow({
      type: "hello",
      path: boot.path,
      session: sessionId ?? resumable?.id ?? null,
      resume: resumeToken ?? resumable?.resume ?? null,
      seq: sessionId ? lastSeq : 0,
      protocol: boot.protocol,
    });
    // "open" comes with the session message: nothing else is sent before the
    // server has said which session this socket speaks for.
  };

  socket.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      const frame = unpackFrame(ev.data);
      if (frame) pending.get(frame[0])?.onChunk?.(frame[1]);
      return;
    }
    try {
      handle(JSON.parse(ev.data as string) as Envelope<ServerMessage>);
    } catch (e) {
      console.error("millwork: bad message", e);
    }
  };

  socket.onclose = (ev) => {
    socket = null;
    rejectPending(t("disconnected"));
    if (closedForGood || ev.code === 4426) return;
    if (ev.code === 4409) {
      // Another tab took this session over.
      closedForGood = true;
      endReason = t("other_tab");
      setStatus("closed");
      return;
    }
    setStatus("reconnecting");
    const delay = Math.min(10000, 500 * 2 ** retry);
    retry += 1;
    window.setTimeout(connect, delay);
  };
}
