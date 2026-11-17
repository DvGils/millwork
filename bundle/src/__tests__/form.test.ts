import { describe, expect, it } from "vitest";
import { defaults, getAt, rebase, setAt } from "../components/form";

describe("form pointers", () => {
  it("places a field at its parent's place plus what its pointer adds", () => {
    // A field of a row has the list's pointer without an index.
    expect(rebase("/rows/0", "/rows/name", "/rows")).toBe("/rows/0/name");
    expect(rebase("/ops/1", "/ops/source", "/ops")).toBe("/ops/1/source");
    // So has a list inside a row, and a field of its rows.
    expect(rebase("/rows/0", "/rows/tags", "/rows")).toBe("/rows/0/tags");
    expect(rebase("/rows/0/tags/2", "/rows/tags/name", "/rows/tags")).toBe("/rows/0/tags/2/name");
    // The fields of a union's variant are under the union's own pointer.
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
