// Layout and text: plain elements with the theme's tokens. No library behind them.

import type { Renderer } from "../render";
import { cn } from "cn";
import { Slot } from "../render";
import { isCompact } from "../theme";
import { store } from "../store";
import { PageWithSidebar } from "./more";
import { PageBody, pageBodyClass } from "./page-body";
import { Markdown as MarkdownView } from "./markdown";
import { CodeBlock } from "./copy";

// Compact density takes one step off every gap, never below one.
const gapClass = (gap: unknown) => {
  const g = typeof gap === "number" ? gap : 4;
  return `gap-${isCompact() ? Math.max(1, g - 1) : g}`;
};

const alignClass: Record<string, string> = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
  baseline: "items-baseline",
};

const justifyClass: Record<string, string> = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
};

export const Page: Renderer = ({ node, props, children }) => {
  const className = props.cls as string;
  const style = props.max_width ? { maxWidth: String(props.max_width) } : undefined;
  const sidebarId = node.children.find((cid) => store.get(cid)?.type === "Sidebar");
  if (sidebarId) {
    return <PageWithSidebar sidebarId={sidebarId} rest={node.children.filter((c) => c !== sidebarId)} className={className} style={style} padding={props.padding} gap={gapClass(props.gap ?? 6)} header={props.header} />;
  }
  return (
    <div className="flex h-dvh flex-col">
      <Slot value={props.header} />
      <main className={pageBodyClass(props.padding)}>
        <PageBody className={cn(gapClass(props.gap ?? 6), className)} style={style}>
          {children}
        </PageBody>
      </main>
    </div>
  );
};

export const Stack: Renderer = ({ props, children }) => (
  <div
    className={cn(
      "flex flex-col",
      gapClass(props.gap),
      alignClass[String(props.align ?? "stretch")],
      justifyClass[String(props.justify ?? "start")],
      props.grow && "grow",
      props.divided && "divide-y divide-border",
      props.cls as string,
    )}
  >
    {children}
  </div>
);

export const Row: Renderer = ({ props, children }) => (
  <div
    className={cn(
      "flex flex-row",
      gapClass(props.gap),
      alignClass[String(props.align ?? "center")],
      justifyClass[String(props.justify ?? "start")],
      props.wrap && "flex-wrap",
      props.cls as string,
    )}
  >
    {children}
  </div>
);

const textVariant: Record<string, string> = {
  body: "text-sm",
  muted: "text-sm text-muted-foreground",
  caption: "text-xs text-muted-foreground",
  label: "text-sm font-medium",
  title: "text-2xl font-semibold tracking-tight",
  heading: "text-lg font-semibold",
  subheading: "text-base font-medium",
  mono: "font-mono text-sm",
};

const toneText: Record<string, string> = {
  muted: "text-muted-foreground",
  primary: "text-primary",
  destructive: "text-destructive",
  success: "text-success",
  warning: "text-warning",
};

export const Text: Renderer = ({ props }) => {
  const variant = String(props.variant ?? "body");
  const Tag = variant === "title" ? "h1" : variant === "heading" ? "h2" : variant === "subheading" ? "h3" : "p";
  return (
    <Tag
      className={cn(
        textVariant[variant] ?? textVariant.body,
        props.tone ? toneText[String(props.tone)] : undefined,
        props.truncate && "truncate",
        props.align === "center" && "text-center",
        props.align === "right" && "text-right",
        props.cls as string,
      )}
    >
      {String(props.content ?? "")}
    </Tag>
  );
};

export const Markdown: Renderer = ({ props }) => (
  <div className={cn("text-sm", props.cls as string)}>
    <MarkdownView content={String(props.content ?? "")} tight={Boolean(props.tight)} />
  </div>
);

// Code: pre-formatted, with a copy button unless `copyable` is off.
// `min-w-0`: inside a flex column the block would otherwise refuse to shrink
// below its longest line and push the whole column wider than the page.
export const Code: Renderer = ({ props }) => (
  <div className={cn("flex min-w-0 max-w-full flex-col gap-1", props.cls as string)}>
    {props.title ? <div className="text-xs text-muted-foreground">{String(props.title)}</div> : null}
    <CodeBlock
      copyable={props.copyable !== false}
      className={cn(props.wrap && "whitespace-pre-wrap")}
      style={props.max_height ? { maxHeight: String(props.max_height) } : undefined}
    >
      <code>{String(props.content ?? "")}</code>
    </CodeBlock>
  </div>
);
