// What a component placed in a chat's composer may do: upload a file under
// the chat's limits, send a message, and know whether a reply is running.
// A custom component receives it as its `chat` prop; outside a composer the
// context is null and the prop is absent.

import { createContext } from "react";

export interface ChatFile {
  id: string;
  name: string;
  size: number;
  mime: string;
}

export interface ChatApi {
  upload: (file: File) => Promise<ChatFile>;
  send: (text: string, files?: ChatFile[]) => void;
  busy: boolean;
}

export const ChatContext = createContext<ChatApi | null>(null);
