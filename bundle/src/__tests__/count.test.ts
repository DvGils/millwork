import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { Count, limitOf } from "../components/inputs";

const drawn = (length: number, max?: number) => Count({ length, max }) as ReactElement<Record<string, unknown>>;

describe("Count", () => {
  it("shows the count against the limit, or alone without one", () => {
    expect(drawn(12, 200).props.children).toBe("12 / 200");
    expect(drawn(12).props.children).toBe(12);
    expect(drawn(0, 0).props.children).toBe("0 / 0");
  });

  it("changes color exactly when the field is full", () => {
    expect(drawn(19, 20).props.className).toContain("text-muted-foreground");
    expect(drawn(19, 20).props["data-full"]).toBeUndefined();
    expect(drawn(20, 20).props.className).toContain("text-destructive");
    expect(drawn(20, 20).props["data-full"]).toBe(true);
    // What Python set past the limit is over it, and says so.
    expect(drawn(25, 20).props.className).toContain("text-destructive");
    expect(drawn(1000).props.className).toContain("text-muted-foreground");
  });
});

describe("limitOf", () => {
  it("is the limit a field can have, and nothing else", () => {
    expect(limitOf(200)).toBe(200);
    expect(limitOf(0)).toBe(0);
    for (const odd of [-1, 1.5, NaN, Infinity, null, undefined, "20", {}]) expect(limitOf(odd), String(odd)).toBeUndefined();
  });
});
