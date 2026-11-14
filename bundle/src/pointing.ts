// Finding a component on the page by the id of its node, for what the
// server asks of one: the keyboard put in it.
//
// The wrapper every node is drawn in carries the node's id. It takes no
// room on the page itself, so what is acted on is inside it.

// What the keyboard can be in.
export const FOCUSABLE = "input, textarea, select, button, a[href], [tabindex]:not([tabindex='-1'])";

// Put the keyboard in a node: in the first thing inside it that takes it.
// One that is disabled or not on the screen is passed over for the next,
// so a card whose first field cannot be typed in gives it to the second.
// False when nothing in the node took it.
export function focusNode(id: string): boolean {
  const wrapper = document.querySelector(`[data-node="${CSS.escape(id)}"]`);
  const inside = wrapper ? Array.from(wrapper.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];
  for (const element of inside) {
    if (element.matches(":disabled") || element.getClientRects().length === 0) continue;
    element.focus();
    if (document.activeElement === element) return true;
  }
  return false;
}
