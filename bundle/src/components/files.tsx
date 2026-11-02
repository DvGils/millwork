// Files: an upload dropzone over the session's socket, cards, viewers, downloads.
// A session file has no URL: the tab fetches its bytes over the socket by id and
// keeps them as a blob URL.

import { t } from "../theme";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Renderer } from "../render";
import { cn } from "cn";
import { icon } from "../icons";
import { fileUrl, onStatus, request, saveFile } from "../ws";
import { toast } from "@/components/ui/toast";
import { safeUrl } from "../lib";
import { Button } from "@/components/ui/button";
import { Progress, ProgressIndicator, ProgressTrack } from "@/components/ui/progress";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface FileRef {
  id: string;
  name: string;
  size: number;
  mime: string;
}

// The blob URL of a session file, once its bytes have arrived; null until then
// or when the fetch failed. A fetch cut by a disconnect is asked again when the
// socket is back, so an image never stays blank for the rest of the session.
export function useFileUrl(id: string | null | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    if (!id) {
      setUrl(null);
      return;
    }
    fileUrl(id)
      .then((u) => alive && setUrl(u))
      .catch(() => {
        if (!alive) return;
        setUrl(null);
        const stop = onStatus((s) => {
          if (s === "open") {
            stop();
            if (alive) setAttempt((n) => n + 1);
          }
        });
      });
    return () => {
      alive = false;
    };
  }, [id, attempt]);
  return url;
}

function failedDownload() {
  toast.add({ title: t("download_failed"), type: "error" });
}

interface MenuItem {
  id: string;
  label: string;
  icon?: string | null;
  disabled?: boolean;
  destructive?: boolean;
}

export function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function kindOf(mime: string): string {
  const major = mime.split("/")[0];
  if (major === "image" || major === "audio" || major === "video") return major;
  if (mime === "application/pdf") return "pdf";
  if (major === "text" || mime === "application/json") return "text";
  return "file";
}

const kindIcon: Record<string, string> = {
  image: "image",
  pdf: "file-text",
  text: "file-text",
  audio: "volume-2",
  video: "play",
  file: "file",
};

// One request per file, its bytes as frames behind the message; the session
// stores them under the node's spec and answers with the record.
export function upload(node: string, file: File, onProgress: (p: number) => void, field?: string): Promise<FileRef> {
  const payload: Record<string, unknown> = { name: file.name, mime: file.type || null };
  if (field) payload.field = field;
  return request(node, "upload", payload, { body: file, onProgress }).then((r) => r as FileRef);
}

export const FileUpload: Renderer = ({ node, props, emit }) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState<{ name: string; progress: number }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const accept = Array.isArray(props.accept) ? (props.accept as string[]) : null;
  const multiple = Boolean(props.multiple);
  const maxFiles = typeof props.max_files === "number" ? props.max_files : 10;
  const disabled = Boolean(props.disabled) || busy.length > 0;
  const Up = icon("upload");

  const take = useCallback(
    async (list: FileList | File[]) => {
      const files = Array.from(list).slice(0, multiple ? maxFiles : 1);
      if (!files.length) return;
      setError(null);
      setBusy(files.map((f) => ({ name: f.name, progress: 0 })));
      const done: FileRef[] = [];
      for (let i = 0; i < files.length; i++) {
        try {
          const ref = await upload(node.id, files[i], (p) =>
            setBusy((b) => b.map((x, j) => (j === i ? { ...x, progress: p } : x))),
          );
          done.push(ref);
        } catch (e) {
          const reason = (e as Error).message;
          setError(`${files[i].name}: ${reason}`);
          if (props.on_reject) emit("reject", { name: files[i].name, reason });
        }
      }
      setBusy([]);
      if (done.length && props.on_upload) emit("upload", done);
      if (inputRef.current) inputRef.current.value = "";
    },
    [multiple, maxFiles, node.id, props.on_upload, props.on_reject, emit],
  );

  const zone = props.dropzone !== false;
  return (
    <div className={cn("flex flex-col gap-2", props.cls as string)}>
      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        accept={accept ? accept.join(",") : undefined}
        multiple={multiple}
        disabled={disabled}
        onChange={(e) => e.target.files && void take(e.target.files)}
      />
      {zone ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            if (!disabled) void take(e.dataTransfer.files);
          }}
          className={cn(
            "flex w-full flex-col items-center justify-center gap-1 rounded-xl border border-dashed px-4 py-6 text-sm transition-colors",
            over ? "border-primary bg-primary/5" : "border-border bg-muted/30 hover:bg-muted/60",
            disabled && "opacity-60",
          )}
        >
          {Up ? <Up className="size-5 text-muted-foreground" /> : null}
          <span className="font-medium">{String(props.label ?? (multiple ? "Drop files or click to choose" : "Drop a file or click to choose"))}</span>
          {props.description || accept ? (
            <span className="text-xs text-muted-foreground">{String(props.description ?? accept?.join(", "))}</span>
          ) : null}
        </button>
      ) : (
        <Button type="button" variant="outline" disabled={disabled} onClick={() => inputRef.current?.click()}>
          {Up ? <Up /> : null}
          {String(props.label ?? "Choose file")}
        </Button>
      )}
      {busy.map((b, i) => (
        <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="w-40 truncate">{b.name}</span>
          <Progress value={Math.round(b.progress * 100)} className="grow">
            <ProgressTrack>
              <ProgressIndicator />
            </ProgressTrack>
          </Progress>
        </div>
      ))}
      {error ? <div className="text-xs text-destructive">{error}</div> : null}
    </div>
  );
};

