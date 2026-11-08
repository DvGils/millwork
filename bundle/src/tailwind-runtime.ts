// The Tailwind browser runtime, loaded once, the first time a page needs a class
// the precompiled stylesheet does not have: a custom component, or `cls` on a
// catalogue component. Pages without either never pay for it (design decision 5).
//
// The style block repeats the theme mapping from src/index.css so utilities the
// runtime generates use the same tokens as the precompiled ones.

import themeBlock from "./theme-block.css?raw";
import type { Node } from "./store";

let loading: Promise<void> | null = null;
let loaded = false;

export function runtimeLoaded(): boolean {
  return loaded;
}

// Whether a page has anything the runtime styles: a class of its own on a
// catalogue component, or a custom component.
export function needsRuntime(nodes: Record<string, Node>): boolean {
  for (const node of Object.values(nodes)) {
    if (node.type === "Custom") return true;
    const cls = node.props.cls;
    if (typeof cls === "string" && cls !== "") return true;
  }
  return false;
}

export function ensureTailwindRuntime(): Promise<void> {
  if (loading) return loading;
  loading = (async () => {
    const style = document.createElement("style");
    style.setAttribute("type", "text/tailwindcss");
    style.textContent = [
      "@layer theme, base, components, utilities;",
      '@import "tailwindcss/theme.css" layer(theme);',
      '@import "tailwindcss/utilities.css" layer(utilities);',
      themeBlock,
    ].join("\n");
    document.head.appendChild(style);
    await import("@tailwindcss/browser");
    loaded = true;
  })();
  return loading;
}
