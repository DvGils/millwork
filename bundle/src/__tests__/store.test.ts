import { describe, expect, it } from "vitest";
import { store, type Node, type PatchOp } from "../store";

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
  it("bumps the epoch of every node with that key and notifies it", () => {
    store.mount("root", { root: node("root", "Page", {}, ["root/f"]), "root/f": node("root/f", "Form") }, null);
    const seen: number[] = [];
    store.subscribe("root/f", () => seen.push(store.epoch("root/f")));
    expect(store.reset("f")).toBe(1);
    expect(store.reset("nope")).toBe(0);
    expect(seen).toEqual([1]);
    expect(store.epoch("root")).toBe(0);
  });
});
