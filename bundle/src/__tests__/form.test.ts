import { describe, expect, it } from "vitest";
import { defaults, getAt, rebase, setAt } from "../components/form";

describe("form pointers", () => {
  it("rebases list item pointers rooted at the item", () => {
    // Python emits item field pointers rooted at "" for list items.
    expect(rebase("/rows/0", "/name", "")).toBe("/rows/0/name");
    expect(rebase("/ops/1", "/source", "")).toBe("/ops/1/source");
    // A top-level union's variant fields are rooted at the union's own pointer.
    expect(rebase("/op", "/op/source", "/op")).toBe("/op/source");
  });

  it("sets nested and indexed values immutably", () => {
    const a = { ops: [{ type: "recode", source: "" }] };
    const b = setAt(a, "/ops/0/source", "q1") as typeof a;
    expect(b.ops[0].source).toBe("q1");
    expect(a.ops[0].source).toBe("");
    expect(getAt(setAt({}, "/a/0/b", 1), "/a/0/b")).toBe(1);
    expect(getAt(setAt({}, "/x~1y", 2), "/x~1y")).toBe(2);
  });

  it("builds defaults for every widget kind", () => {
    const d = defaults([
      { name: "t", pointer: "/t", label: "t", widget: "input", required: true },
      { name: "n", pointer: "/n", label: "n", widget: "input", clearable: true },
      { name: "tags", pointer: "/tags", label: "tags", widget: "checkboxes" },
      { name: "on", pointer: "/on", label: "on", widget: "switch", default: true },
      { name: "target", pointer: "/target", label: "target", widget: "fieldset", fields: [{ name: "w", pointer: "/target/w", label: "w", widget: "number", default: 1 }] },
      {
        name: "op", pointer: "/op", label: "op", widget: "union", discriminator: "type",
        variants: [{ tag: "recode", label: "Recode", fields: [{ name: "source", pointer: "/op/source", label: "s", widget: "input", required: true }] }],
      },
    ]);
    expect(d).toEqual({ t: "", n: null, tags: [], on: true, target: { w: 1 }, op: { type: "recode", source: "" } });
  });
});
