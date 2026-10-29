// Markdown rendered as React elements (never as an HTML string). The renderer
// is a lazy chunk: only pages with Markdown or a Chat load it.

import { lazy, Suspense, type ComponentType } from "react";
import { cn } from "cn";
import { safeUrl, slugify } from "../lib";
import { CodeBlock } from "./copy";

type Props = { content: string; tight?: boolean };

// The text of a heading's children, for its anchor id.
function textOf(node: unknown): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) return textOf((node as { props: { children?: unknown } }).props.children);
  return "";
}

// Two rhythms: `tight` for a chat turn or a caption, where a heading sits
// close to its text; the default for a page, where a section breathes.
const Inner = lazy(async () => {
  const [{ default: ReactMarkdown }, { default: gfm }] = await Promise.all([import("react-markdown"), import("remark-gfm")]);
  const Renderer: ComponentType<Props> = ({ content, tight }) => (
    <div className={tight ? "mw-markdown mw-tight" : "mw-markdown"}>
      <ReactMarkdown
        remarkPlugins={[gfm]}
        urlTransform={(url) => safeUrl(url, { image: true })}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-primary underline-offset-4 hover:underline">
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
  return { default: Renderer };
});

export function Markdown({ content, tight }: Props) {
  return (
    <Suspense fallback={<div className="whitespace-pre-wrap text-sm">{content}</div>}>
      <Inner content={content} tight={tight} />
    </Suspense>
  );
}
