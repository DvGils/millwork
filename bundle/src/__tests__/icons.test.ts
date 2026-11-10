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

  it("draws a file under public/ by its path, as the same component each time", () => {
    const rocket = icon("/public/icons/rocket.svg");
    expect(rocket).not.toBeNull();
    expect(icon("/public/icons/rocket.svg")).toBe(rocket);
    expect(icon("/public/logo.PNG")).not.toBeNull();
    expect(icon("/public/a/b/c-d_e.1.webp")).not.toBeNull();
  });

  it("refuses a path that is not a file under public/", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const refused = [
      "/public/../secret.svg",
      "/public/a/../b.svg",
      "/public/.hidden.svg",
      "/elsewhere/x.svg",
      "//evil.example/x.svg",
      "/public/x.svg?v=1",
      "/public/x.svg#a",
      "/public/x%2e.svg",
      "/public\\x.svg",
      '/public/x").svg',
      "/public/x.svg\n",
      "/public/notes.txt",
      "/public/" + "a".repeat(200) + ".svg",
    ];
    for (const path of refused) expect(icon(path), path).toBeNull();
    expect(warn).toHaveBeenCalledTimes(refused.length);
    warn.mockRestore();
  });

  it("warns once per unknown name and returns null", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(icon("no-such-icon")).toBeNull();
    expect(warn).toHaveBeenCalledWith('millwork: unknown icon "no-such-icon"');
    warn.mockRestore();
  });
});
