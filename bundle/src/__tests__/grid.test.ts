import { describe, expect, it } from "vitest";
import { gridColumns } from "../components/surfaces";

describe("gridColumns", () => {
  it("says every width itself, so a grid inside a grid takes nothing from it", () => {
    expect(gridColumns({ sm: 2, md: 4 })).toEqual({ "--mw-cols": 2, "--mw-cols-md": 4, "--mw-cols-lg": "initial", "--mw-cols-xl": "initial" });
    expect(gridColumns({ sm: 1, lg: 3 })).toEqual({ "--mw-cols": 1, "--mw-cols-md": "initial", "--mw-cols-lg": 3, "--mw-cols-xl": "initial" });
    expect(gridColumns(3)).toEqual({ "--mw-cols": 3, "--mw-cols-md": "initial", "--mw-cols-lg": "initial", "--mw-cols-xl": "initial" });
    expect(gridColumns(undefined)).toEqual({ "--mw-cols": 2, "--mw-cols-md": "initial", "--mw-cols-lg": "initial", "--mw-cols-xl": "initial" });
    expect(gridColumns({ md: 2 })["--mw-cols"]).toBe(1);
  });
});
