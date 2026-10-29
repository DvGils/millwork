// The Chat: finished messages from props, the in-flight one from the stream,
// a composer with attachments and commands, every part kind rendered on
// shadcn's chat components.

import { t } from "../theme";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Renderer } from "../render";
import { Render } from "../render";
import { cn } from "cn";
import { icon } from "../icons";
import { safeUrl } from "../lib";
import { onStream } from "../ws";
import { upload, useFileUrl } from "./files";
import { applyChunk, type Part, type Transient, type UIMessage } from "../stream";
import { Markdown } from "./markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Message, MessageContent } from "@/components/ui/message";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@/components/ui/trace";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CustomComponent } from "../custom";

interface Command {
  id: string;
  label: string;
  icon?: string | null;
  description?: string | null;
}

interface Accept {
  accept?: string[] | null;
  max_files?: number;
  max_size_mb?: number | null;
}

interface FileRefWire {
  id: string;
  name: string;
  size: number;
  mime: string;
}

// ------------------------------------------------------------- the component

export const Chat: Renderer = ({ node, props, emit }) => {
  const finished = (Array.isArray(props.messages) ? (props.messages as UIMessage[]) : []);
  const busy = Boolean(props.busy);
  const inline = (props.inline ?? {}) as Record<string, { $node: string }>;
  const [inflight, setInflight] = useState<UIMessage | null>(null);
  const [transient, setTransient] = useState<Transient>({});
  // Chunks are applied synchronously against refs, then published: a state
  // updater would run later and lose the transient parts.
  const inflightRef = useRef<UIMessage | null>(null);
  const transientRef = useRef<Transient>({});

  useEffect(
    () =>
      onStream(node.id, (chunk) => {
        const extra: Transient = { ...transientRef.current };
        const applied = applyChunk(inflightRef.current, chunk as { type: string }, extra);
        // On finish the message stays on screen until the server's props carry
        // it (the busy flag dropping is what removes the stream copy).
        const next = (chunk as { type: string }).type === "finish" ? inflightRef.current : applied;
        inflightRef.current = next;
        transientRef.current = extra;
        setInflight(next);
        setTransient(extra);
      }),
    [node.id],
  );

  // When the server says the turn is over, its props carry the final message: drop the stream copy.
  useEffect(() => {
    if (!busy) {
      inflightRef.current = null;
      transientRef.current = { ...transientRef.current, status: undefined };
      setInflight(null);
      setTransient(transientRef.current);
    }
  }, [busy, finished.length]);

  const messages = useMemo(() => (inflight && busy ? [...finished, inflight] : finished), [finished, inflight, busy]);
  const suggestions = (transient.suggestions ?? (props.live_suggestions as string[] | undefined) ?? []).length
    ? (transient.suggestions ?? (props.live_suggestions as string[]))
    : messages.length === 0
      ? ((props.suggestions as string[] | undefined) ?? [])
      : [];

  const sendMessage = (text: string, files: FileRefWire[], command: string | null) => {
    if (!props.on_message || busy) return;
    emit("message", { text, files, command });
    transientRef.current = {};
    setTransient({});
  };

  return (
    <div className={cn("mw-fill flex max-h-dvh min-h-0 grow flex-col", props.cls as string)}>
      <MessageScrollerProvider>
        <MessageScroller className="min-h-0 grow">
          <MessageScrollerViewport className="px-3">
            <MessageScrollerContent className="flex flex-col gap-4 py-4">
              {messages.length === 0 && props.welcome ? (
                <div className="mx-auto max-w-prose py-8 text-center text-sm text-muted-foreground">
                  <Markdown content={String(props.welcome)} tight />
                </div>
              ) : null}
              {messages.map((m) => (
                <MessageScrollerItem key={m.id} messageId={m.id} scrollAnchor={m.role === "user"}>
                  <ChatMessage message={m} inline={inline} showSteps={String(props.show_steps ?? "collapsed")} streaming={m === inflight} />
                </MessageScrollerItem>
              ))}
              {transient.status && busy ? (
                <Marker variant="default">
                  <MarkerIcon>
                    <Spin />
                  </MarkerIcon>
                  <MarkerContent>{transient.status}</MarkerContent>
                </Marker>
              ) : null}
            </MessageScrollerContent>
          </MessageScrollerViewport>
          <MessageScrollerButton />
        </MessageScroller>
      </MessageScrollerProvider>
      {suggestions.length ? (
        <div className="flex flex-wrap gap-2 px-1 pb-2">
          {suggestions.map((s) => (
            <Button key={s} type="button" size="sm" variant="outline" disabled={busy} onClick={() => sendMessage(s, [], null)}>
              {s}
            </Button>
          ))}
        </div>
      ) : null}
      <Composer
        node={node.id}
        busy={busy}
        disabled={Boolean(props.disabled) || !props.on_message}
        placeholder={props.placeholder ? String(props.placeholder) : "Type a message"}
        attachments={(props.attachments as Accept | null) ?? null}
        commands={Array.isArray(props.commands) ? (props.commands as Command[]) : []}
        onSend={sendMessage}
        onStop={() => emit("stop")}
        canStop={Boolean(props.on_stop) || busy}
      />
    </div>
  );
};

