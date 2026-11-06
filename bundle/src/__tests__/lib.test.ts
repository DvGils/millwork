import { describe, expect, it, vi } from "vitest";
import { isInternalPath, isSameOriginPath, safeUrl, samePath, slugify, toApp, toBrowser, signOutUrl } from "../lib";

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

describe("relative links", () => {
  it("passes fragments and page-relative paths through, refusing schemes", () => {
    expect(safeUrl("#top")).toBe("#top");
    expect(safeUrl("other")).toBe("other");
    expect(safeUrl("docs/page?x=1#a")).toBe("docs/page?x=1#a");
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "../x", "a/../b", "\\evil", "//evil"]) {
      expect(safeUrl(bad)).toBe("about:blank");
    }
  });
});

describe("signOutUrl", () => {
  it("is the proxy's URL when the proxy signed the person in, else the login page", () => {
    const boot = (mw: { base?: string; user?: { sign_out?: string | null } | null }) => vi.stubGlobal("window", { __mw: mw });
    boot({ base: "/sales", user: { sign_out: "/oauth2/sign_out" } });
    expect(signOutUrl()).toBe("/oauth2/sign_out");
    boot({ base: "/sales", user: { sign_out: null } });
    expect(signOutUrl()).toBe("/sales/_mw/login");
    boot({ base: "", user: {} });
    expect(signOutUrl()).toBe("/_mw/login");
    boot({ base: "" });
    expect(signOutUrl()).toBe("/_mw/login");
    vi.unstubAllGlobals();
  });

  it("is where the app's on_logout said, under the prefix, unless a proxy signs out", () => {
    const boot = (mw: { base?: string; user?: { sign_out?: string | null } | null }) => vi.stubGlobal("window", { __mw: mw });
    boot({ base: "/sales", user: { sign_out: null } });
    expect(signOutUrl("/welcome")).toBe("/sales/welcome");
    expect(signOutUrl("https://example.com/bye")).toBe("https://example.com/bye");
    expect(signOutUrl(null)).toBe("/sales/_mw/login");
    expect(signOutUrl("javascript:alert(1)")).toBe("about:blank");
    boot({ base: "/sales", user: { sign_out: "/oauth2/sign_out" } });
    expect(signOutUrl("/welcome")).toBe("/oauth2/sign_out");
    vi.unstubAllGlobals();
  });
});

describe("samePath", () => {
  it("reads a path the same whether it is spelled as an address or as the app wrote it", () => {
    expect(samePath("/c/Jos%C3%A9%20P%C3%A9rez", "/c/José Pérez")).toBe(true);
    expect(samePath("/orders/7", "/orders/7")).toBe(true);
    expect(samePath("/orders/7", "/orders/8")).toBe(false);
    // An encoded slash is not a slash, and a spelling that does not decode is itself.
    expect(samePath("/files/a%2Fb", "/files/a/b")).toBe(false);
    expect(samePath("/x/%E0%A4%A", "/x/%E0%A4%A")).toBe(true);
  });
});
