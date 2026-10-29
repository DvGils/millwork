import { describe, expect, it, vi } from "vitest";
import { icon } from "../icons";

describe("icon", () => {
  it("resolves lucide's kebab names, digits included", () => {
    expect(icon("file-text")).not.toBeNull();
    expect(icon("trash-2")).not.toBeNull();
    expect(icon("check-circle-2")).not.toBeNull();
    expect(icon("bar-chart-3")).toBe(icon("BarChart3"));
    expect(icon("trash2")).toBe(icon("trash-2"));
  });

  it("warns once per unknown name and returns null", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(icon("no-such-icon")).toBeNull();
    expect(warn).toHaveBeenCalledWith('millwork: unknown icon "no-such-icon"');
    warn.mockRestore();
  });
});
