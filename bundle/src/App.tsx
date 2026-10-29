import { useEffect, useState } from "react";
import { Render } from "./render";
import { useRoot } from "./store";
import { closedReason, onStatus, type Status } from "./ws";
import { Toaster } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Login, type LoginBoot } from "./login";
import { t } from "./theme";

export function App() {
  const login = (window as unknown as { __mw?: { login?: LoginBoot } }).__mw?.login;
  if (login) return <Login boot={login} />;
  return <Connected />;
}

function Connected() {
  const root = useRoot();
  const [status, setStatus] = useState<Status>("connecting");
  useEffect(() => onStatus(setStatus), []);

  const ended = status === "closed";
  return (
    <>
      {ended ? <Ended /> : null}
      {root ? (
        // A page whose session ended stays readable but takes no more input:
        // inert blocks clicks, keys and focus, and hides it from assistive tech.
        <div inert={ended || undefined}>
          <Render id={root} />
        </div>
      ) : (
        <Splash status={status} />
      )}
      {status === "reconnecting" && root ? (
        <div className="fixed bottom-3 right-3 rounded-md border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-sm">
          {t("reconnecting")}
        </div>
      ) : null}
      <Toaster />
    </>
  );
}

function Splash({ status }: { status: Status }) {
  if (status === "closed") return null;
  return <div className="flex h-dvh items-center justify-center text-sm text-muted-foreground">{t("loading")}</div>;
}

// The session is over and the tab will not reconnect on its own: the reason, and
// a reload, which starts a fresh session on the same page. In the flow above the
// page so nothing is covered, sticky so it stays in view, above any overlay.
function Ended() {
  const reason = closedReason();
  return (
    <div role="alert" className="sticky inset-x-0 top-0 z-[60] flex items-center justify-center gap-3 border-b bg-card px-4 py-2 text-sm shadow-sm">
      <span className="font-medium">{t("session_ended")}</span>
      {reason ? <span className="text-muted-foreground">{reason}</span> : null}
      <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
        {t("reload")}
      </Button>
    </div>
  );
}
