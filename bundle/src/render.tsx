// Rendering a node: look its type up in the registry and render it as a real
// React component, so its hooks are its own. A node with `hidden` is rendered
// but not shown, keeping its client state. Unknown types resolve to the app's
// custom components. An error inside one node shows that node's id, never a
// blank page.

import { Component as ReactComponent, memo, useEffect, type ReactNode } from "react";
import { useNode, useResetEpoch, type Node } from "./store";
import { emit as wsEmit } from "./ws";
import { registry } from "./components";
import { CustomComponent } from "./custom";
import { ensureTailwindRuntime } from "./tailwind-runtime";

export interface RenderProps {
  node: Node;
  props: Record<string, unknown>;
  children: ReactNode;
  emit: (name: string, payload?: unknown) => void;
}

export type Renderer = (p: RenderProps) => ReactNode;

export const Render = memo(function Render({ id }: { id: string }) {
  const node = useNode(id);
  const epoch = useResetEpoch(id);
  if (!node) return null;
  // The wrapper is always there, so flipping `hidden` never remounts the subtree:
  // `display: contents` keeps it out of the layout while shown.
  const hidden = Boolean(node.props.hidden);
  return (
    <div style={{ display: hidden ? "none" : "contents" }}>
      <Boundary key={`${node.type}:${epoch}`} id={id}>
        <NodeComponent node={node} />
      </Boundary>
    </div>
  );
});

function NodeComponent({ node }: { node: Node }) {
  const Renderer = registry[node.type];
  const emit = (name: string, payload: unknown = null) => wsEmit(node.id, name, payload);
  const children = node.children.map((cid) => <Render key={cid} id={cid} />);
  const cls = node.props.cls;
  useEffect(() => {
    if (typeof cls === "string" && cls) void ensureTailwindRuntime();
  }, [cls]);
  if (!Renderer) {
    return (
      <CustomComponent node={node} props={node.props} emit={emit}>
        {children}
      </CustomComponent>
    );
  }
  return <Renderer node={node} props={node.props} emit={emit}>{children}</Renderer>;
}

class Boundary extends ReactComponent<{ id: string; children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };

  static getDerivedStateFromError(error: Error) {
    return { error: error.message };
  }

  componentDidUpdate(prev: { id: string; children: ReactNode }) {
    if (prev.children !== this.props.children && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-md border border-destructive/50 bg-destructive/5 p-2 text-xs text-destructive">
          {this.props.id}: {this.state.error}
        </div>
      );
    }
    return this.props.children;
  }
}

// A slot prop ({"$node": id}) rendered in place.
export function Slot({ value }: { value: unknown }) {
  if (value && typeof value === "object" && "$node" in (value as object)) {
    return <Render id={(value as { $node: string }).$node} />;
  }
  return null;
}

export function isSlot(value: unknown): boolean {
  return !!value && typeof value === "object" && "$node" in (value as object);
}
