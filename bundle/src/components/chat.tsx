// The Chat: finished messages from props, the in-flight one from the stream,
// a composer with attachments and commands, every part kind rendered on
// shadcn's chat components.

import { locale, t } from "../theme";
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
import { CopyButton } from "./copy";
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
import { Message, MessageAvatar, MessageContent } from "@/components/ui/message";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@/components/ui/trace";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CustomComponent } from "../custom";
import { Slot } from "../render";
import { ChatContext, type ChatApi, type ChatFile } from "../chat-context";

interface Command {
  id: string;
  label: string;
  icon?: string | null;
  description?: string | null;
}

interface ActionSpec {
  id: string;
  label: string;
  icon?: string | null;
}

// What a message may offer under itself, from the Chat's props and handlers.
interface Tools {
  copy: boolean;
  feedback: boolean;
  regenerate: boolean;
  edit: boolean;
  actions: ActionSpec[];
  busy: boolean;
  emit: (name: string, payload?: unknown) => void;
}

// The reading aids a Chat asked for; each is off unless its prop is set.
interface Aids {
  avatar: string | null;
  names: boolean;
  timestamps: boolean;
  durations: boolean;
  assistantName: string;
  userName: string;
  // The label of each command the chat offers, by id.
  commands: Record<string, string>;
}