export const FileCard: Renderer = ({ props, emit }) => {
  const file = (props.file ?? null) as FileRef | null;
  const name = String(props.name ?? file?.name ?? "");
  const size = typeof props.size === "number" ? props.size : file?.size;
  const kind = String(props.kind ?? (file ? kindOf(file.mime) : "file"));
  const url = typeof props.url === "string" ? safeUrl(props.url) : null;
  const status = String(props.status ?? "ready");
  // A session file opens in a new tab from its bytes; an outside URL as a link.
  // The tab is opened while the click still counts as the user's, then pointed
  // at the bytes once they are here; a blocked popup falls back to saving.
  const open = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!file) return;
    e.preventDefault();
    const win = window.open("", "_blank", "noopener");
    fileUrl(file.id)
      .then((u) => {
        if (win) win.location.href = u;
        else return saveFile(file.id, file.name);
      })
      .catch(() => {
        win?.close();
        failedDownload();
      });
  };
  const actions = Array.isArray(props.actions) ? (props.actions as MenuItem[]) : [];
  const Icon = icon(kindIcon[kind] ?? "file");
  const More = icon("more-horizontal");
  const Spin = icon("loader-2");
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-lg border bg-card px-3 py-2 text-sm",
        props.on_click && "cursor-pointer hover:bg-accent/50",
        status === "error" && "border-destructive/50",
        props.cls as string,
      )}
      onClick={props.on_click ? () => emit("click") : undefined}
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        {status === "loading" && Spin ? <Spin className="size-4 animate-spin" /> : Icon ? <Icon className="size-4" /> : null}
      </span>
      <div className="min-w-0 grow">
        <div className="truncate font-medium">{name}</div>
        <div className="truncate text-xs text-muted-foreground">
          {[size !== undefined ? formatSize(size) : null, props.meta ? String(props.meta) : null].filter(Boolean).join(" · ")}
        </div>
      </div>
      {url || file ? (
        <a href={url ?? "#"} target="_blank" rel="noreferrer" className="text-xs text-primary underline-offset-4 hover:underline" onClick={file ? open : (e) => e.stopPropagation()}>
          {t("open")}
        </a>
      ) : null}
      {actions.length ? (
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" aria-label={t("actions")} onClick={(e) => e.stopPropagation()} />}>
            {More ? <More /> : "…"}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {actions.map((a) => {
              const AIcon = icon(a.icon);
              return (
                <DropdownMenuItem key={a.id} disabled={Boolean(a.disabled)} variant={a.destructive ? "destructive" : "default"} onClick={() => emit("action", a.id)}>
                  {AIcon ? <AIcon /> : null}
                  {a.label}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
};

const imageSize: Record<string, string> = { sm: "max-h-32", md: "max-h-64", lg: "max-h-[32rem]", full: "w-full" };

export const Image: Renderer = ({ props, emit }) => {
  const ref = typeof props.src === "object" && props.src ? (props.src as FileRef) : null;
  const blob = useFileUrl(ref?.id);
  const src = ref ? (blob ?? undefined) : safeUrl(typeof props.src === "string" ? props.src : undefined, { image: true });
  return (
    <img
      src={src}
      alt={String(props.alt ?? "")}
      className={cn("rounded-lg", imageSize[String(props.size ?? "md")], props.fit === "cover" ? "object-cover" : "object-contain", props.on_click && "cursor-zoom-in", props.cls as string)}
      onClick={props.on_click ? () => emit("click") : undefined}
    />
  );
};

export const Pdf: Renderer = ({ props }) => {
  const ref = typeof props.src === "object" && props.src ? (props.src as FileRef) : null;
  const blob = useFileUrl(ref?.id);
  const base = ref ? blob : safeUrl(typeof props.src === "string" ? props.src : undefined);
  const src = base ? (typeof props.page === "number" ? `${base}#page=${props.page}` : base) : undefined;
  return (
    <iframe
      src={src}
      title="PDF"
      className={cn("w-full rounded-lg border", props.cls as string)}
      style={{ height: String(props.height ?? "70vh") }}
    />
  );
};

export const Download: Renderer = ({ props, emit }) => {
  const Icon = icon(props.icon);
  const variant = String(props.variant ?? "outline") as "default" | "secondary" | "outline" | "ghost" | "link";
  // A session file names itself: the tab fetches it without a round trip through
  // the handler. Anything else is made on click and arrives as a download command.
  const fileId = typeof props.file_id === "string" ? props.file_id : null;
  const click = () => {
    if (!fileId) {
      emit("download");
      return;
    }
    saveFile(fileId, String(props.filename ?? "")).catch(failedDownload);
  };
  return (
    <Button type="button" variant={variant === ("primary" as string) ? "default" : variant} disabled={Boolean(props.disabled)} onClick={click}>
      {Icon ? <Icon /> : null}
      {String(props.label ?? t("download"))}
    </Button>
  );
};
