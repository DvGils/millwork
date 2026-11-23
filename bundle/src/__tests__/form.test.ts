import { describe, expect, it } from "vitest";
import { carried, defaults, getAt, rebase, setAt } from "../components/form";

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

describe("a row that becomes another variant", () => {
  const title = { name: "title", pointer: "/item/title", label: "Name", widget: "input" };
  const weight = { name: "weight", pointer: "/item/weight", label: "Weight", widget: "number", integer: true, default: 1 };
  const counted = {
    tag: "counted", label: "Counted", unseen: ["id", "source"],
    fields: [
      title, weight,
      { name: "goal", pointer: "/item/goal", label: "Goal", widget: "number", default: 100 },
      { name: "unit", pointer: "/item/unit", label: "Unit", widget: "select", options: [{ value: "eur", label: "Euro" }, { value: "pct", label: "Percent" }] },
      { name: "version", pointer: "/item/version", label: "Version", widget: "hidden", default: 1, fixed: true },
      { name: "ref", pointer: "/item/ref", label: "Ref", widget: "hidden" },
      { name: "notes", pointer: "/item/notes", label: "Notes", widget: "list", item: { name: "notes", pointer: "/item/notes", label: "", widget: "fieldset", fields: [] } },
    ],
  };
  const reached = {
    tag: "reached", label: "Reached", unseen: ["id"],
    fields: [
      title,
      { ...weight, integer: false },
      { name: "goal", pointer: "/item/goal", label: "Goal", widget: "input" },
      { name: "unit", pointer: "/item/unit", label: "Unit", widget: "select", options: [{ value: "eur", label: "Euro" }] },
      { name: "version", pointer: "/item/version", label: "Version", widget: "hidden", default: 2, fixed: true },
      { name: "ref", pointer: "/item/ref", label: "Ref", widget: "hidden" },
      { name: "notes", pointer: "/item/notes", label: "Notes", widget: "list", item: { name: "notes", pointer: "/item/notes", label: "", widget: "fieldset", fields: [] } },
      { name: "done", pointer: "/item/done", label: "Done", widget: "switch" },
    ],
  };
  const row = { kind: "counted", id: 7, source: "import", title: "Typed by hand", weight: 3, goal: 250, unit: "pct", version: 1, ref: "r-7", notes: [{}] };

  it("keeps what both variants show in the same way, and what both hold unseen", () => {
    expect(carried(counted, reached, row)).toEqual({ id: 7, title: "Typed by hand", ref: "r-7", notes: [{}] });
  });

  it("keeps a choice the other variant has too", () => {
    expect(carried(counted, reached, { ...row, unit: "eur" }).unit).toBe("eur");
    expect(carried(reached, counted, { kind: "reached", unit: "eur", done: true })).toEqual({ unit: "eur" });
  });

  it("leaves an empty field to the other variant's default", () => {
    expect(carried(counted, reached, { ...row, title: null }).title).toBeUndefined();
  });

  it("has nothing to keep for a row that was empty", () => {
    expect(carried(undefined, reached, row)).toEqual({});
    expect(carried(counted, reached, null)).toEqual({});
  });
});