// A clock time in the theme's locale, with the date once it is not today.
function clock(at: unknown): string | null {
  if (typeof at !== "number") return null;
  const d = new Date(at * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return new Intl.DateTimeFormat(locale(), sameDay ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(d);
}

function elapsed(took: unknown): string | null {
  if (typeof took !== "number") return null;
  if (took < 60) return `${took < 10 ? took.toFixed(1) : Math.round(took)} s`;
  const m = Math.floor(took / 60);
  return `${m} min ${Math.round(took - m * 60)} s`;
}

interface Accept {
  accept?: string[] | null;
  max_files?: number;
  max_size_mb?: number | null;
  capture?: "user" | "environment" | null;
  paperclip?: boolean;
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

  const tools: Tools = {
    copy: props.copyable !== false,
    feedback: Boolean(props.on_feedback),
    regenerate: props.regenerate !== false && Boolean(props.on_message),
    edit: props.edit !== false && Boolean(props.on_message),
    actions: props.on_action && Array.isArray(props.actions) ? (props.actions as ActionSpec[]) : [],
    // A disabled chat starts no reply: no message, no edit and no second try.
    busy: busy || Boolean(props.disabled),
    emit,
  };
  // Only the latest answer can be regenerated: an earlier one would take the
  // whole conversation after it along.
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant")?.id;
  const user = (window as unknown as { __mw?: { user?: { name?: string } } }).__mw?.user;
  const aids: Aids = {
    avatar: typeof props.avatar === "string" && props.avatar ? safeUrl(props.avatar, { image: true }) ?? null : null,
    names: Boolean(props.names),
    timestamps: Boolean(props.timestamps),
    durations: Boolean(props.durations),
    assistantName: typeof props.assistant_name === "string" && props.assistant_name ? props.assistant_name : t("assistant"),
    userName: user?.name ? String(user.name) : t("you"),
    commands: Object.fromEntries((Array.isArray(props.commands) ? (props.commands as Command[]) : []).map((c) => [c.id, c.label])),
  };

  return (
    <div className={cn("mw-fill flex max-h-dvh min-h-0 grow flex-col", props.cls as string)}>
      <MessageScrollerProvider autoScroll defaultScrollPosition="end">
        <MessageScroller className="min-h-0 grow">
          <MessageScrollerViewport className="px-3">
            <MessageScrollerContent className="flex flex-col gap-4 py-4">
              {messages.length === 0 && props.welcome ? (
                <div className="mx-auto max-w-prose py-8 text-center text-sm text-muted-foreground">
                  <Markdown content={String(props.welcome)} tight />
                </div>
              ) : null}
              {messages.map((m) => (
                <MessageScrollerItem key={m.id} messageId={m.id}>
                  <ChatMessage message={m} inline={inline} showSteps={String(props.show_steps ?? "collapsed")} streaming={m === inflight} tools={tools} last={m.id === lastAssistant} aids={aids} />
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
            <Button key={s} type="button" size="sm" variant="outline" disabled={busy || Boolean(props.disabled) || !props.on_message} onClick={() => sendMessage(s, [], null)}>
              {s}
            </Button>
          ))}
        </div>
      ) : null}
      <Composer
        node={node.id}
        busy={busy}
        disabled={Boolean(props.disabled) || !props.on_message}
        placeholder={props.placeholder ? String(props.placeholder) : t("type_message")}
        maxChars={typeof props.max_chars === "number" ? props.max_chars : undefined}
        attachments={(props.attachments as Accept | null) ?? null}
        commands={Array.isArray(props.commands) ? (props.commands as Command[]) : []}
        tools={Array.isArray(props.tools) ? (props.tools as unknown[]) : []}
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

function ChatMessage({ message, inline, showSteps, streaming, tools, last, aids }: { message: UIMessage; inline: Record<string, { $node: string }>; showSteps: string; streaming: boolean; tools: Tools; last: boolean; aids: Aids }) {
  const user = message.role === "user";
  const [editing, setEditing] = useState(false);
  const meta = message.metadata ?? {};
  const line = [
    aids.names ? (user ? aids.userName : aids.assistantName) : null,
    aids.timestamps ? clock(meta.at) : null,
    aids.durations && !user && !streaming ? elapsed(meta.took) : null,
  ].filter((x): x is string => Boolean(x));
  const steps = message.parts.filter((p) => p.type === "reasoning" || p.type.startsWith("tool-") || p.type === "error");
  const rest = message.parts.filter((p) => !steps.includes(p));
  const sources = rest.filter((p) => p.type === "source-url" || p.type === "source-document");
  const body = rest.filter((p) => !sources.includes(p));
  const text = () => message.parts.filter((p) => p.type === "text").map((p) => String(p.text ?? "")).join("\n");
  return (
    <Message align={user ? "end" : "start"}>
      {!user && aids.avatar ? (
        <MessageAvatar className="self-start">
          <img src={aids.avatar} alt="" className="size-8 object-cover" />
        </MessageAvatar>
      ) : null}
      <MessageContent className={cn("flex max-w-[85%] flex-col gap-2", user && "items-end")}>
        {line.length ? (
          <div className={cn("text-xs text-muted-foreground transition-opacity", "opacity-0 group-hover/message:opacity-100 group-focus-within/message:opacity-100 [@media(hover:none)]:opacity-100")}>
            {line.join(" · ")}
          </div>
        ) : null}
        {!user && steps.length && showSteps !== "hidden" ? <StepsTrace parts={steps} collapsed={showSteps === "collapsed"} streaming={streaming} durations={aids.durations} /> : null}
        {editing ? (
          <EditBox
            text={text()}
            onSave={(next) => {
              tools.emit("edit", { id: message.id, text: next });
              setEditing(false);
            }}
            onCancel={() => setEditing(false)}
          />
        ) : (
          body.map((p, i) => <PartView key={i} part={p} user={user} inline={inline} />)
        )}
        {/* The command a message was sent under, which is all there is to see
            of a message that was a command and nothing else. */}
        {user && typeof meta.command === "string" ? <Badge variant="outline">{aids.commands[meta.command] ?? meta.command}</Badge> : null}
        {sources.length ? <Sources parts={sources} /> : null}
        {streaming || editing ? null : user ? (
          tools.edit ? (
            <ActionRow>
              <IconAction name="pencil" label={t("edit")} disabled={tools.busy} onClick={() => setEditing(true)} />
            </ActionRow>
          ) : null
        ) : (
          <AssistantActions message={message} tools={tools} last={last} text={text} />
        )}
      </MessageContent>
    </Message>
  );
}

// ------------------------------------------------------------- under a message

// A box that opens under the last message would sit below the fold of the
// message list; it comes into view when it mounts.
function intoView(el: HTMLDivElement | null) {
  el?.scrollIntoView({ block: "nearest" });
}

// Hidden until the message is hovered or holds focus; always there without a
// mouse. `pinned` keeps it in view, for a message with feedback on it.
function ActionRow({ children, pinned }: { children: ReactNode; pinned?: boolean }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-0.5 transition-opacity", pinned ? "opacity-100" : "opacity-0 group-hover/message:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100")}>
      {children}
    </div>
  );
}

function IconAction({ name, label, active, disabled, onClick }: { name: string; label: string; active?: boolean; disabled?: boolean; onClick: () => void }) {
  const Icon = icon(name);
  return (
    <Button type="button" size="icon-xs" variant="ghost" aria-label={label} title={label} aria-pressed={active} disabled={disabled} className={cn("text-muted-foreground hover:text-foreground", active && "text-foreground")} onClick={onClick}>
      {Icon ? <Icon className={cn(active && "fill-current")} /> : null}
    </Button>
  );
}

function AssistantActions({ message, tools, last, text }: { message: UIMessage; tools: Tools; last: boolean; text: () => string }) {
  const feedback = (message.metadata as { feedback?: { value?: string; comment?: string | null } } | undefined)?.feedback;
  const current = feedback?.value ?? null;
  const [commenting, setCommenting] = useState(false);
  const [comment, setComment] = useState("");
  const rate = (value: "up" | "down") => {
    const next = current === value ? null : value;
    tools.emit("feedback", { id: message.id, value: next, comment: null });
    setCommenting(next === "down");
    setComment("");
  };
  const show = tools.copy || tools.feedback || (tools.regenerate && last) || tools.actions.length > 0;
  if (!show) return null;
  return (
    <>
      <ActionRow pinned={current !== null}>
        {tools.copy ? <CopyButton text={text} /> : null}
        {tools.feedback ? (
          <>
            <IconAction name="thumbs-up" label={t("good_response")} active={current === "up"} onClick={() => rate("up")} />
            <IconAction name="thumbs-down" label={t("bad_response")} active={current === "down"} onClick={() => rate("down")} />
          </>
        ) : null}
        {tools.regenerate && last ? <IconAction name="refresh-cw" label={t("regenerate")} disabled={tools.busy} onClick={() => tools.emit("regenerate", { id: message.id })} /> : null}
        {tools.actions.map((a) => {
          const Icon = icon(a.icon);
          return (
            <Button key={a.id} type="button" size="xs" variant="ghost" className="text-muted-foreground hover:text-foreground" onClick={() => tools.emit("action", { id: message.id, action: a.id })}>
              {Icon ? <Icon /> : null}
              {a.label}
            </Button>
          );
        })}
      </ActionRow>
      {commenting && current === "down" ? (
        <div ref={intoView} className="flex w-full max-w-md flex-col gap-2 rounded-lg border bg-card p-2">
          <Textarea value={comment} placeholder={t("feedback_prompt")} rows={2} autoFocus className="min-h-16 resize-none" onChange={(e) => setComment(e.target.value)} />
          <div className="flex justify-end gap-1">
            <Button type="button" size="sm" variant="ghost" onClick={() => setCommenting(false)}>
              {t("skip")}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!comment.trim()}
              onClick={() => {
                tools.emit("feedback", { id: message.id, value: "down", comment: comment.trim() });
                setCommenting(false);
              }}
            >
              {t("send")}
            </Button>
          </div>
        </div>
      ) : null}
    </>
  );
}

