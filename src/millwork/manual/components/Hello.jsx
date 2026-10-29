// The manual's custom component: props and emit arrive as React props; local state is its own.
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sparkles } from "lucide-react";

export default function Hello({ props, emit, children }) {
  const [clicks, setClicks] = useState(0);
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-dashed border-primary/40 p-4">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-primary" />
        <span className="font-medium">Hello, {props.who}.</span>
        <Badge variant="secondary">server says {props.count}</Badge>
        <Badge variant="outline">local clicks {clicks}</Badge>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => setClicks((c) => c + 1)}>Local +1</Button>
        <Button size="sm" onClick={() => emit("wave", clicks)}>Wave to the server</Button>
      </div>
      {children}
    </div>
  );
}
