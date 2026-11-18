import { describe, expect, it } from "vitest";
import { applyChunk, seenRunning, type UIMessage } from "../stream";

function after(...chunks: Record<string, unknown>[]): UIMessage {
  let message: UIMessage | null = null;
  for (const chunk of chunks) message = applyChunk(message, chunk as { type: string }, {});
  return message as UIMessage;
}

describe("what of a reply is seen to be under way", () => {
  const start = { type: "start", messageId: "m1" };

  it("is nothing before the reply has a part", () => {
    expect(seenRunning([], true)).toBe(false);
    expect(seenRunning(after(start).parts, true)).toBe(false);
  });

  it("is text once a word of it is there, until the text ends", () => {
    const begun = after(start, { type: "text-start", id: "t" });
    expect(seenRunning(begun.parts, true)).toBe(false);
    const written = applyChunk(begun, { type: "text-delta", id: "t", delta: "Three" }, {}) as UIMessage;
    expect(seenRunning(written.parts, true)).toBe(true);
    const ended = applyChunk(written, { type: "text-end", id: "t" }, {}) as UIMessage;
    expect(seenRunning(ended.parts, true)).toBe(false);
  });

  it("is a step that runs, where steps show", () => {
    const step = after(start, { type: "tool-input-available", toolName: "search", toolCallId: "c", input: {} });
    expect(seenRunning(step.parts, true)).toBe(true);
    expect(seenRunning(step.parts, false)).toBe(false);
    const done = applyChunk(step, { type: "tool-output-available", toolCallId: "c", output: 1 }, {}) as UIMessage;
    expect(seenRunning(done.parts, true)).toBe(false);
  });

  it("is a thought while it is thought", () => {
    const thought = after(start, { type: "reasoning-start", id: "r" });
    expect(seenRunning(thought.parts, true)).toBe(true);
    expect(seenRunning(thought.parts, false)).toBe(false);
  });
});
