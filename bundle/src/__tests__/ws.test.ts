// The socket module against a fake WebSocket: sequencing, the request layer,
// uploads across a reconnect, frames, and the file cache.

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../theme", () => ({ applyTheme: vi.fn(), t: (k: string) => k }));
vi.mock("../store", () => ({ store: { mount: vi.fn(), patch: vi.fn(), reset: vi.fn() } }));
vi.mock("../custom", () => ({ invalidate: vi.fn() }));
vi.mock("../tailwind-runtime", () => ({ ensureTailwindRuntime: vi.fn(() => Promise.resolve()), needsRuntime: () => false, runtimeLoaded: () => true }));
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
    const url = await p1;
    expect(url.startsWith("blob:")).toBe(true);
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
    p4.catch(() => undefined);
  });
});
