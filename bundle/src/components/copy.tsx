// A copy button for code: the text comes from a function so a block rendered
// from Markdown can read its own DOM, and the icon confirms for a moment.

import { useEffect, useRef, useState } from "react";
import { cn } from "cn";
import { icon } from "../icons";
import { Button } from "@/components/ui/button";

// The async clipboard needs a secure context and a focused document; a plain
// http host on the LAN, or a refusal, still gets the old selection route.
async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // fall through to the selection route
    }
  }
  const had = document.activeElement;
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
  if (had instanceof HTMLElement) had.focus();
}

export function CopyButton({ text, className }: { text: () => string; className?: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  const Icon = icon(done ? "check" : "copy");
  return (
    <Button
      type="button"
      size="icon-xs"
      variant="ghost"
      aria-label="Copy"
      title="Copy"
      className={cn("text-muted-foreground hover:text-foreground", done && "text-success", className)}
      onClick={() => {
        void copyText(text()).then(() => {
          setDone(true);
          if (timer.current) window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setDone(false), 1500);
        });
      }}
    >
      {Icon ? <Icon /> : null}
    </Button>
  );
}

// A <pre> with the copy button in its corner. The button sits outside the
// scrolling box so a long line never pushes it away.
export function CodeBlock({ children, className, copyable = true, style }: { children: React.ReactNode; className?: string; copyable?: boolean; style?: React.CSSProperties }) {
  const ref = useRef<HTMLPreElement>(null);
  return (
    <div className="relative min-w-0 max-w-full">
      <pre ref={ref} className={cn("overflow-auto rounded-lg bg-muted p-3 font-mono text-xs", copyable && "pr-10", className)} style={style}>
        {children}
      </pre>
      {copyable ? <CopyButton text={() => ref.current?.textContent ?? ""} className="absolute top-1.5 right-1.5" /> : null}
    </div>
  );
}
