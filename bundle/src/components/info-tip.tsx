// An explanation beside a label or a title, behind a mark the theme chooses.
// With an icon, the icon is a button of its own: the keyboard stops at it,
// a press or a tap shows the explanation as pointing at it does, and the
// explanation is its name, so a screen reader says it there. With a dotted
// line, the text itself is what the pointer and the keyboard find, and the
// explanation is its description.

import { useState, type ReactNode } from "react";
import { cn } from "cn";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { icon } from "../icons";
import { tooltipMark } from "../theme";

// The icon after a text that has a tooltip, or nothing where the theme
// draws a line under the text instead.
export function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const mark = tooltipMark();
  if (mark === "underline") return null;
  const Mark = icon(mark === "info" ? "info" : "circle-help");
  return (
    <Tooltip open={open} onOpenChange={setOpen}>
      <TooltipTrigger
        // A press shows it and does not take it away again: a finger has no
        // other way to ask. It goes when the keyboard or the finger moves on.
        closeOnClick={false}
        render={
          <button
            type="button"
            data-slot="info-tip"
            aria-label={text}
            onClick={() => setOpen(true)}
            onBlur={() => setOpen(false)}
            className="inline-flex size-4 shrink-0 cursor-help items-center justify-center rounded-full text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        }
      >
        {Mark ? <Mark className="size-3.5" /> : "?"}
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}

// The text of a label or a title. Where the theme marks a tooltip with a
// dotted line, the text carries the line and the tooltip.
export function Tipped({ text, children }: { text?: string | null; children: ReactNode }) {
  if (!text || tooltipMark() !== "underline") return <>{children}</>;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            data-slot="info-tip"
            aria-description={text}
            className="cursor-help underline decoration-muted-foreground/70 decoration-dotted underline-offset-4 outline-none focus-visible:decoration-solid"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}

// A label with the mark of its tooltip beside it. Without a tooltip it is
// the label alone, as wide as it always was.
export function Marked({ text, className, children }: { text?: string | null; className?: string; children: ReactNode }) {
  if (!text) return <>{children}</>;
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      {children}
      <InfoTip text={text} />
    </div>
  );
}
