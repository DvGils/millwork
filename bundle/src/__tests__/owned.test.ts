import { describe, expect, it } from "vitest";
import { ANSWERED_WITHIN, answerDue, caughtUp, type Told } from "../owned";

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

describe("answerDue", () => {
  it("is not due for the value the server sent last", () => {
    expect(answerDue([], key("abc"), key("abc"), 10)).toBe(false);
    expect(answerDue([], key("abc"), key("abcd"), 10)).toBe(true);
  });

  it("goes by what the server was told since, not by what it sent last", () => {
    // The field told its text and is emptied at once, as on Enter. The
    // server's last value was the empty one, and it is about to hold the
    // text: the empty value it is told next is answered.
    expect(answerDue(told(["4006381333931", 100]), key(""), key(""), 101)).toBe(true);
    // Told the same twice in a row, it answers once.
    expect(answerDue(told(["abc", 100]), key(""), key("abc"), 101)).toBe(false);
  });

  it("forgets what was told when no answer came", () => {
    const long = 100 + ANSWERED_WITHIN;
    expect(answerDue(told(["abc", 100]), key(""), key(""), long)).toBe(false);
    expect(answerDue(told(["abc", 100]), key(""), key("abc"), long)).toBe(true);
  });

  it("makes the two values of an entry and its clearing both remembered", () => {
    const first = answerDue([], key(""), key("4006381333931"), 100);
    const waiting = told(["4006381333931", 100]);
    const second = answerDue(waiting, key(""), key(""), 100);
    expect([first, second]).toEqual([true, true]);
    // The server answers with the text and then with the empty value, and
    // the field keeps what was typed since through both.
    const afterText = caughtUp([...waiting, ...told(["", 100])], key("4006381333931"), 220);
    expect(afterText).toEqual({ take: false, told: told(["", 100]) });
    expect(caughtUp(afterText.told, key(""), 280)).toEqual({ take: false, told: [] });
  });
});
