import { describe, expect, it } from "vitest";
import { typedOption } from "../components/typed-option";

const options = [{ value: "city", label: "City" }, { value: "beach" }];

describe("the row for typed text", () => {
  it("offers text that names no option", () => {
    expect(typedOption(options, " ci ", null)).toEqual({ value: "ci", label: "ci", typed: true });
  });
  it("offers nothing for an option's value or label, or for no text", () => {
    expect(typedOption(options, "city", null)).toBeNull();
    expect(typedOption(options, "City", null)).toBeNull();
    expect(typedOption(options, "beach", null)).toBeNull();
    expect(typedOption(options, "  ", null)).toBeNull();
  });
  it("offers nothing for the name or the value of a chosen option that is not listed", () => {
    expect(typedOption(options, "Dunes", { value: "d", label: "Dunes" })).toBeNull();
    expect(typedOption(options, "d", { value: "d", label: "Dunes" })).toBeNull();
  });
  it("keeps the row of text that was typed and chosen", () => {
    expect(typedOption(options, "dunes", { value: "dunes", label: "dunes" })).toEqual({ value: "dunes", label: "dunes", typed: true });
    expect(typedOption(options, "dune", { value: "dunes" })).not.toBeNull();
  });
});