function Spin() {
  const I = icon("loader-2");
  return I ? <I className="size-3.5 animate-spin" /> : null;
}

// ------------------------------------------------------------- one message

function ChatMessage({ message, inline, showSteps, streaming }: { message: UIMessage; inline: Record<string, { $node: string }>; showSteps: string; streaming: boolean }) {
  const user = message.role === "user";
  const steps = message.parts.filter((p) => p.type === "reasoning" || p.type.startsWith("tool-") || p.type === "error");
  const rest = message.parts.filter((p) => !steps.includes(p));
  const sources = rest.filter((p) => p.type === "source-url" || p.type === "source-document");
  const body = rest.filter((p) => !sources.includes(p));
  return (
    <Message align={user ? "end" : "start"}>
      <MessageContent className={cn("flex max-w-[85%] flex-col gap-2", user && "items-end")}>
        {!user && steps.length && showSteps !== "hidden" ? <StepsTrace parts={steps} collapsed={showSteps === "collapsed"} streaming={streaming} /> : null}
        {body.map((p, i) => (
          <PartView key={i} part={p} user={user} inline={inline} />
        ))}
        {sources.length ? <Sources parts={sources} /> : null}
      </MessageContent>
    </Message>
  );
}

function PartView({ part, user, inline }: { part: Part; user: boolean; inline: Record<string, { $node: string }> }) {
  switch (part.type) {
    case "text":
      return user ? (
        <Bubble align="end" variant="default">
          <BubbleContent className="whitespace-pre-wrap">{String(part.text)}</BubbleContent>
        </Bubble>
      ) : (
        <div className="text-sm">
          <Markdown content={String(part.text)} />
        </div>
      );
    case "file":
      return <FilePart part={part} />;
    case "data-component": {
      const slot = (part.data as { slot?: string } | undefined)?.slot;
      const ref = slot ? inline[slot] : undefined;
      return ref ? <Render id={ref.$node} /> : null;
    }
    default:
      if (part.type.startsWith("data-")) {
        const kind = part.type.slice(5);
        return (
          <CustomComponent node={{ id: `part:${kind}`, type: kind, props: {}, children: [] }} props={{ data: part.data, id: part.id }} emit={() => undefined}>
            {null}
          </CustomComponent>
        );
      }
      return null;
  }
}

