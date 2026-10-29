import { describe, expect, it } from "vitest";
import { slugify } from "../lib";

describe("slugify", () => {
  it("matches the server's anchor for a heading", () => {
    expect(slugify("Who owns the value")).toBe("who-owns-the-value");
    expect(slugify("RadioGroup, CheckboxGroup and ToggleGroup")).toBe("radiogroup-checkboxgroup-and-togglegroup");
    expect(slugify("  Confirm and ask ")).toBe("confirm-and-ask");
  });
});
