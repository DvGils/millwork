import { afterEach, describe, expect, it } from "vitest";
import { asDate } from "../format";

// The zone the tests run in is the process's, which Node reads at each date.
const env = (globalThis as any).process.env as Record<string, string | undefined>;
const zone = env.TZ;

afterEach(() => {
  if (zone === undefined) delete env.TZ;
  else env.TZ = zone;
});

describe("asDate", () => {
  it("reads a day without a time as that day, west and east of UTC", () => {
    for (const tz of ["America/Lima", "Asia/Tokyo", "UTC"]) {
      env.TZ = tz;
      const day = asDate("2026-01-02");
      expect([day.getFullYear(), day.getMonth(), day.getDate()]).toEqual([2026, 0, 2]);
    }
  });

  it("reads a time with its offset as that moment", () => {
    env.TZ = "America/Lima";
    expect(asDate("2026-01-02T12:00:00Z").toISOString()).toBe("2026-01-02T12:00:00.000Z");
    expect(asDate("2026-01-02T21:00:00+09:00").toISOString()).toBe("2026-01-02T12:00:00.000Z");
    expect(asDate("2026-01-02T12:00:00Z").getHours()).toBe(7);
  });

  it("leaves what is no date for the caller to see", () => {
    expect(Number.isNaN(asDate("soon").getTime())).toBe(true);
    expect(Number.isNaN(asDate(null).getTime())).toBe(true);
  });
});
