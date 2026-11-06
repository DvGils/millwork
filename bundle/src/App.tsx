import { useEffect, useState } from "react";
import { Render } from "./render";
import { useRoot } from "./store";
import { closedReason, onStatus, type Status } from "./ws";
import { Toaster } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Login, type LoginBoot } from "./login";
import { Logo } from "./components/header";
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
  // Ended before anything was shown: the reason is the page, in the login
  // page's frame, rather than a banner over an empty screen.
  if (ended && !root) return <EndedPage />;
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
        <div className="fixed bottom-3 right-3 rounded-md border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-sm print:hidden">
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
function EndedPage() {
  const reason = closedReason();
  return (
    <div role="alert" className="flex min-h-dvh items-center justify-center p-6">
      <div className="flex w-full max-w-sm flex-col gap-3">
        <Logo className="h-9 self-start" />
        <h1 className="text-2xl font-semibold tracking-tight">{t("session_ended")}</h1>
        {reason ? <p className="text-sm text-muted-foreground">{reason}</p> : null}
        <div>
          <Button variant="outline" onClick={() => window.location.reload()}>
            {t("reload")}
          </Button>
        </div>
      </div>
    </div>
  );
}

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
