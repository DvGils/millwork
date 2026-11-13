// What a field does with a value the server sends for it, when the person
// may have typed on in the meantime.
//
// A field shows what is typed into it at once and tells the server after a
// pause. The server's answer is that same value, on its way back while the
// typing goes on, and taking it over would wipe out every letter typed
// since. So a field remembers what it told the server. A value from the
// server that is among those is the server catching up: the field keeps
// what it shows, and forgets what it told up to there. Any other value is
// the server's own, a field cleared by a handler or a number brought back
// into its range, and the field takes it.
//
// An answer comes soon or not at all: a handler that stores the value as it
// was sends nothing back. What was told is therefore forgotten after a
// while, so that it cannot be mistaken for the answer to a value the server
// sets much later.

export interface Told {
  key: string;
  at: number;
}

// How long an answer is waited for, in milliseconds.
export const ANSWERED_WITHIN = 3000;

// `told` is what the field told the server and when, oldest first, and
// `key` the server's value, as JSON like the keys in `told`. The answer
// says whether to take the value over and what is left to remember.
export function caughtUp(told: Told[], key: string, now: number): { take: boolean; told: Told[] } {
  const waiting = told.filter((t) => now - t.at < ANSWERED_WITHIN);
  const at = waiting.map((t) => t.key).lastIndexOf(key);
  return at < 0 ? { take: true, told: [] } : { take: false, told: waiting.slice(at + 1) };
}
