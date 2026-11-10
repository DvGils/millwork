import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { icon } from "../icons";

const markup = (path: string, className?: string) => renderToStaticMarkup(createElement(icon(path)!, { className }));

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

  it("draws an SVG file as the mask of a square in the text's color, in either case of its ending", () => {
    for (const path of ["/public/icons/drawn.svg", "/public/icons/drawn.SVG"]) {
      const html = markup(path, "size-4");
      expect(html).toMatch(/^<svg data-slot="file-icon" aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" class="size-4">/);
      const id = /<mask id="(mw-icon-[A-Za-z0-9]+)" style="mask-type:alpha">/.exec(html)?.[1];
      expect(id).toBeTruthy();
      expect(html).toContain(`<image href="${path}" width="24" height="24"></image></mask>`);
      expect(html).toContain(`<rect width="24" height="24" fill="currentColor" mask="url(#${id})"></rect>`);
      // Nothing of the file is in the page: the image, the square, and no more.
      expect(html.match(/<[a-z]+/g)).toEqual(["<svg", "<mask", "<image", "<rect"]);
    }
  });

  it("draws any other image as it is", () => {
    const html = markup("/public/icons/tile.png", "size-4");
    expect(html).toBe(
      '<svg data-slot="file-icon" aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" class="size-4">' +
        '<image href="/public/icons/tile.png" width="24" height="24"></image></svg>',
    );
  });

  it("gives two icons of one file a mask each", () => {
    const Drawn = icon("/public/icons/twice.svg")!;
    const html = renderToStaticMarkup(createElement("div", null, createElement(Drawn), createElement(Drawn)));
    const ids = [...html.matchAll(/<mask id="([^"]+)"/g)].map((m) => m[1]);
    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
  });

  it("asks for the file under the app's prefix", () => {
    vi.stubGlobal("window", { __mw: { base: "/sales" } });
    expect(markup("/public/icons/prefixed.svg")).toContain('<image href="/sales/public/icons/prefixed.svg"');
    vi.unstubAllGlobals();
  });

  it("takes a path of two hundred characters and no longer", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(icon("/public/" + "a".repeat(188) + ".svg")).not.toBeNull();
    expect(icon("/public/" + "a".repeat(189) + ".svg")).toBeNull();
    warn.mockRestore();
  });

  it("takes no name that every object has", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const name of ["constructor", "valueOf", "hasOwnProperty", "toString", "__proto__"]) expect(icon(name), name).toBeNull();
    warn.mockRestore();
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
      "/public/x.gif",
      "/public/" + "a".repeat(200) + ".svg",
      "/PUBLIC/x.svg",
      "/Public/x.svg",
      "/x/public/y.svg",
      "/public//x.svg",
      "/public/x y.svg",
      "/public/x'y.svg",
      "/public/x(y.svg",
      "/public/x\\y.svg",
      "/publ\u0131c/x.svg",
      "/public/x.\u017fvg",
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
