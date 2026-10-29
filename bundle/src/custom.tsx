// An app's custom component: JSX fetched as text, compiled once per source,
// rendered as a real component with `props`, `emit` and `children` as React
// props, so its own state survives a server push. The compiler (react-runner
// with sucrase) is a lazy chunk: pages without custom components never load it.

import { useCallback, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import type { Node } from "./store";
import { imports } from "./imports";
import { fileUrl, request } from "./ws";
import { ensureTailwindRuntime } from "./tailwind-runtime";

type Compiled = ComponentType<{
  props: Record<string, unknown>;
  emit: (name: string, payload?: unknown) => void;
  request: (name: string, payload?: unknown) => Promise<unknown>;
  fileUrl: (id: string) => Promise<string>;
  children?: ReactNode;
}>;

const sources = new Map<string, Promise<string>>();
const compiled = new Map<string, Compiled>();
let version = 0;

function load(name: string): Promise<string> {
  const key = `${version}:${name}`;
  let p = sources.get(key);
  if (!p) {
    p = fetch(`/_mw/components/${encodeURIComponent(name)}.jsx`, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`custom component ${name}: HTTP ${r.status}`);
      return r.text();
    });
    // A failed fetch is not remembered: the next mount tries again.
    p.catch(() => sources.delete(key));
    sources.set(key, p);
  }
  return p;
}

// Called for the dev loop's reload_component command, or for every component when no name is given.
export function invalidate(name?: string) {
  if (name === undefined) {
    version += 1;
    sources.clear();
    compiled.clear();
    return;
  }
  for (const key of [...sources.keys()]) if (key.endsWith(`:${name}`)) sources.delete(key);
  for (const key of [...compiled.keys()]) if (key.endsWith(`:${name}`)) compiled.delete(key);
  version += 1;
}

async function compile(name: string, code: string): Promise<Compiled> {
  const key = `${version}:${name}`;
  const hit = compiled.get(key);
  if (hit) return hit;
  const { importCode } = await import("react-runner");
  const mod = importCode(code, { import: imports }) as { default?: Compiled };
  if (typeof mod.default !== "function") throw new Error(`custom component ${name} has no default export`);
  compiled.set(key, mod.default);
  return mod.default;
}

export function CustomComponent({
  node,
  props,
  emit,
  children,
}: {
  node: Node;
  props: Record<string, unknown>;
  emit: (name: string, payload?: unknown) => void;
  children: ReactNode;
}) {
  const [Comp, setComp] = useState<Compiled | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const onReload = (e: Event) => {
      const which = (e as CustomEvent<{ name?: string }>).detail?.name;
      if (!which || which === node.type) setTick((t) => t + 1);
    };
    window.addEventListener("mw:reload-component", onReload);
    return () => window.removeEventListener("mw:reload-component", onReload);
  }, [node.type]);

  useEffect(() => {
    let alive = true;
    setError(null);
    void ensureTailwindRuntime();
    load(node.type)
      .then((src) => compile(node.type, src))
      .then((c) => alive && setComp(() => c))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [node.type, tick]);

  const stable = useMemo(() => ({ ...props }), [props]);
  // A custom component asks its own handlers (`on_<name>` on the Python side) and
  // fetches session files the same way the catalogue does.
  const ask = useCallback((name: string, payload?: unknown) => request(node.id, name, payload ?? null), [node.id]);

  if (error) return <div className="text-destructive text-sm">{error}</div>;
  if (!Comp) return null;
  return (
    <Comp props={stable} emit={emit} request={ask} fileUrl={fileUrl}>
      {children}
    </Comp>
  );
}