function FilePart({ part }: { part: Part }) {
  // A file in a message is one of the session's: its bytes come over the socket.
  const fileId = typeof part.fileId === "string" ? part.fileId : null;
  const blob = useFileUrl(fileId);
  const url = fileId ? (blob ?? undefined) : safeUrl(part.url, { image: true });
  const media = String(part.mediaType ?? "");
  if (media.startsWith("image/")) return <img src={url} alt={String(part.filename ?? "")} className="max-h-64 rounded-lg" />;
  const Icon = icon("file-text");
  // A type the browser shows opens in a tab; anything else saves under its name.
  const viewable = media === "application/pdf" || media.startsWith("text/") || media.startsWith("audio/") || media.startsWith("video/");
  return (
    <a href={url} target="_blank" rel="noreferrer" download={viewable ? undefined : String(part.filename ?? "file")} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-muted/50">
      {Icon ? <Icon className="size-4 text-muted-foreground" /> : null}
      {String(part.filename ?? "file")}
    </a>
  );
}

function Sources({ parts }: { parts: Part[] }) {
  const Icon = icon("link");
  return (
    <div className="flex flex-wrap gap-1.5">
      {parts.map((p, i) =>
        p.type === "source-url" ? (
          <a key={i} href={safeUrl(p.url)} target="_blank" rel="noreferrer" title={p.snippet ? String(p.snippet) : undefined}>
            <Badge variant="outline" className="gap-1">
              {Icon ? <Icon className="size-3" /> : null}
              {String(p.title ?? p.url)}
            </Badge>
          </a>
        ) : (
          <Badge key={i} variant="outline" title={p.snippet ? String(p.snippet) : undefined}>
            {String(p.title ?? "document")}
          </Badge>
        ),
      )}
    </div>
  );
}

