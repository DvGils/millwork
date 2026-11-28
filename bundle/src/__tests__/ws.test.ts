// The socket module against a fake WebSocket: sequencing, the request layer,
// uploads across a reconnect, frames, and the file cache.

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../theme", () => ({ applyTheme: vi.fn(), t: (k: string) => k }));
vi.mock("../store", () => ({ store: { mount: vi.fn(), patch: vi.fn(), reset: vi.fn() } }));
vi.mock("../custom", () => ({ invalidate: vi.fn() }));
vi.mock("../tailwind-runtime", () => ({ ensureTailwindRuntime: vi.fn(() => Promise.resolve()), needsRuntime: () => false, runtimeLoaded: () => true }));
vi.mock("../components/markdown", () => ({ preloadMarkdown: vi.fn(() => Promise.resolve()), needsMarkdown: () => false, markdownLoaded: () => true }));
vi.mock("../scroll", () => ({ keepScrollInHistory: vi.fn(), restoreScroll: vi.fn(), scrollFromHistory: () => 0, watchScroll: vi.fn() }));
vi.mock("@/components/ui/toast", () => ({ toast: { add: vi.fn() } }));

class FakeSocket {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  static all: FakeSocket[] = [];
  readyState = 0;
  bufferedAmount = 0;
  binaryType = "blob";
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }
  send(d: unknown) { this.sent.push(d); }
  open() { this.readyState = 1; this.onopen?.(); }
  text(seq: number, msg: unknown) { this.onmessage?.({ data: JSON.stringify({ seq, msg }) }); }
  bin(buf: ArrayBuffer) { this.onmessage?.({ data: buf }); }
  close(code = 1006) { this.readyState = 3; this.onclose?.({ code }); }
  json(): any[] { return this.sent.filter((x) => typeof x === "string").map((x) => JSON.parse(x as string)); }
  frames(): Uint8Array[] { return this.sent.filter((x) => x instanceof Uint8Array) as Uint8Array[]; }
}

const storage: Record<string, string> = {};
(globalThis as any).sessionStorage = { getItem: (k: string) => storage[k] ?? null, setItem: (k: string, v: string) => { storage[k] = v; } };
(globalThis as any).window = {
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  location: { href: "http://localhost/", pathname: "/" },
  history: { pushState() {} },
  setTimeout: (...a: any[]) => (globalThis.setTimeout as any)(...a),
};
(globalThis as any).WebSocket = FakeSocket;
(globalThis as any).document = { title: "" };

const ws = await import("../ws");
const { store } = await import("../store");

const tick = () => new Promise((r) => setTimeout(r, 0));
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const last = () => FakeSocket.all[FakeSocket.all.length - 1];

function session(s: FakeSocket, id = "S1") { s.text(0, { type: "session", id, resume: "R", protocol: 1 }); }
async function reconnect(): Promise<FakeSocket> {
  const before = FakeSocket.all.length;
  last().close();
  for (let i = 0; i < 300 && FakeSocket.all.length === before; i++) await sleep(10);
  const s = last();
  s.open();
  return s;
}

