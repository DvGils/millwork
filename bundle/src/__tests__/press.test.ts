import { describe, expect, it } from "vitest";
import { ownPress } from "../press";

// As much of an element as the rule reads: its parent and what it matches.
class El {
  matches: boolean;
  parent: El | null;
  constructor(matches = false, parent: El | null = null) {
    this.matches = matches;
    this.parent = parent;
  }
  contains(other: El | null): boolean {
    for (let e = other; e; e = e.parent) if (e === this) return true;
    return false;
  }
  closest(): El | null {
    for (let e: El | null = this; e; e = e.parent) if (e.matches) return e;
    return null;
  }
}
const press = (target: El, currentTarget: El) => ownPress({ target, currentTarget } as unknown as Parameters<typeof ownPress>[0]);

describe("whose press it is", () => {
  it("is the card's on its own ground", () => {
    const card = new El(true);
    expect(press(new El(false, card), card)).toBe(true);
    expect(press(card, card)).toBe(true);
  });
  it("is the control's on a control inside the card", () => {
    const card = new El(true);
    const box = new El(true, card);
    expect(press(box, card)).toBe(false);
    expect(press(new El(false, box), card)).toBe(false);
  });
  it("is the card's when the control is around it", () => {
    const label = new El(true);
    const card = new El(false, label);
    expect(press(new El(false, card), card)).toBe(true);
  });
  it("is not the card's from a dialog that is elsewhere on the page", () => {
    const card = new El(true);
    expect(press(new El(false, new El()), card)).toBe(false);
  });
});
