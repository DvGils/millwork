// An app's custom component: JSX fetched as text, compiled once per source,
// rendered as a real component with `props`, `emit` and `children` as React
// props, so its own state survives a server push. The compiler (react-runner
// with sucrase) is a lazy chunk: pages without custom components never load it.

import { mw } from "./lib";
import { useCallback, useContext, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import type { Node } from "./store";
import { imports } from "./imports";
import { fileUrl, request } from "./ws";
import { ensureTailwindRuntime } from "./tailwind-runtime";
import { ChatContext, type ChatApi } from "./chat-context";

type Compiled = ComponentType<{
  props: Record<string, unknown>;
  emit: (name: string, payload?: unknown) => void;
  request: (name: string, payload?: unknown) => Promise<unknown>;
  fileUrl: (id: string) => Promise<string>;
  chat?: ChatApi;
  children?: ReactNode;
}>;

const sources = new Map<string, Promise<string>>();
const compiled = new Map<string, Compiled>();
let version = 0;

// The content version of each component, from the boot and then from every
// session message: in the source URL, so the browser keeps a version for good
// and a changed component is fetched under a new URL without a reload.
function versions(): Record<string, string> {
  const w = window as unknown as { __mw?: { components?: Record<string, string> } };
  w.__mw ??= {};
  w.__mw.components ??= {};
  return w.__mw.components;
}

// Called with the versions a new session reports; a component whose version
// moved (a deploy while the tab was open) is loaded afresh on its next mount.
export function syncVersions(next: Record<string, string>) {
  const current = versions();
  const changed = Object.keys(next).filter((name) => current[name] !== undefined && current[name] !== next[name]);
  Object.assign(current, next);
  for (const name of changed) {
    invalidate(name);
    window.dispatchEvent(new CustomEvent("mw:reload-component", { detail: { name } }));
  }
}

function load(name: string): Promise<string> {
  const key = `${version}:${name}`;
  let p = sources.get(key);
  if (!p) {
    const v = versions()[name];
    const url = `${mw("/components/")}${encodeURIComponent(name)}.jsx${v ? `?v=${encodeURIComponent(v)}` : ""}`;
    p = fetch(url, { cache: v ? "default" : "no-cache" }).then((r) => {
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
export function invalidate(name?: string, newVersion?: string) {
  if (name !== undefined && newVersion) versions()[name] = newVersion;
  if (name === undefined) {
    version += 1;
    sources.clear();
    compiled.clear();
    return;
  }
  // Only this component's entries go; the others keep their keys and their mounts.
  for (const key of [...sources.keys()]) if (key.endsWith(`:${name}`)) sources.delete(key);
  for (const key of [...compiled.keys()]) if (key.endsWith(`:${name}`)) compiled.delete(key);
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
  // Inside a chat's composer the component may upload and send; elsewhere there is no chat.
  const chat = useContext(ChatContext);

  if (error) return <div className="text-destructive text-sm">{error}</div>;
  if (!Comp) return null;
  return (
    <Comp props={stable} emit={emit} request={ask} fileUrl={fileUrl} chat={chat ?? undefined}>
      {children}
    </Comp>
  );
}
