import { beforeEach, describe, expect, it, vi } from "vitest";

const navigated: string[] = [];
vi.mock("../ws", () => ({ navigate: (p: string) => navigated.push(p) }));
vi.mock("../lib", async (orig) => ({ ...(await orig<typeof import("../lib")>()), hasSession: () => true }));

beforeEach(() => {
  (globalThis as any).window = { __mw: { base: "/manual" } };
  navigated.length = 0;
});

describe("markdown links under a path prefix", () => {
  it("maps an app path once and opens it on the session", async () => {
    const { linkProps, transformUrl } = await import("../components/markdown");
    expect(transformUrl("/pages/foo", "a")).toBe("/pages/foo");
    expect(transformUrl("/public/pic.png", "img")).toBe("/manual/public/pic.png");
    const props = linkProps("/pages/foo");
    expect(props.href).toBe("/manual/pages/foo");
    expect(props.target).toBeUndefined();
    props.onClick!({ button: 0, preventDefault() {} } as any);
    expect(navigated).toEqual(["/pages/foo"]);
  });

  it("keeps a heading link on the page and sends the rest to a new tab", async () => {
    const { linkProps } = await import("../components/markdown");
    expect(linkProps("#stat")).toMatchObject({ href: "#stat", target: undefined });
    expect(linkProps("https://example.org")).toMatchObject({ href: "https://example.org", target: "_blank" });
    expect(linkProps("mailto:a@b.c").target).toBe("_blank");
    expect(linkProps("javascript:alert(1)").href).toBe("about:blank");
  });
});
