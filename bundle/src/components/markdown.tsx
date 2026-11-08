// Markdown rendered as React elements (never as an HTML string). The renderer
// is a lazy chunk: only pages with Markdown or a Chat load it.

import { useEffect, useReducer, type ComponentType } from "react";
import type { Node } from "../store";
import { cn } from "cn";
import { isInternalPath, linkLook, safeUrl, slugify } from "../lib";
import { CodeBlock } from "./copy";
import { anchorProps } from "./anchor";

type Props = { content: string; tight?: boolean };

// The text of a heading's children, for its anchor id.
function textOf(node: unknown): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) return textOf((node as { props: { children?: unknown } }).props.children);
  return "";
}

// A link's href is left as written, so that `linkProps` maps it once, to the
// browser path under the app's prefix. Every other URL is checked here.
export function transformUrl(url: string, tagName: string): string {
  return tagName === "a" ? url : safeUrl(url, { image: true });
}

// A link to a page of the app opens it on the session, as `ui.Link` does,
// and a link to a heading stays on the page. A link to anywhere else opens
// a new tab.
export function linkProps(href: unknown) {
  const stays = isInternalPath(href) || (typeof href === "string" && href.startsWith("#"));
  return anchorProps(href, stays ? undefined : "_blank");
}

// Two rhythms: `tight` for a chat turn or a caption, where a heading sits
// close to its text; the default for a page, where a section breathes.
// The renderer's chunk, fetched once. A page that mounts with Markdown on it
// waits for it, so the text is drawn once, in place, and not first as its
// source. The renderer is kept here rather than behind React's lazy boundary,
// which would commit its fallback once even for a chunk already in.
type Mods = [typeof import("react-markdown"), typeof import("remark-gfm")];
let chunk: Promise<void> | null = null;
let Renderer: ComponentType<Props> | null = null;
const waiting = new Set<() => void>();

export function preloadMarkdown(): Promise<void> {
  chunk ??= Promise.all([import("react-markdown"), import("remark-gfm")]).then((mods: Mods) => {
    Renderer = makeRenderer(mods[0].default, mods[1].default);
    for (const wake of waiting) wake();
  });
  return chunk;
}
export function markdownLoaded(): boolean {
  return Renderer !== null;
}
export function needsMarkdown(nodes: Record<string, Node>): boolean {
  return Object.values(nodes).some((n) => n.type === "Markdown");
}

function makeRenderer(ReactMarkdown: Mods[0]["default"], gfm: Mods[1]["default"]): ComponentType<Props> {
  const Rendered: ComponentType<Props> = ({ content, tight }) => (
    <div className={tight ? "mw-markdown mw-tight" : "mw-markdown"}>
      <ReactMarkdown
        remarkPlugins={[gfm]}
        urlTransform={(url, _key, node) => transformUrl(url, node.tagName)}
        components={{
          a: ({ href, children }) => (
            <a {...linkProps(href)} className={cn("text-primary", linkLook)}>
              {children}
            </a>
          ),
          code: ({ className, children }) =>
            className ? (
              <code className={className}>{children}</code>
            ) : (
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
            ),
          pre: ({ children }) => (
            <div className={tight ? "my-2" : "my-3"}>
              <CodeBlock>{children}</CodeBlock>
            </div>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-auto">
              <table className="w-full text-sm [&_td]:border-t [&_td]:px-2 [&_td]:py-1 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left">{children}</table>
            </div>
          ),
          ul: ({ children }) => <ul className={cn("list-disc pl-5", tight ? "my-2" : "my-3")}>{children}</ul>,
          ol: ({ children }) => <ol className={cn("list-decimal pl-5", tight ? "my-2" : "my-3")}>{children}</ol>,
          h1: ({ children }) => <h1 id={slugify(textOf(children))} className={cn("scroll-mt-20 text-lg font-semibold first:mt-0", tight ? "mt-3 mb-1" : "mt-8 mb-3")}>{children}</h1>,
          h2: ({ children }) => <h2 id={slugify(textOf(children))} className={cn("scroll-mt-20 text-base font-semibold first:mt-0", tight ? "mt-3 mb-1" : "mt-10 mb-3")}>{children}</h2>,
          h3: ({ children }) => <h3 id={slugify(textOf(children))} className={cn("scroll-mt-20 font-medium first:mt-0", tight ? "mt-2 mb-1" : "mt-6 mb-2")}>{children}</h3>,
          p: ({ children }) => <p className={cn("leading-relaxed first:mt-0 last:mb-0", tight ? "my-1.5" : "my-3")}>{children}</p>,
          blockquote: ({ children }) => <blockquote className={cn("border-l-2 pl-3 text-muted-foreground", tight ? "my-2" : "my-3")}>{children}</blockquote>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
  return Rendered;
}

// Markdown that arrives before the chunk, through a patch or a chat turn,
// shows as its text until the chunk is in, then renders in place.
export function Markdown({ content, tight }: Props) {
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (Renderer) return;
    waiting.add(rerender);
    void preloadMarkdown();
    return () => {
      waiting.delete(rerender);
    };
  }, []);
  if (Renderer) return <Renderer content={content} tight={tight} />;
  return <div className="whitespace-pre-wrap text-sm">{content}</div>;
}
