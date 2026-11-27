// An option as it is shown wherever one is listed or chosen: its icon, when
// it has one, in front of its label.

import type { ReactNode } from "react";
import { cn } from "cn";
import { icon } from "../icons";

export function optionLabel(
  o: { value: string | number | boolean; label?: string | null; icon?: string | null },
  size = "size-4",
  cut = false,
): ReactNode {
  const label = o.label ?? String(o.value);
  // Cut where it is shown in a row that has no more room for it, a chip.
  const text = cut ? <span className="min-w-0 truncate">{label}</span> : label;
  const Drawn = o.icon ? icon(o.icon) : null;
  if (!Drawn) return text;
  return (
    <>
      <Drawn className={cn("shrink-0", size)} />
      {text}
    </>
  );
}
