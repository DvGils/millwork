import type { MouseEvent } from "react";
import { createContext } from "react";
import { navigate } from "../ws";
import { hasSession, isInternalPath, safeUrl } from "../lib";

// What makes an element a link to `href`: a page of the app is opened on the
// session, without a reload, unless the click asks for a new tab or window.
// Anything else is the browser's own business.
export function anchorProps(href: unknown, target: unknown) {
  const blank = target === "_blank";
  const internal = isInternalPath(href) && !blank && hasSession();
  return {
    href: safeUrl(href),
    target: blank ? "_blank" : undefined,
    rel: blank ? "noreferrer" : undefined,
    onClick: internal
      ? (e: MouseEvent) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
          e.preventDefault();
          navigate(href as string);
        }
      : undefined,
  };
}

// True for what a Sidebar holds, where a link is a place to go and looks it.
export const InSidebar = createContext(false);
