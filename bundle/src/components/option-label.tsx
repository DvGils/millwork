// An option as it is shown wherever one is listed or chosen: its icon, when
// it has one, in front of its label.

import type { ReactNode } from "react";
import { cn } from "cn";
import { icon } from "../icons";

export function optionLabel(o: { value: string; label?: string | null; icon?: string | null }, size = "size-4"): ReactNode {
  const text = o.label ?? o.value;
  const Drawn = o.icon ? icon(o.icon) : null;
  if (!Drawn) return text;
  return (
    <>
      <Drawn className={cn("shrink-0", size)} />
      {text}
    </>
  );
}
