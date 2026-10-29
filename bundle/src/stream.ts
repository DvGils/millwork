// The AI SDK UI message stream, parsed into message parts. millwork owns both
// ends of the wire, so this is the format as a convention, not a dependency.

export interface Part {
  type: string;
  [key: string]: unknown;
}

export interface UIMessage {
  id: string;
  role: "user" | "assistant" | "system";
  parts: Part[];
  metadata?: Record<string, unknown>;
}

export interface Chunk {
  type: string;
  [key: string]: unknown;
}

export interface Transient {
  status?: string;
  suggestions?: string[];
}

// Applies one chunk to the in-flight message. Returns the new message (never
// mutates), or null when the stream ended. Transient data parts go to `extra`.
export function applyChunk(message: UIMessage | null, chunk: Chunk, extra: Transient): UIMessage | null {
  switch (chunk.type) {
    case "start":
      return { id: String(chunk.messageId ?? ""), role: "assistant", parts: [] };
    case "finish":
      return null;
    case "start-step":
    case "finish-step":
    case "message-metadata":
      return message;
  }
  if (!message) return message;
  const parts = [...message.parts];
  const find = (pred: (p: Part) => boolean) => parts.findIndex(pred);

  switch (chunk.type) {
    case "text-start":
      parts.push({ type: "text", text: "", state: "streaming", _id: chunk.id });
      break;
    case "text-delta": {
      const i = find((p) => p.type === "text" && p._id === chunk.id);
      if (i >= 0) parts[i] = { ...parts[i], text: String(parts[i].text) + String(chunk.delta) };
      break;
    }
    case "text-end": {
      const i = find((p) => p.type === "text" && p._id === chunk.id);
      if (i >= 0) parts[i] = { ...parts[i], state: "done" };
      break;
    }
    case "reasoning-start":
      parts.push({ type: "reasoning", text: "", state: "streaming", _id: chunk.id });
      break;
    case "reasoning-delta": {
      const i = find((p) => p.type === "reasoning" && p._id === chunk.id);
      if (i >= 0) parts[i] = { ...parts[i], text: String(parts[i].text) + String(chunk.delta) };
      break;
    }
    case "reasoning-end": {
      const i = find((p) => p.type === "reasoning" && p._id === chunk.id);
      if (i >= 0) parts[i] = { ...parts[i], state: "done" };
      break;
    }
    case "tool-input-start":
      parts.push({ type: `tool-${chunk.toolName}`, toolCallId: chunk.toolCallId, state: "input-streaming", input: "" });
      break;
    case "tool-input-delta": {
      const i = find((p) => p.toolCallId === chunk.toolCallId);
      if (i >= 0) parts[i] = { ...parts[i], input: String(parts[i].input ?? "") + String(chunk.inputTextDelta ?? "") };
      break;
    }
    case "tool-input-available": {
      const i = find((p) => p.toolCallId === chunk.toolCallId);
      const part = { type: `tool-${chunk.toolName}`, toolCallId: chunk.toolCallId, state: "input-available", input: chunk.input };
      if (i >= 0) parts[i] = part;
      else parts.push(part);
      break;
    }
    case "tool-output-available": {
      const i = find((p) => p.toolCallId === chunk.toolCallId);
      if (i >= 0) parts[i] = { ...parts[i], state: "output-available", output: chunk.output };
      break;
    }
    case "tool-output-error": {
      const i = find((p) => p.toolCallId === chunk.toolCallId);
      if (i >= 0) parts[i] = { ...parts[i], state: "output-error", errorText: chunk.errorText };
      break;
    }
    case "source-url":
    case "source-document":
    case "file":
      parts.push({ ...chunk });
      break;
    case "error":
      parts.push({ type: "error", errorText: chunk.errorText });
      break;
    default:
      if (chunk.type.startsWith("data-")) {
        if (chunk.type === "data-status") {
          extra.status = String((chunk.data as { text?: string })?.text ?? "");
          return message;
        }
        if (chunk.type === "data-suggestions") {
          extra.suggestions = ((chunk.data as { items?: string[] })?.items ?? []).map(String);
          return message;
        }
        if (chunk.transient) return message;
        const part: Part = { type: chunk.type, data: chunk.data, id: chunk.id };
        const i = chunk.id ? find((p) => p.type === chunk.type && p.id === chunk.id) : -1;
        if (i >= 0) parts[i] = part;
        else parts.push(part);
      } else {
        console.warn("millwork: unknown stream chunk", chunk.type);
      }
  }
  return { ...message, parts };
}

export function messageText(m: UIMessage): string {
  return m.parts.filter((p) => p.type === "text").map((p) => String(p.text)).join("");
}
