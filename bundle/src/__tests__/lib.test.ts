import { describe, expect, it } from "vitest";
import { isInternalPath, isSameOriginPath, safeUrl, slugify, toApp, toBrowser } from "../lib";

describe("slugify", () => {
  it("matches the server's anchor for a heading", () => {
    expect(slugify("Who owns the value")).toBe("who-owns-the-value");
    expect(slugify("RadioGroup, CheckboxGroup and ToggleGroup")).toBe("radiogroup-checkboxgroup-and-togglegroup");
    expect(slugify("  Confirm and ask ")).toBe("confirm-and-ask");
  });
});

describe("paths under a prefix", () => {
  it("maps app paths to browser paths and back", () => {
    expect(toBrowser("/", "/sales")).toBe("/sales/");
    expect(toBrowser("/reports/3", "/sales")).toBe("/sales/reports/3");
    expect(toBrowser("/reports/3", "")).toBe("/reports/3");
    expect(toBrowser("https://x.example/", "/sales")).toBe("https://x.example/");
    expect(toBrowser("about:blank", "/sales")).toBe("about:blank");
    expect(toBrowser("//evil.example", "/sales")).toBe("//evil.example");
    expect(toApp("/sales", "/sales")).toBe("/");
    expect(toApp("/sales/", "/sales")).toBe("/");
    expect(toApp("/sales/reports/3", "/sales")).toBe("/reports/3");
    expect(toApp("/salesfoo", "/sales")).toBe("/salesfoo");
    expect(toApp("/reports/3", "")).toBe("/reports/3");
  });
});

describe("same-origin paths", () => {
  it("refuses dot segments in every spelling", () => {
    for (const bad of ["/../x", "/a/../x", "/./_mw/login", "/%2e%2e/x", "/%2E/x", "/a/%2e%2e", "//evil", "/\\evil", "/%zz/x"]) {
      expect(isSameOriginPath(bad)).toBe(false);
      expect(safeUrl(bad)).toBe("about:blank");
    }
    expect(isSameOriginPath("/a.b/c..d/.hidden")).toBe(true);
    expect(isInternalPath("/_mw/login")).toBe(false);
    expect(isInternalPath("/_mw")).toBe(false);
    expect(isInternalPath("/public/x.pdf")).toBe(false);
    expect(isInternalPath("/publication")).toBe(true);
  });
});
