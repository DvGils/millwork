// The Tailwind browser runtime, loaded once, the first time a page needs a class
// the precompiled stylesheet does not have: a custom component, or `cls` on a
// catalogue component. Pages without either never pay for it (design decision 5).
//
// The style block repeats the theme mapping from src/index.css so utilities the
// runtime generates use the same tokens as the precompiled ones.

import themeBlock from "./theme-block.css?raw";

let loading: Promise<void> | null = null;

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
  })();
  return loading;
}