// A user message being edited in place: Enter sends it again, Escape leaves it as it was.
function EditBox({ text, onSave, onCancel }: { text: string; onSave: (text: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState(text);
  const save = () => {
    if (value.trim()) onSave(value.trim());
  };
  return (
    <div ref={intoView} className="flex w-full flex-col gap-2 rounded-xl border bg-card p-2">
      <Textarea
        value={value}
        autoFocus
        rows={2}
        className="field-sizing-content max-h-60 min-h-9 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            save();
          } else if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
      />
      <div className="flex justify-end gap-1">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button type="button" size="sm" disabled={!value.trim()} onClick={save}>
          {t("save")}
        </Button>
      </div>
    </div>
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

function StepsTrace({ parts, collapsed, streaming, durations }: { parts: Part[]; collapsed: boolean; streaming: boolean; durations: boolean }) {
  const lines = parts.map((p, i) => <StepLine key={i} part={p} durations={durations} />);
  if (!collapsed) return <Trace>{lines}</Trace>;
  const running = streaming && parts.some((p) => p.state === "streaming" || p.state === "input-available" || p.state === "input-streaming");
  const Icon = icon(running ? "loader-2" : "brain");
  return (
    <Trace>
      <TraceCollapsible defaultOpen={false}>
        <TraceCollapsibleTrigger>
          <TraceLine status={running ? "running" : undefined}>
            <TraceIcon>{Icon ? <Icon className={cn(running && "animate-spin")} /> : null}</TraceIcon>
            <TraceTitle>{running ? t("working") : (parts.length === 1 ? t("one_step") : t("steps", { n: parts.length }))}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace>{lines}</Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

function StepLine({ part, durations }: { part: Part; durations: boolean }) {
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
  const took = durations && !running ? elapsed(part.took) : null;
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
      {took ? <span className="ml-1 text-xs text-muted-foreground">{took}</span> : null}
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
  maxChars,
  attachments,
  commands,
  tools,
  onSend,
  onStop,
  canStop,
}: {
  node: string;
  busy: boolean;
  disabled: boolean;
  placeholder: string;
  maxChars?: number;
  attachments: Accept | null;
  commands: Command[];
  tools: unknown[];
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
    // A chosen command is a message by itself: one that takes no words.
    if ((!t && files.length === 0 && !command) || busy || disabled || uploading) return;
    onSend(t, files, command);
    setText("");
    setFiles([]);
  }, [text, files, busy, disabled, uploading, onSend, command]);

  // What the chat's tools may do, under the same limits as the paperclip.
  const api = useMemo<ChatApi>(
    () => ({
      upload: (file: File) => upload(node, file, () => undefined) as Promise<ChatFile>,
      send: (t: string, attached: ChatFile[] = []) => {
        if (disabled || busy) return;
        onSend(t.trim(), attached as FileRefWire[], command);
      },
      busy: busy || disabled,
    }),
    [node, disabled, busy, onSend, command],
  );

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
    <div className="relative flex flex-col gap-2 rounded-xl border bg-card p-2">
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
        maxLength={maxChars}
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
        {attachments && attachments.paperclip !== false ? (
          <>
            <input ref={inputRef} type="file" className="sr-only" multiple accept={attachments.accept?.join(",")} capture={attachments.capture ?? undefined} onChange={(e) => e.target.files && void take(e.target.files)} />
            <Button type="button" variant="ghost" size="icon-sm" aria-label={t("attach")} disabled={disabled || uploading} onClick={() => inputRef.current?.click()}>
              {Clip ? <Clip /> : null}
            </Button>
          </>
        ) : null}
        {tools.length ? (
          <ChatContext.Provider value={api}>
            {tools.map((slot, i) => (
              <Slot key={i} value={slot} />
            ))}
          </ChatContext.Provider>
        ) : null}
        {error ? <span className="truncate text-xs text-destructive">{error}</span> : null}
        <span className="grow" />
        {busy && canStop ? (
          <Button type="button" variant="outline" size="sm" onClick={onStop}>
            {Stop ? <Stop /> : null}
            {t("stop")}
          </Button>
        ) : (
          <Button type="button" size="sm" disabled={disabled || busy || uploading || (!text.trim() && files.length === 0 && !command)} onClick={submit} aria-label={t("send")}>
            {Send ? <Send /> : null}
            {t("send")}
          </Button>
        )}
      </div>
    </div>
  );
}
