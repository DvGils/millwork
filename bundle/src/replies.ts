// The reply that is on its way to each chat, as far as it has come. It is
// kept here and not in the chat's component, so a chat that leaves the page
// and comes back, or is drawn again, still has it.

import { useSyncExternalStore } from "react";
import { applyChunk, type Chunk, type Transient, type UIMessage } from "./stream";

export interface Live {
  message: UIMessage | null;
  transient: Transient;
  // The reply has come to its end, though its handler may go on for a
  // while: the answer is there and nothing more is on its way.
  ended: boolean;
}

const NONE: Live = { message: null, transient: {}, ended: false };
const live = new Map<string, Live>();
const watchers = new Map<string, Set<() => void>>();

function put(node: string, next: Live) {
  live.set(node, next);
  watchers.get(node)?.forEach((w) => w());
}

export function liveReply(node: string): Live {
  return live.get(node) ?? NONE;
}

// One chunk of a reply to the chat `node`, whether that chat is on the page
// or not.
export function feed(node: string, chunk: Chunk) {
  const now = liveReply(node);
  const transient: Transient = { ...now.transient };
  // A reply that starts has said nothing yet of what it is doing.
  if (chunk.type === "start") transient.status = undefined;
  const applied = applyChunk(now.message, chunk, transient);
  // On finish the message stays until the server's props carry it.
  const finished = chunk.type === "finish";
  put(node, { message: finished ? now.message : applied, transient, ended: chunk.type === "start" ? false : finished || now.ended });
}

// The server says the turn is over, and its props carry the message: the
// copy from the stream goes. What the reply suggested stays.
export function rest(node: string) {
  const now = live.get(node);
  if (!now || (now.message === null && !now.ended && now.transient.status === undefined)) return;
  put(node, { message: null, transient: { ...now.transient, status: undefined }, ended: false });
}

// A message was sent: what the last reply suggested is gone with it.
export function sent(node: string) {
  if (live.has(node)) put(node, NONE);
}

// Another session: its replies are not this one's.
export function forgetReplies() {
  const nodes = [...live.keys()];
  live.clear();
  for (const node of nodes) watchers.get(node)?.forEach((w) => w());
}

export function useLiveReply(node: string): Live {
  return useSyncExternalStore(
    (watch) => {
      let set = watchers.get(node);
      if (!set) {
        set = new Set();
        watchers.set(node, set);
      }
      set.add(watch);
      return () => {
        set!.delete(watch);
        if (set!.size === 0) watchers.delete(node);
      };
    },
    () => liveReply(node),
  );
}
