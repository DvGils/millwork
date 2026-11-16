import { createContext, useContext } from "react";

// Whether a node is hidden, or is in something that is. A hidden node is
// kept in a wrapper that does not show, which hides what is drawn inside
// it. A dialog and a sheet are drawn at the top of the page and not
// inside their wrapper, so they ask here whether they may open.
export const HiddenAbove = createContext(false);

export function useHiddenAbove(): boolean {
  return useContext(HiddenAbove);
}
