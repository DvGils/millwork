// A scroll area that stays at its end while its content grows, until the
// reader scrolls away from the end. Back at the end, it stays there again.

import { useLayoutEffect, useRef } from "react";

// How far from the end still counts as being at the end, in px.
const END_SLACK = 12;
// How long after a wheel, touch, pointer or key in the area a scroll counts
// as the reader's own. What the page scrolls by itself never ends the
// staying, only the reader does.
const INTENT_MS = 1000;

const INTENTS = ["wheel", "touchmove", "pointerdown", "keydown"] as const;

/** Keep the viewport inside `holder` at its end. Returns what undoes it. */
export function stickToEnd(holder: HTMLElement): () => void {
  const el = holder.querySelector<HTMLElement>('[data-slot="scroll-area-viewport"]');
  if (!el) return () => {};
  let sticky = true;
  let intent = 0;
  const follow = () => {
    if (sticky) el.scrollTop = el.scrollHeight;
  };
  const scrolled = () => {
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= END_SLACK) sticky = true;
    else if (Date.now() - intent < INTENT_MS) sticky = false;
  };
  const touched = () => {
    intent = Date.now();
  };
  follow();
  // The content growing, a row that arrives or an image that loads, and the
  // area itself getting smaller, a field under it that grows.
  const sizes = new ResizeObserver(follow);
  sizes.observe(el);
  if (el.firstElementChild) sizes.observe(el.firstElementChild);
  el.addEventListener("scroll", scrolled, { passive: true });
  // On the holder, which has the scrollbar in it as well.
  for (const name of INTENTS) holder.addEventListener(name, touched, { passive: true });
  return () => {
    sizes.disconnect();
    el.removeEventListener("scroll", scrolled);
    for (const name of INTENTS) holder.removeEventListener(name, touched);
  };
}

/** A ref for the element around the viewport, which stays at its end while `on`. */
export function useStickToEnd<T extends HTMLElement>(on: boolean) {
  const holder = useRef<T>(null);
  useLayoutEffect(() => {
    if (on && holder.current) return stickToEnd(holder.current);
  }, [on]);
  return holder;
}
