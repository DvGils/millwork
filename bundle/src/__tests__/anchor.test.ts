import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../ws", () => ({ navigate: vi.fn() }));

import { anchorProps } from "../components/anchor";
import { navigate } from "../ws";

const boot = (mw: Record<string, unknown>) => vi.stubGlobal("window", { __mw: mw });
const click = (over: Record<string, unknown> = {}) => ({ metaKey: false, ctrlKey: false, shiftKey: false, button: 0, preventDefault: vi.fn(), ...over });

describe("anchorProps", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.mocked(navigate).mockClear();
  });

  it("opens a page of the app on the session, under the prefix, and leaves a new tab to the browser", () => {
    boot({ base: "/sales" });
    const a = anchorProps("/orders/new", "_self");
    expect(a.href).toBe("/sales/orders/new");
    expect(a.target).toBeUndefined();
    const plain = click();
    a.onClick?.(plain as never);
    expect(plain.preventDefault).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/orders/new");
    const held = click({ ctrlKey: true });
    a.onClick?.(held as never);
    expect(held.preventDefault).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("is a plain link for another site, a new tab, a framework route and the login page", () => {
    boot({ base: "" });
    expect(anchorProps("https://example.com/docs", "_blank")).toEqual({ href: "https://example.com/docs", target: "_blank", rel: "noreferrer", onClick: undefined });
    expect(anchorProps("/orders/new", "_blank").onClick).toBeUndefined();
    expect(anchorProps("/public/a.pdf", "_self").onClick).toBeUndefined();
    expect(anchorProps("javascript:alert(1)", "_self").href).toBe("about:blank");
    boot({ base: "", login: {} });
    expect(anchorProps("/orders/new", "_self").onClick).toBeUndefined();
  });
});
