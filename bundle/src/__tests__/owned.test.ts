import { describe, expect, it } from "vitest";
import { ANSWERED_WITHIN, caughtUp, type Told } from "../owned";

const key = (value: unknown) => JSON.stringify(value);
const told = (...values: [unknown, number][]): Told[] => values.map(([v, at]) => ({ key: key(v), at }));

describe("caughtUp", () => {
  it("keeps what the field shows when the server answers with what it was told", () => {
    // "one " was sent at 100, and the answer comes at 160 with "one t" typed.
    expect(caughtUp(told(["one ", 100]), key("one "), 160)).toEqual({ take: false, told: [] });
  });

  it("goes on waiting for the answers to what was told after that", () => {
    const waiting = told(["one ", 100], ["one two ", 400]);
    expect(caughtUp(waiting, key("one "), 420)).toEqual({ take: false, told: told(["one two ", 400]) });
  });

  it("takes a value the field never told the server", () => {
    // A handler cleared the field, capped a number, or cut the text short.
    expect(caughtUp(told(["fast body", 100]), key(""), 150)).toEqual({ take: true, told: [] });
    expect(caughtUp(told(["100", 100]), key("10"), 150)).toEqual({ take: true, told: [] });
    expect(caughtUp(told(["0123456789", 100]), key("01234"), 150)).toEqual({ take: true, told: [] });
  });

  it("takes a value that was typed on the way but never sent", () => {
    // "1", "10" and "100" were typed and only "100" was sent: the 10 that
    // comes back is the server's.
    expect(caughtUp(told(["100", 100]), key("10"), 150).take).toBe(true);
  });

  it("takes every value for a control that tells the server nothing here", () => {
    expect(caughtUp([], key("chosen"), 10)).toEqual({ take: true, told: [] });
  });

  it("forgets what was told when no answer came", () => {
    // The handler kept the value to itself. A button sets that very value
    // much later, and it is the server's own.
    const long = 100 + ANSWERED_WITHIN;
    expect(caughtUp(told(["ab", 100]), key("ab"), long)).toEqual({ take: true, told: [] });
    expect(caughtUp(told(["ab", 100]), key("ab"), long - 1).take).toBe(false);
  });
});
