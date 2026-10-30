// A voice note button for a chat's composer: records with the browser, uploads
// the clip under the chat's limits and sends it as a message. `chat` arrives
// because the component sits in `Chat(tools=[...])`.
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Mic, Square } from "lucide-react";

export default function Voice({ chat }) {
  const [recorder, setRecorder] = useState(null);
  const chunks = useRef([]);
  if (!chat) return null;

  async function start() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const r = new MediaRecorder(stream);
    chunks.current = [];
    r.ondataavailable = (e) => chunks.current.push(e.data);
    r.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks.current, { type: r.mimeType || "audio/webm" });
      const file = new File([blob], "voice.webm", { type: blob.type });
      const ref = await chat.upload(file);
      chat.send("", [ref]);
    };
    r.start();
    setRecorder(r);
  }

  function stop() {
    recorder?.stop();
    setRecorder(null);
  }

  return (
    <Button
      type="button"
      size="icon-sm"
      variant={recorder ? "destructive" : "ghost"}
      aria-label={recorder ? "Stop recording" : "Record a voice note"}
      disabled={chat.busy && !recorder}
      onClick={recorder ? stop : start}
    >
      {recorder ? <Square /> : <Mic />}
    </Button>
  );
}
