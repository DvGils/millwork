// The node store: the page as a flat table of nodes, patched in place.
//
// React components subscribe per node id, so a patch that touches one node
// re-renders that node and nothing else. The store never holds React state;
// it is a plain object with a snapshot per node version. A reset epoch per
// node remounts its subtree, which is how client-owned state goes back to
// its default.

import { useSyncExternalStore } from "react";

export type NodeId = string;

export interface Node {
  id: NodeId;
  type: string;
  props: Record<string, unknown>;
  children: NodeId[];
}

export type PatchOp =
  | { op: "set"; id: NodeId; props: Record<string, unknown> }
  | { op: "unset"; id: NodeId; keys: string[] }
  | { op: "splice"; id: NodeId; prop: string; edits: [number, number, unknown[]][] }
  | { op: "children"; id: NodeId; children: NodeId[] }
  | { op: "add"; node: Node }
  | { op: "remove"; id: NodeId };

type Listener = () => void;

// A list rebuilt from its edits in one pass. Each edit is [start, delete, items]
// in positions of the old list, ascending. What the edits leave alone stays the
// same objects, so a row that did not change is not drawn again.
export function splice(list: unknown, edits: [number, number, unknown[]][]): unknown[] {
  const old = Array.isArray(list) ? list : [];
  const out: unknown[] = [];
  let at = 0;
  for (const [start, del, items] of edits) {
    for (let i = at; i < start && i < old.length; i++) out.push(old[i]);
    for (const item of items) out.push(item);
    at = start + del;
  }
  for (let i = at; i < old.length; i++) out.push(old[i]);
  return out;
}

class Store {
  root: NodeId | null = null;
  title: string | null = null;
  private nodes = new Map<NodeId, Node>();
  private listeners = new Map<NodeId, Set<Listener>>();
  private rootListeners = new Set<Listener>();
  private snapshots = new Map<NodeId, Node>();
  private epochs = new Map<NodeId, number>();

  // Held, the page is kept off the screen while something it needs to paint
  // right is on its way; the store itself goes on taking mounts and patches.
  held = false;

  hold(until: Promise<unknown>) {
    this.held = true;
    for (const l of this.rootListeners) l();
    const release = () => {
      this.held = false;
      for (const l of this.rootListeners) l();
    };
    until.then(release, release);
  }

  shown(): NodeId | null {
    return this.held ? null : this.root;
  }

  mount(root: NodeId, nodes: Record<NodeId, Node>, title: string | null) {
    const previous = [...this.nodes.keys()];
    this.nodes = new Map(Object.entries(nodes));
    this.snapshots.clear();
    this.epochs.clear();
    this.root = root;
    this.title = title;
    if (title && typeof document !== "undefined") document.title = title;
    for (const id of new Set([...previous, ...this.nodes.keys()])) this.notify(id);
    for (const l of this.rootListeners) l();
  }

  patch(ops: PatchOp[]) {
    const touched = new Set<NodeId>();
    for (const op of ops) {
      switch (op.op) {
        case "add":
          this.nodes.set(op.node.id, op.node);
          touched.add(op.node.id);
          break;
        case "remove":
          this.nodes.delete(op.id);
          this.snapshots.delete(op.id);
          this.epochs.delete(op.id);
          touched.add(op.id);
          break;
        case "set": {
          const n = this.nodes.get(op.id);
          if (n) {
            n.props = { ...n.props, ...op.props };
            touched.add(op.id);
          }
          break;
        }
        case "splice": {
          const n = this.nodes.get(op.id);
          if (n) {
            n.props = { ...n.props, [op.prop]: splice(n.props[op.prop], op.edits) };
            touched.add(op.id);
          }
          break;
        }
        case "unset": {
          const n = this.nodes.get(op.id);
          if (n) {
            const props = { ...n.props };
            for (const k of op.keys) delete props[k];
            n.props = props;
            touched.add(op.id);
          }
          break;
        }
        case "children": {
          const n = this.nodes.get(op.id);
          if (n) {
            n.children = op.children;
            touched.add(op.id);
          }
          break;
        }
      }
    }
    for (const id of touched) {
      this.snapshots.delete(id);
      this.notify(id);
    }
  }

  // Remount the subtrees of every node whose key is `key`: client state goes back to default.
  reset(key: string): number {
    let count = 0;
    for (const id of this.nodes.keys()) {
      if (id.endsWith(`/${key}`)) {
        this.epochs.set(id, (this.epochs.get(id) ?? 0) + 1);
        this.notify(id);
        count += 1;
      }
    }
    return count;
  }

  epoch(id: NodeId): number {
    return this.epochs.get(id) ?? 0;
  }

  get(id: NodeId): Node | undefined {
    return this.nodes.get(id);
  }

  // A stable object per node version, so useSyncExternalStore sees a change
  // exactly when the node changed.
  snapshot(id: NodeId): Node | undefined {
    const n = this.nodes.get(id);
    if (!n) return undefined;
    let s = this.snapshots.get(id);
    if (!s) {
      s = { ...n, props: { ...n.props }, children: [...n.children] };
      this.snapshots.set(id, s);
    }
    return s;
  }

  subscribe(id: NodeId, l: Listener): () => void {
    let set = this.listeners.get(id);
    if (!set) {
      set = new Set();
      this.listeners.set(id, set);
    }
    set.add(l);
    return () => {
      set!.delete(l);
      if (set!.size === 0) this.listeners.delete(id);
    };
  }

  subscribeRoot(l: Listener): () => void {
    this.rootListeners.add(l);
    return () => {
      this.rootListeners.delete(l);
    };
  }

  private notify(id: NodeId) {
    const set = this.listeners.get(id);
    if (set) for (const l of set) l();
  }
}

export const store = new Store();

export function useNode(id: NodeId): Node | undefined {
  return useSyncExternalStore(
    (l) => store.subscribe(id, l),
    () => store.snapshot(id),
    () => store.snapshot(id),
  );
}

export function useResetEpoch(id: NodeId): number {
  return useSyncExternalStore(
    (l) => store.subscribe(id, l),
    () => store.epoch(id),
    () => store.epoch(id),
  );
}

export function useRoot(): NodeId | null {
  return useSyncExternalStore(
    (l) => store.subscribeRoot(l),
    () => store.shown(),
    () => store.shown(),
  );
}