describe("ws request layer", () => {
  it("an unnumbered reply leaves lastSeq alone, so the next hello resumes", async () => {
    ws.connect();
    const s1 = last();
    s1.open();
    session(s1);
    s1.text(7, { type: "patch", ops: [] });
    expect(s1.json().at(-1)?.msg.type).toBe("hello");
    // a search reply (seq 0, unnumbered)
    const p = ws.request("n", "search", "q");
    const rid = s1.json().at(-1).msg.request;
    s1.text(0, { type: "reply", request: rid, payload: [], error: null });
    await expect(p).resolves.toEqual([]);
    const s2 = await reconnect();
    const hello = s2.json()[0].msg;
    expect(hello.seq).toBe(7);
  });

  it("the hello names the browser's time zone", () => {
    ws.connect();
    const s = last();
    s.open();
    expect(s.json()[0].msg.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });

  it("a duplicate numbered message after a reply is still dropped", async () => {
    const s = last();
    session(s);
    (store.patch as any).mockClear();
    s.text(9, { type: "patch", ops: ["x"] });
    const p = ws.request("n", "search", "q");
    const rid = s.json().at(-1).msg.request;
    s.text(0, { type: "reply", request: rid, payload: [], error: null });
    await p;
    s.text(9, { type: "patch", ops: ["x"] }); // replayed duplicate
    expect((store.patch as any).mock.calls.length).toBe(1);
  });

  it("stream() sends nothing of an old upload on a new socket", async () => {
    const s = last();
    const body = new Blob([new Uint8Array(3 * 256 * 1024 + 5)]);
    s.bufferedAmount = 10 * 1024 * 1024; // hold the sender back
    const p = ws.request("n", "upload", { name: "f" }, { body });
    p.catch(() => undefined);
    await sleep(50);
    expect(s.frames().length).toBe(0);
    const s2 = await reconnect();
    await expect(p).rejects.toThrow("disconnected");
    session(s2);
    await sleep(100);
    expect(s2.frames().length).toBe(0);
    expect(s2.json().filter((m) => m.msg.type === "request").length).toBe(0);
  });

  it("cancel() stops the sender; frames stop after at most one more chunk", async () => {
    const s = last();
    const body = new Blob([new Uint8Array(4 * 256 * 1024)]);
    s.bufferedAmount = 0;
    const p = ws.request("n", "upload", { name: "f" }, { body });
    p.catch(() => undefined);
    await tick();
    const before = s.frames().length;
    p.cancel();
    await expect(p).rejects.toThrow("cancelled");
    await sleep(50);
    expect(s.frames().length - before).toBeLessThanOrEqual(1);
    expect(s.json().at(-1).msg.type).toBe("cancel");
  });

  it("emit before the session message is queued and flushed after it, not dropped", async () => {
    const s2 = await reconnect();
    ws.emit("n", "click", 1);
    expect(s2.json().some((m) => m.msg.type === "event")).toBe(false);
    session(s2);
    expect(s2.json().some((m) => m.msg.type === "event")).toBe(true);
  });

  it("a change a field is still holding goes out before whatever is sent next", async () => {
    ws.connect();
    const s = last();
    s.open();
    session(s);
    const sent = () => s.json().map((m) => `${m.msg.type}:${m.msg.name ?? m.msg.path ?? ""}`).slice(1);
    // A field holds its change for a moment, and the person clicks at once.
    let held: string | null = "pasted text";
    const say = () => {
      if (held === null) return;
      const text = held;
      held = null;
      ws.emit("field", "change", text);
    };
    ws.holdBack(say);
    ws.emit("save", "click");
    expect(sent()).toEqual(["event:change", "event:click"]);
    // Said once: the next thing sent does not bring it out again.
    ws.emit("save", "click");
    expect(sent()).toEqual(["event:change", "event:click", "event:click"]);
    // The same before a move to another page, an answer and a request.
    for (const [next, kind] of [
      [() => ws.navigate("/other"), "navigate:/other"],
      [() => ws.answer("r1", true), "answer:"],
      [() => void ws.request("n", "search", "q").catch(() => {}), "request:search"],
    ] as const) {
      held = "more";
      ws.holdBack(say);
      const before = sent().length;
      next();
      expect(sent().slice(before)).toEqual(["event:change", kind]);
    }
    // A field that said it on its own time is not asked again.
    held = "typed";
    const release = ws.holdBack(say);
    say();
    release();
    const before = sent().length;
    ws.emit("save", "click");
    expect(sent().slice(before)).toEqual(["event:click"]);
  });

  it("request() during the hello/session window rejects", async () => {
    const s2 = await reconnect();
    const p = ws.request("n", "search", "q");
    await expect(p).rejects.toThrow("not connected");
    session(s2);
  });

  it("a bad frame header (len>32, invalid utf-8) is ignored without throwing", async () => {
    const s = last();
    const seen: number[] = [];
    const p = ws.request("", "file", { id: "x" }, { onChunk: (d) => seen.push(d.length) });
    p.catch(() => undefined);
    const rid: string = s.json().at(-1).msg.request;
    const good = new Uint8Array([rid.length, ...new TextEncoder().encode(rid), 1, 2, 3]);
    const long = new Uint8Array([40, ...new Uint8Array(45)]);
    const badUtf = new Uint8Array([2, 0xff, 0xfe, 9]);
    const short = new Uint8Array([16, 1, 2]);
    for (const f of [good, long, badUtf, short]) s.bin(f.buffer.slice(f.byteOffset, f.byteOffset + f.byteLength));
    expect(seen).toEqual([3]);
    p.cancel();
  });

  it("fileUrl: a rejected fetch leaves the cache so a retry works; a session change mid-fetch", async () => {
    const s = last();
    const p1 = ws.fileUrl("F1");
    const p1b = ws.fileUrl("F1");
    expect(p1b).toBe(p1);
    const rid: string = s.json().at(-1).msg.request;
    s.text(0, { type: "head", request: rid, payload: { mime: "text/plain" } });
    const f = new Uint8Array([rid.length, ...new TextEncoder().encode(rid), 104, 105]);
    s.bin(f.buffer);
    s.text(0, { type: "reply", request: rid, payload: { size: 2 }, error: null });
    expect(ws.fileType("F1")).toBeUndefined();
    const url = await p1;
    expect(url.startsWith("blob:")).toBe(true);
    expect(ws.fileType("F1")).toBe("text/plain");
    // same promise for the same id afterwards
    expect(ws.fileUrl("F1")).toBe(p1);
    // a fetch interrupted by a close is forgotten so the next call asks again
    const p2 = ws.fileUrl("F2");
    p2.catch(() => undefined);
    const s2 = await reconnect();
    await expect(p2).rejects.toThrow("disconnected");
    await tick();
    session(s2);
    const p3 = ws.fileUrl("F2");
    expect(p3).not.toBe(p2);
    p3.catch(() => undefined);
    // a NEW session forgets F1: a later call asks again
    const s3 = await reconnect();
    session(s3, "S2");
    const p4 = ws.fileUrl("F1");
    expect(p4).not.toBe(p1);
    expect(ws.fileType("F1")).toBeUndefined();
    p4.catch(() => undefined);
  });

  it("fileType: the type is the one that came with the bytes, without its parameters", async () => {
    const s = last();
    const p = ws.fileUrl("H1");
    const rid: string = s.json().at(-1).msg.request;
    s.text(0, { type: "head", request: rid, payload: { mime: "Text/HTML; charset=utf-8" } });
    s.text(0, { type: "reply", request: rid, payload: { size: 0 }, error: null });
    await p;
    expect(ws.fileType("H1")).toBe("text/html");
    expect(ws.runsNothing(ws.fileType("H1"))).toBe(false);
  });

  it("fileUrl: the address has the type only of what runs nothing", async () => {
    const s = last();
    const fetched = async (id: string, mime: string, body = "<svg/>") => {
      const p = ws.fileUrl(id);
      const rid: string = s.json().at(-1).msg.request;
      s.text(0, { type: "head", request: rid, payload: { mime } });
      const f = new Uint8Array([rid.length, ...new TextEncoder().encode(rid), ...new TextEncoder().encode(body)]);
      s.bin(f.buffer);
      s.text(0, { type: "reply", request: rid, payload: { size: body.length }, error: null });
      return p;
    };
    const typeAt = async (id: string, mime: string) => (await fetch(await fetched(id, mime))).headers.get("content-type");
    expect(await typeAt("T1", "text/plain; charset=utf-8")).toBe("text/plain; charset=utf-8");
    expect(await typeAt("T2", "application/pdf")).toBe("application/pdf");
    expect(await typeAt("T3", "text/html")).toBe("application/octet-stream");
    expect(await typeAt("T4", "application/xhtml+xml")).toBe("application/octet-stream");
    expect(await typeAt("T5", "text/csv")).toBe("application/octet-stream");
    // A type that reads as plain text and is not plain ASCII would leave the
    // blob without a type, for the browser to guess at.
    expect(await typeAt("T6", "text/plain\u00a0")).toBe("text/plain");
    expect(await typeAt("T7", "text/mar\u212adown")).toBe("text/markdown");
    // A drawing is no blob of this app: it is a data URL, with the bytes in it.
    const svg = await fetched("T8", "image/svg+xml", "<svg>\u00e9</svg>");
    expect(svg).toBe("data:image/svg+xml;base64,PHN2Zz7DqTwvc3ZnPg==");
    expect(ws.fileType("T8")).toBe("image/svg+xml");
  });

  it("emitHeard: a wait is over when the session says back the tag its event went with", async () => {
    const s = await reconnect();
    session(s, "HEARD");
    const over: string[] = [];
    void ws.emitHeard("root/list", "move", { key: "a", to: 2 }).then(() => over.push("first"));
    void ws.emitHeard("root/list", "move", { key: "b", to: 0 }).then(() => over.push("second"));
    void ws.emitHeard("root/other", "rename", "x").then(() => over.push("other"));
    await tick();
    const sent = s.json().filter((m) => m.msg.type === "event").slice(-3).map((m) => m.msg);
    expect(sent.map((m) => [m.node, m.name])).toEqual([
      ["root/list", "move"],
      ["root/list", "move"],
      ["root/other", "rename"],
    ]);
    const [first, second, other] = sent.map((m) => m.tag as string);
    expect(new Set([first, second, other]).size).toBe(3);
    expect(over).toEqual([]);
    // In whatever order the session is done with them, each wait ends at its own word.
    s.text(0, { type: "command", name: "heard", args: { node: "root/list", tag: second } });
    await tick();
    expect(over).toEqual(["second"]);
    s.text(0, { type: "command", name: "heard", args: { node: "root/other", tag: other } });
    s.text(0, { type: "command", name: "heard", args: { node: "root/list", tag: first } });
    await tick();
    expect(over).toEqual(["second", "other", "first"]);
    // A word said twice, or for a tag nobody waits for, is nobody's.
    s.text(0, { type: "command", name: "heard", args: { node: "root/list", tag: first } });
    s.text(0, { type: "command", name: "heard", args: { node: "root/list", tag: "none" } });
    // Another session has heard nothing of what the one before was sent.
    void ws.emitHeard("root/list", "move", { key: "c", to: 1 }).then(() => over.push("gone"));
    const next = await reconnect();
    session(next, "HEARD-2");
    await tick();
    expect(over).toEqual(["second", "other", "first", "gone"]);
  });

  it("runsNothing: only what a browser shows without running anything", () => {
    const shown = ["application/pdf", "text/plain", "TEXT/PLAIN; charset=utf-8", "text/markdown", "image/png", "image/jpeg", "audio/mpeg", "video/mp4"];
    for (const mime of shown) expect(ws.runsNothing(mime)).toBe(true);
    const saved = [
      "text/html", "text/xml", "application/xml", "application/xhtml+xml", "image/svg+xml", "text/csv",
      "text/javascript", "application/octet-stream", "application/pdf+xml", "xtext/plain", "video/x+xml", "audio/svg+xml", "", undefined,
    ];
    for (const mime of saved) expect(ws.runsNothing(mime)).toBe(false);
  });
});
