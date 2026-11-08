import { describe, expect, it } from "vitest";
import { needsRuntime } from "../tailwind-runtime";
import type { Node } from "../store";

const node = (id: string, type: string, props: Record<string, unknown> = {}): Node => ({ id, type, props, children: [] });

describe("needsRuntime", () => {
  it("is false for a page of catalogue components without classes of their own", () => {
    expect(needsRuntime({ a: node("a", "Page"), b: node("b", "Text", { content: "hi", cls: "" }) })).toBe(false);
  });
  it("is true for a class on any node, or a custom component", () => {
    expect(needsRuntime({ a: node("a", "Page"), b: node("b", "Stack", { cls: "max-w-3xl" }) })).toBe(true);
    expect(needsRuntime({ a: node("a", "Custom", { name: "Map" }) })).toBe(true);
  });
});
