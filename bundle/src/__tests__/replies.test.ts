import { beforeEach, describe, expect, it } from "vitest";
import { feed, forgetReplies, liveReply, rest, sent } from "../replies";

const begin = (node: string, text: string) => {
  feed(node, { type: "start", messageId: "m1" });
  feed(node, { type: "text-start", id: "t" });
  feed(node, { type: "text-delta", id: "t", delta: text });
};

describe("the reply on its way to a chat", () => {
  beforeEach(() => forgetReplies());

  it("is kept for a chat that is not on the page", () => {
    begin("chat", "Half a sen");
    feed("chat", { type: "text-delta", id: "t", delta: "tence." });
    expect(liveReply("chat").message?.parts[0].text).toBe("Half a sentence.");
    expect(liveReply("other").message).toBeNull();
  });

  it("stays as it ended until the page carries it, and goes then", () => {
    begin("chat", "Done.");
    feed("chat", { type: "data-status", data: { text: "Reading" }, transient: true });
    feed("chat", { type: "data-suggestions", data: { items: ["More"] }, transient: true });
    feed("chat", { type: "finish" });
    expect(liveReply("chat")).toMatchObject({ ended: true, transient: { status: "Reading" } });
    expect(liveReply("chat").message?.parts[0].text).toBe("Done.");
    rest("chat");
    expect(liveReply("chat")).toEqual({ message: null, ended: false, transient: { status: undefined, suggestions: ["More"] } });
    // Nothing changes for a chat at rest, so nothing is drawn again.
    const same = liveReply("chat");
    rest("chat");
    expect(liveReply("chat")).toBe(same);
    sent("chat");
    expect(liveReply("chat").transient).toEqual({});
  });

  it("is made again from nothing by a reply that is said again", () => {
    begin("chat", "Half");
    feed("chat", { type: "data-status", data: { text: "Reading" }, transient: true });
    // A tab that missed some is told the reply from its start.
    begin("chat", "Half a sentence.");
    const now = liveReply("chat");
    expect(now.message?.parts).toHaveLength(1);
    expect(now.message?.parts[0].text).toBe("Half a sentence.");
    expect(now.transient.status).toBeUndefined();
    expect(now.ended).toBe(false);
  });

  it("takes the question as it ended in the place of the open one", () => {
    feed("chat", { type: "start", messageId: "m1" });
    feed("chat", { type: "data-ask", id: "q", data: { question: "Delete?", open: true, answer: null } });
    feed("chat", { type: "data-ask", id: "q", data: { question: "Delete?", open: false, answer: "yes" } });
    expect(liveReply("chat").message?.parts).toEqual([{ type: "data-ask", id: "q", data: { question: "Delete?", open: false, answer: "yes" } }]);
  });
});
