// A question a reply asks: what it says and its options as buttons while it
// waits for the person, and what was chosen once it does not.

import { useEffect, useState } from "react";
import { cn } from "cn";
import { icon } from "../icons";
import { t } from "../theme";
import { Button } from "@/components/ui/button";

interface Offered {
  value: string;
  label: string;
  icon?: string | null;
}

export interface Asked {
  question?: string;
  description?: string | null;
  options?: Offered[];
  primary?: string | null;
  open?: boolean;
  answer?: string | null;
}

// `live` is whether an answer can still be given: the question is open and
// its reply is the one on its way. A question in a message that is over is
// never open, whatever was kept of it.
export function Question({ data, live, onAnswer }: { data: Asked; live: boolean; onAnswer: (value: string) => void }) {
  // What was pressed, until the server says how the question ended.
  const [pressed, setPressed] = useState<string | null>(null);
  const options = Array.isArray(data.options) ? data.options : [];
  const open = live && Boolean(data.open);
  const chosen = options.find((o) => o.value === data.answer) ?? null;
  const Check = icon("check");
  const None = icon("minus");

  // A press the session did not take, in the middle of a change of page
  // say, is not the end of the question: its buttons come back.
  useEffect(() => {
    if (pressed === null) return;
    const again = window.setTimeout(() => setPressed(null), 4000);
    return () => window.clearTimeout(again);
  }, [pressed]);

  const press = (value: string) => {
    if (pressed !== null) return;
    setPressed(value);
    onAnswer(value);
  };

  const buttons = (
    <div className="flex flex-wrap gap-2 pt-1">
      {options.map((o) => {
        const I = icon(o.icon);
        return (
          <Button key={o.value} type="button" size="sm" variant={o.value === data.primary ? "default" : "outline"} disabled={pressed !== null} onClick={() => press(o.value)}>
            {I ? <I /> : null}
            {o.label}
          </Button>
        );
      })}
    </div>
  );

  const answered = chosen ? (
    <div className="flex items-center gap-1.5 text-sm font-medium">
      {Check ? <Check className="size-4 text-muted-foreground" /> : null}
      {chosen.label}
    </div>
  ) : (
    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
      {None ? <None className="size-4" /> : null}
      {t("not_answered")}
    </div>
  );

  return (
    <div data-slot="question" data-open={open ? "" : undefined} role="group" aria-label={data.question} className={cn("flex w-fit flex-col gap-1.5 rounded-xl border p-3 text-sm", open && "bg-card")}>
      <div className={cn(open ? "font-medium" : "text-muted-foreground")}>{data.question}</div>
      {open && data.description ? <div className="text-muted-foreground">{data.description}</div> : null}
      {open ? buttons : answered}
    </div>
  );
}
