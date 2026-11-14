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

// What goes with every page and keeps what the browser holds of it from
// one page to the next: how a sidebar is folded, an assistant's window.
const STAYS = new Set(["Sidebar", "Assistant"]);

class Store {
  root: NodeId | null = null;
  title: string | null = null;
  // How many whole pages have been put here. A component that lives on
  // from one page to the next, under the same id, can tell by it that the
  // page around it is a new one.
  mounts = 0;
  private nodes = new Map<NodeId, Node>();
  private listeners = new Map<NodeId, Set<Listener>>();
  private rootListeners = new Set<Listener>();
  private snapshots = new Map<NodeId, Node>();
  private epochs = new Map<NodeId, number>();
  // The page each part of the page body was first put here with. A part
  // that is there again on another page, under the same id, is another
  // part, and starts over: what was typed into a form on one page is not
  // on the next. The parts that go with every page are left as they are,
  // wherever in the page they stand.
  private pages = new Map<NodeId, number>();
  private page = 0;

  // `another` says the person went to another page, where a tab that was
  // given the page it already had says nothing.
  mount(root: NodeId, nodes: Record<NodeId, Node>, title: string | null, another = false) {
    const previous = [...this.nodes.keys()];
    this.nodes = new Map(Object.entries(nodes));
    if (another) {
      this.page += 1;
      this.pages.clear();
      this.startOver(root, true);
    } else {
      for (const id of [...this.pages.keys()]) if (!this.nodes.has(id)) this.pages.delete(id);
    }
    this.snapshots.clear();
    this.epochs.clear();
    this.root = root;
    this.title = title;
    this.mounts += 1;
    if (title && typeof document !== "undefined") document.title = title;
    for (const id of new Set([...previous, ...this.nodes.keys()])) this.notify(id);
    for (const l of this.rootListeners) l();
  }

  // Give the parts of a page that start over the number of the page. A
  // `Page` is the frame around them and is kept, and so is whatever holds
  // a part that stays, which is looked into for the parts beside it. A
  // page whose root is something else, a form or a chat, starts over whole.
  private startOver(id: NodeId, top: boolean) {
    const node = this.nodes.get(id);
    if (!node || STAYS.has(node.type)) return;
    if ((top && node.type === "Page") || this.holdsWhatStays(node)) {
      for (const child of node.children) this.startOver(child, false);
      return;
    }
    this.pages.set(id, this.page);
  }

  private holdsWhatStays(node: Node): boolean {
    return node.children.some((id) => {
      const child = this.nodes.get(id);
      return child !== undefined && (STAYS.has(child.type) || this.holdsWhatStays(child));
    });
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

  // Remount the subtrees of these nodes: client state goes back to default.
  // The server names them, by the one rule it has for what a key stands for.
  reset(ids: string[]): number {
    let count = 0;
    for (const id of ids) {
      if (this.nodes.has(id)) {
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

  // The page a part of the page body came with, or 0 for anything else.
  pageOf(id: NodeId): number {
    return this.pages.get(id) ?? 0;
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

export function usePageOf(id: NodeId): number {
  return useSyncExternalStore(
    (l) => store.subscribe(id, l),
    () => store.pageOf(id),
    () => store.pageOf(id),
  );
}

export function useMounts(): number {
  return useSyncExternalStore(
    (l) => store.subscribeRoot(l),
    () => store.mounts,
    () => store.mounts,
  );
}

export function useRoot(): NodeId | null {
  return useSyncExternalStore(
    (l) => store.subscribeRoot(l),
    () => store.root,
    () => store.root,
  );
}
