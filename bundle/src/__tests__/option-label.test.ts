import { createElement, Fragment } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { optionLabel } from "../components/option-label";

const html = (...args: Parameters<typeof optionLabel>) => renderToStaticMarkup(createElement(Fragment, null, optionLabel(...args)));

describe("optionLabel", () => {
  it("is the label, or the value where there is none", () => {
    expect(optionLabel({ value: "nl", label: "Dutch" })).toBe("Dutch");
    expect(optionLabel({ value: "nl" })).toBe("nl");
    expect(optionLabel({ value: "nl", label: null, icon: null })).toBe("nl");
  });

  it("puts the icon in front, at the size it was asked for", () => {
    const shown = html({ value: "ok", label: "Done", icon: "check" });
    expect(shown).toMatch(/^<svg[^>]*class="[^"]*shrink-0 size-4[^"]*"/);
    expect(shown.endsWith("</svg>Done")).toBe(true);
    expect(html({ value: "ok", icon: "check" }, "size-3")).toMatch(/class="[^"]*size-3/);
  });

  it("draws a file of the app's own as it draws one of the bundle's", () => {
    const shown = html({ value: "go", label: "Launch", icon: "/public/icons/rocket.svg" });
    expect(shown).toContain('<image href="/public/icons/rocket.svg"');
    expect(shown.endsWith("Launch")).toBe(true);
  });

  it("shows the label alone for an icon nobody knows", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(optionLabel({ value: "x", label: "X", icon: "no-such-icon" })).toBe("X");
    warn.mockRestore();
  });
});
