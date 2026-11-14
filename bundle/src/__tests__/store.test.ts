import { describe, expect, it } from "vitest";
import { splice, store, type Node, type PatchOp } from "../store";

const node = (id: string, type = "Box", props = {}, children: string[] = []): Node => ({ id, type, props, children });

describe("store", () => {
  it("mounts and patches like the Python side", () => {
    const seen: string[] = [];
    store.subscribeRoot(() => seen.push("root"));
    store.mount("root", { root: node("root", "Page", {}, ["root/0:Text"]), "root/0:Text": node("root/0:Text", "Text", { content: "a" }) }, "T");
    expect(store.root).toBe("root");
    const unsub = store.subscribe("root/0:Text", () => seen.push("text"));
    const ops: PatchOp[] = [
      { op: "add", node: node("root/k", "Box", { label: "k" }) },
      { op: "set", id: "root/0:Text", props: { content: "b" } },
      { op: "unset", id: "root/0:Text", keys: ["content"] },
      { op: "children", id: "root", children: ["root/0:Text", "root/k"] },
    ];
    store.patch(ops);
    expect(store.get("root")!.children).toEqual(["root/0:Text", "root/k"]);
    expect(store.get("root/0:Text")!.props).toEqual({});
    expect(store.get("root/k")!.props.label).toBe("k");
    expect(seen.filter((s) => s === "text").length).toBe(1);
    const snap1 = store.snapshot("root/k");
    store.patch([{ op: "set", id: "root/0:Text", props: { content: "c" } }]);
    expect(store.snapshot("root/k")).toBe(snap1); // untouched nodes keep their snapshot identity
    store.patch([{ op: "remove", id: "root/k" }]);
    expect(store.get("root/k")).toBeUndefined();
    unsub();
  });
});

describe("store patch order", () => {
  it("notifies only after the whole patch is applied", () => {
    // The Python diff may order a same-id remove before its add, or a set before an add it
    // refers to; listeners must see the finished table, never a step in between.
    store.mount("root", { root: node("root", "Page", {}, ["root/a"]), "root/a": node("root/a", "Text", { content: "a" }) }, null);
    const seen: unknown[] = [];
    const unsub = store.subscribe("root/a", () => seen.push(store.get("root/b")?.props.label));
    store.patch([
      { op: "set", id: "root/a", props: { content: "b" } },
      { op: "add", node: node("root/b", "Box", { label: "late" }) },
    ]);
    expect(seen).toEqual(["late"]);
    unsub();
  });
});

describe("store reset", () => {
  it("bumps the epoch of every node it is given and notifies it", () => {
    store.mount("root", { root: node("root", "Page", {}, ["root/f"]), "root/f": node("root/f", "Form") }, null);
    const seen: number[] = [];
    store.subscribe("root/f", () => seen.push(store.epoch("root/f")));
    expect(store.reset(["root/f"])).toBe(1);
    expect(store.reset(["root/nope"])).toBe(0);
    expect(seen).toEqual([1]);
    expect(store.epoch("root")).toBe(0);
  });
});

describe("store splice", () => {
  it("rebuilds a list from its edits and keeps what they leave alone", () => {
    const rows = [0, 1, 2, 3, 4, 5].map((i) => ({ id: i }));
    const fresh = { id: 9 };
    // Positions are the old list's: one row replaced, two removed, one added at the end.
    const next = splice(rows, [
      [1, 1, [fresh]],
      [3, 2, []],
      [6, 0, [{ id: 6 }]],
    ]) as { id: number }[];
    expect(next.map((r) => r.id)).toEqual([0, 9, 2, 5, 6]);
    expect(next[0]).toBe(rows[0]);
    expect(next[2]).toBe(rows[2]);
    expect(next[1]).toBe(fresh);
    expect(splice(rows, [[0, 0, [fresh]]])).toEqual([fresh, ...rows]);
    expect(splice(undefined, [[0, 0, [fresh]]])).toEqual([fresh]);
  });

  it("patches one prop of a node and leaves its other props as they were", () => {
    const keys = [1, 2, 3];
    store.mount("root", { root: node("root", "Table", { rows: [{ id: 1 }, { id: 2 }, { id: 3 }], keys }) }, null);
    const before = store.snapshot("root")!;
    const kept = (before.props.rows as unknown[])[2];
    let told = 0;
    const unsub = store.subscribe("root", () => (told += 1));
    store.patch([{ op: "splice", id: "root", prop: "rows", edits: [[0, 1, [{ id: 1, n: 5 }]]] }]);
    const after = store.snapshot("root")!;
    expect(told).toBe(1);
    expect(after).not.toBe(before);
    expect(after.props.rows).toEqual([{ id: 1, n: 5 }, { id: 2 }, { id: 3 }]);
    expect((after.props.rows as unknown[])[2]).toBe(kept);
    expect(after.props.keys).toBe(keys);
    unsub();
  });
});

describe("store mounts", () => {
  it("counts whole pages, and a patch is not one", () => {
    const told: number[] = [];
    const unsub = store.subscribeRoot(() => told.push(store.mounts));
    const before = store.mounts;
    store.mount("root", { root: node("root", "Page") }, null);
    store.patch([{ op: "set", id: "root", props: { title: "t" } }]);
    store.mount("root", { root: node("root", "Page") }, null);
    expect(store.mounts).toBe(before + 2);
    // Whoever listens for a new page hears of it with the count already up.
    expect(told).toEqual([before + 1, before + 2]);
    unsub();
  });
});
