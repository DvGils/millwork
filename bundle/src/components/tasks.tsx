// Tasks on the page: a Progress bar fed by a task, and Steps on Trace.

import type { Renderer } from "../render";
import { cn } from "cn";
import { icon } from "../icons";
import { t as text } from "../theme";
import { Progress as UiProgress, ProgressIndicator, ProgressLabel, ProgressTrack, ProgressValue } from "@/components/ui/progress";
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";

interface Step {
  id: string;
  label: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled" | "skipped";
  note?: string | null;
  lines?: string[];
  children?: Step[];
}

interface TaskSnapshot {
  id: string;
  label: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  progress: number | null;
  message: string | null;
  steps: Step[];
  error: { type: string; message: string } | null;
}

function task(props: Record<string, unknown>): TaskSnapshot | null {
  const t = props.task;
  return t && typeof t === "object" ? (t as TaskSnapshot) : null;
}

export const Progress: Renderer = ({ props }) => {
  const t = task(props);
  const raw = t ? t.progress : typeof props.value === "number" ? props.value : null;
  const value = typeof raw === "number" ? Math.round(raw * 100) : null;
  const label = props.label ?? t?.label;
  const description = props.description ?? t?.message ?? (t?.status === "failed" ? t.error?.message : undefined);
  const indeterminate = value === null && (!t || t.status === "running" || t.status === "pending");
  const failed = t?.status === "failed";
  const cancelled = t?.status === "cancelled";
  // A task that ended without finishing says so where its percentage was.
  const ended = failed ? text("failed") : cancelled ? text("canceled") : null;
  return (
    <UiProgress
      value={indeterminate ? null : (value ?? (t?.status === "done" ? 100 : 0))}
      className={cn(
        "flex flex-col gap-1.5",
        failed && "[&_[data-slot=progress-indicator]]:bg-destructive",
        cancelled && "[&_[data-slot=progress-indicator]]:bg-muted-foreground/40",
        props.cls as string,
      )}
    >
      {label || value !== null || ended ? (
        <div className="flex items-center justify-between text-sm">
          {label ? <ProgressLabel>{String(label)}</ProgressLabel> : <span />}
          {ended ? (
            <span className={cn("text-xs", failed ? "text-destructive" : "text-muted-foreground")}>{ended}</span>
          ) : value !== null ? (
            <ProgressValue />
          ) : t ? (
            <span className="text-xs text-muted-foreground">{t.status}</span>
          ) : null}
        </div>
      ) : null}
      <ProgressTrack>
        <ProgressIndicator />
      </ProgressTrack>
      {description ? <p className={cn("text-xs", failed ? "text-destructive" : "text-muted-foreground")}>{String(description)}</p> : null}
    </UiProgress>
  );
};

const stepStatus: Record<string, "running" | "error" | "pending" | undefined> = {
  running: "running",
  failed: "error",
  cancelled: "error",
  pending: "pending",
  skipped: "pending",
  done: undefined,
};

const stepIcon: Record<string, string> = {
  running: "loader-2",
  failed: "x-circle",
  cancelled: "x-circle",
  pending: "circle",
  skipped: "minus",
  done: "check-circle-2",
};

function StepLine({ step, compact }: { step: Step; compact: boolean }) {
  const Icon = icon(stepIcon[step.status] ?? "circle");
  const status = stepStatus[step.status];
  const hasDetail = (step.lines?.length ?? 0) > 0 || (step.children?.length ?? 0) > 0;
  const line = (
    <TraceLine status={status}>
      <TraceIcon>{Icon ? <Icon className={cn(step.status === "running" && "animate-spin", step.status === "done" && "text-success")} /> : null}</TraceIcon>
      <TraceTitle>{step.label}</TraceTitle>
      {step.note ? <TraceDescription>{step.note}</TraceDescription> : null}
    </TraceLine>
  );
  if (!hasDetail) return line;
  return (
    <TraceCollapsible defaultOpen={step.status === "running" && !compact}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Trace>
          {(step.children ?? []).map((c) => (
            <StepLine key={c.id} step={c} compact={compact} />
          ))}
          {step.lines?.length ? (
            <pre className="max-h-48 overflow-auto rounded-md bg-muted p-2 font-mono text-xs">{step.lines.join("\n")}</pre>
          ) : null}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

export const Steps: Renderer = ({ props }) => {
  const t = task(props);
  const items = (Array.isArray(props.items) ? (props.items as Step[]) : t?.steps) ?? [];
  const compact = Boolean(props.compact);
  return (
    <Trace className={cn(props.cls as string)}>
      {items.map((s) => (
        <StepLine key={s.id} step={s} compact={compact} />
      ))}
      {t?.status === "failed" && t.error ? (
        <TraceLine status="error">
          <TraceTitle>{t.error.message}</TraceTitle>
        </TraceLine>
      ) : null}
    </Trace>
  );
};
