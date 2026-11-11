// A press on something that is not a button: a card, an image, a table row.
import type React from "react";

// What takes a press of its own. One on any of these, inside the thing that is
// pressed, is not a press on that thing. The first lines are what a browser
// and ARIA know as a control. `data-press` is how anything else says so where
// it is drawn: a slider's track, a scrollbar, a row that is itself pressed.
const CONTROLS = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "label",
  "summary",
  "[contenteditable]",
  "[role=button]",
  "[role=checkbox]",
  "[role=switch]",
  "[role=radio]",
  "[role=tab]",
  "[role=menuitem]",
  "[role=option]",
  "[role=combobox]",
  "[role=slider]",
  "[role=link]",
  "[data-press]",
].join(", ");

// Where the pointer went down for the click that is on its way, if a pointer
// made it. A press starts there: one that starts on a control and ends
// beside it, as a selection dragged out of a field does, is not a press on
// what holds the control.
let began: EventTarget | null = null;
if (typeof document !== "undefined") {
  document.addEventListener("pointerdown", (e) => (began = e.target), true);
  document.addEventListener("click", () => (began = null));
}

interface Pressed {
  target: EventTarget | null;
  currentTarget: EventTarget | null;
}

// Whether `target` is, or is inside, a control that sits inside `here`.
export function onControl(target: EventTarget | null, here: EventTarget | null): boolean {
  const control = (target as Element).closest(CONTROLS);
  return Boolean(control) && control !== here && (here as Element).contains(control);
}

// Whether the event is `currentTarget`'s own. A press in a dialog or a menu
// declared inside it reaches it through React while it is nowhere inside it
// on the page, and is not its own either.
export function ownPress(e: Pressed): boolean {
  const here = e.currentTarget as Element;
  if (!here.contains(e.target as Element) || onControl(e.target, here)) return false;
  if (began && (!here.contains(began as Element) || onControl(began, here))) return false;
  // A click that ends a drag over text has selected it, and is no press.
  const selection = typeof window === "undefined" ? null : window.getSelection();
  return !selection || selection.isCollapsed || !here.contains(selection.anchorNode);
}

export const pressLook = "cursor-pointer outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// The props that make an element pressable by pointer and by keyboard: it takes
// focus, says it is a button, and answers Enter and Space as one does. A key
// held down is one press.
export function pressable(press: () => void) {
  return {
    role: "button",
    tabIndex: 0,
    onClick: (e: React.MouseEvent) => {
      if (ownPress(e)) press();
    },
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.target !== e.currentTarget || (e.key !== "Enter" && e.key !== " ")) return;
      e.preventDefault();
      if (!e.repeat) press();
    },
  };
}
