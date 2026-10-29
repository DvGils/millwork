import { useEffect, useState } from "react";
import { Render } from "./render";
import { useRoot } from "./store";
import { onStatus, type Status } from "./ws";
import { Toaster } from "@/components/ui/toast";
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

  return (
    <>
      {root ? <Render id={root} /> : <Splash status={status} />}
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
  return (
    <div className="flex h-dvh items-center justify-center text-sm text-muted-foreground">
      {status === "closed" ? t("disconnected") : t("loading")}
    </div>
  );
}
