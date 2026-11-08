// Where a page scrolls, and where it stands when it is left.
//
// The shell is viewport-high and its body is the scroller; a page without a
// shell scrolls the window. A new page opens at the top. The position of a
// page being left is kept in its history entry, so that going back lands where
// the reader was.

function scroller(): Element | null {
  return document.querySelector(".mw-shell-body");
}

export function scrollPosition(): number {
  const el = scroller();
  return el ? el.scrollTop : window.scrollY;
}

export function keepScrollInHistory() {
  const state = (window.history.state ?? {}) as Record<string, unknown>;
  window.history.replaceState({ ...state, mw: true, scroll: scrollPosition() }, "");
}

export function scrollFromHistory(): number {
  const state = window.history.state as { scroll?: unknown } | null;
  return typeof state?.scroll === "number" ? state.scroll : 0;
}

// Scroll anchoring would move the position again as the new page is laid out
// under it, so it is off until that has been drawn.
function settle(el: HTMLElement, y: number) {
  el.style.overflowAnchor = "none";
  el.scrollTop = y;
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      el.style.overflowAnchor = "";
    });
  });
}

// A position is restored once the page is tall enough to hold it: a lazily
// loaded part may still be on its way. The top needs no waiting and is taken
// at once, on the element the new page reuses, so nothing is drawn below it
// first. Any other position is tried after the new page has been drawn, and
// the wait stops when the reader scrolls away from where the restore put
// them, or when a newer restore has begun.
let restoring = 0;
export function restoreScroll(y: number) {
  const mine = ++restoring;
  if (y === 0) {
    const el = scroller();
    if (el) settle(el as HTMLElement, 0);
    else window.scrollTo(0, 0);
    return;
  }
  window.setTimeout(() => attempt(y, mine, null, 15), 0);
}

function attempt(y: number, mine: number, placed: number | null, tries: number) {
  if (mine !== restoring) return;
  const el = scroller();
  if (!el) {
    window.scrollTo(0, y);
    return;
  }
  if (placed !== null && el.scrollTop !== placed) return;
  if (el.scrollHeight >= y + el.clientHeight || tries === 0) {
    settle(el as HTMLElement, y);
    return;
  }
  let now = placed;
  if (placed === null) {
    settle(el as HTMLElement, y);
    now = el.scrollTop;
  }
  window.setTimeout(() => attempt(y, mine, now, tries - 1), 100);
}

// The position is saved a moment after each scroll, so a history entry
// left through the back or forward button is up to date as well.
let saving = 0;
export function watchScroll() {
  document.addEventListener(
    "scroll",
    () => {
      window.clearTimeout(saving);
      saving = window.setTimeout(keepScrollInHistory, 200);
    },
    { capture: true, passive: true },
  );
}