function StepsTrace({ parts, collapsed, streaming }: { parts: Part[]; collapsed: boolean; streaming: boolean }) {
  const lines = parts.map((p, i) => <StepLine key={i} part={p} />);
  if (!collapsed) return <Trace>{lines}</Trace>;
  const running = streaming && parts.some((p) => p.state === "streaming" || p.state === "input-available" || p.state === "input-streaming");
  const Icon = icon(running ? "loader-2" : "brain");
  return (
    <Trace>
      <TraceCollapsible defaultOpen={false}>
        <TraceCollapsibleTrigger>
          <TraceLine status={running ? "running" : undefined}>
            <TraceIcon>{Icon ? <Icon className={cn(running && "animate-spin")} /> : null}</TraceIcon>
            <TraceTitle>{running ? t("working") : t("steps", { n: parts.length })}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace>{lines}</Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

function StepLine({ part }: { part: Part }) {
  if (part.type === "reasoning") {
    const Icon = icon("brain");
    const streaming = part.state === "streaming";
    return (
      <TraceCollapsible defaultOpen={streaming}>
        <TraceCollapsibleTrigger>
          <TraceLine status={streaming ? "running" : undefined}>
            <TraceIcon>{Icon ? <Icon /> : null}</TraceIcon>
            <TraceTitle>{streaming ? t("thinking") : t("thought")}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <div className="whitespace-pre-wrap text-xs text-muted-foreground">{String(part.text)}</div>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    );
  }
  if (part.type === "error") {
    const Icon = icon("x-circle");
    return (
      <TraceLine status="error">
        <TraceIcon>{Icon ? <Icon /> : null}</TraceIcon>
        <TraceTitle>{String(part.errorText)}</TraceTitle>
      </TraceLine>
    );
  }
  const name = part.type.slice(5);
  const state = String(part.state ?? "");
  const running = state === "input-available" || state === "input-streaming";
  const failed = state === "output-error";
  const isStep = name === "step";
  const label = isStep ? String((part.input as { label?: string } | undefined)?.label ?? "step") : name;
  const Icon = icon(failed ? "x-circle" : running ? "loader-2" : isStep ? "check-circle-2" : "wand-2");
  const detail: ReactNode = isStep ? null : (
    <div className="flex flex-col gap-1 font-mono text-xs text-muted-foreground">
      {part.input !== undefined && part.input !== null ? <div>in: {JSON.stringify(part.input)}</div> : null}
      {state === "output-available" ? <div>out: {JSON.stringify(part.output)}</div> : null}
      {failed ? <div className="text-destructive">{String(part.errorText)}</div> : null}
    </div>
  );
  const line = (
    <TraceLine status={failed ? "error" : running ? "running" : undefined}>
      <TraceIcon>{Icon ? <Icon className={cn(running && "animate-spin")} /> : null}</TraceIcon>
      <TraceTitle>{label}</TraceTitle>
    </TraceLine>
  );
  if (!detail) return line;
  return (
    <TraceCollapsible defaultOpen={false}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>{detail}</TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

// ------------------------------------------------------------- the composer

function Composer({
  node,
  busy,
  disabled,
  placeholder,
  attachments,
  commands,
  onSend,
  onStop,
  canStop,
}: {
  node: string;
  busy: boolean;
  disabled: boolean;
  placeholder: string;
  attachments: Accept | null;
  commands: Command[];
  onSend: (text: string, files: FileRefWire[], command: string | null) => void;
  onStop: () => void;
  canStop: boolean;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<FileRefWire[]>([]);
  const [uploading, setUploading] = useState(false);
  const [command, setCommand] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const Send = icon("send");
  const Stop = icon("square");
  const Clip = icon("paperclip");
  const X = icon("x");

  const submit = useCallback(() => {
    const t = text.trim();
    if ((!t && files.length === 0) || busy || disabled || uploading) return;
    onSend(t, files, command);
    setText("");
    setFiles([]);
  }, [text, files, busy, disabled, uploading, onSend, command]);

  const take = async (list: FileList) => {
    setUploading(true);
    setError(null);
    for (const file of Array.from(list).slice(0, attachments?.max_files ?? 5)) {
      try {
        const ref = (await upload(node, file, () => undefined)) as FileRefWire;
        setFiles((f) => [...f, ref]);
      } catch (e) {
        setError(`${file.name}: ${(e as Error).message}`);
      }
    }
    setUploading(false);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-2">
      {files.length ? (
        <div className="flex flex-wrap gap-1.5">
          {files.map((f) => (
            <Badge key={f.id} variant="secondary" className="gap-1">
              {f.name}
              <button type="button" aria-label={t("remove")} onClick={() => setFiles((all) => all.filter((x) => x.id !== f.id))}>
                {X ? <X className="size-3" /> : "×"}
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
      <Textarea
        value={text}
        placeholder={placeholder}
        disabled={disabled}
        rows={1}
        className="field-sizing-content max-h-40 min-h-9 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <div className="flex items-center gap-2">
        {commands.length ? (
          <ToggleGroup value={command ? [command] : []} onValueChange={(v) => setCommand(((v as string[])[0] ?? null) as string | null)} size="sm">
            {commands.map((c) => {
              const I = icon(c.icon);
              return (
                <ToggleGroupItem key={c.id} value={c.id} aria-label={c.label} title={c.description ?? undefined}>
                  {I ? <I /> : null}
                  {c.label}
                </ToggleGroupItem>
              );
            })}
          </ToggleGroup>
        ) : null}
        {attachments ? (
          <>
            <input ref={inputRef} type="file" className="sr-only" multiple accept={attachments.accept?.join(",")} onChange={(e) => e.target.files && void take(e.target.files)} />
            <Button type="button" variant="ghost" size="icon-sm" aria-label={t("attach")} disabled={disabled || uploading} onClick={() => inputRef.current?.click()}>
              {Clip ? <Clip /> : null}
            </Button>
          </>
        ) : null}
        {error ? <span className="truncate text-xs text-destructive">{error}</span> : null}
        <span className="grow" />
        {busy && canStop ? (
          <Button type="button" variant="outline" size="sm" onClick={onStop}>
            {Stop ? <Stop /> : null}
            Stop
          </Button>
        ) : (
          <Button type="button" size="sm" disabled={disabled || busy || uploading || (!text.trim() && files.length === 0)} onClick={submit} aria-label={t("send")}>
            {Send ? <Send /> : null}
            Send
          </Button>
        )}
      </div>
    </div>
  );
}
