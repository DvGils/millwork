// The login page: the app's name and image, the reason a sign-in was refused,
// and under them the layout the server sent, which is the app's own or every
// provider's button and the password form. No app code runs here.

import { useEffect, useState } from "react";
import { Label } from "@/components/ui/label";
import { ATTEMPT } from "./components/sign-in";
import { safeUrl } from "./lib";
import { t, theme } from "./theme";
import { Logo } from "./components/header";
import { Render } from "./render";
import { store, type Node } from "./store";

export interface LoginBoot {
  name: string;
  // The layout under the heading, as a page's nodes are.
  root: string;
  nodes: Record<string, Node>;
  // True when a proxy in front of the app does the signing in.
  proxied?: boolean;
  next: string;
  error?: string | null;
  image?: string | null;
}

let mounted = false;

export function Login({ boot }: { boot: LoginBoot }) {
  // The nodes go into the store once, before the first draw, and stay as they
  // are: no socket is open here to change them.
  if (!mounted) {
    mounted = true;
    store.mount(boot.root, boot.nodes ?? {}, null);
  }
  const image = boot.image ?? theme().login_image ?? null;
  const ways = Object.values(boot.nodes ?? {}).some((n) => n.type === "SignIn");
  // A layout with nothing in it, the page of an app that signs in elsewhere,
  // is not drawn, so it takes no room.
  const empty = !(boot.nodes?.[boot.root]?.children.length);
  // Why the last sign-in was refused, until another is tried.
  const [refused, setRefused] = useState(boot.error ?? null);
  useEffect(() => {
    const clear = () => setRefused(null);
    window.addEventListener(ATTEMPT, clear);
    return () => window.removeEventListener(ATTEMPT, clear);
  }, []);

  return (
    <div className="flex min-h-dvh">
      {image ? (
        <div className="hidden w-1/2 bg-muted md:block" style={{ backgroundImage: `url(${safeUrl(image, { image: true })})`, backgroundSize: "cover", backgroundPosition: "center" }} />
      ) : null}
      <div className="flex grow items-center justify-center p-6">
        <div className="flex w-full max-w-sm flex-col gap-6">
          <div className="flex flex-col gap-3">
            <Logo className="h-9 self-start" />
            <h1 className="text-2xl font-semibold tracking-tight">{boot.name}</h1>
            <p className="text-sm text-muted-foreground">{t("sign_in_hint")}</p>
          </div>
          {refused ? (
            <p role="alert" className="text-sm text-destructive">
              {refused}
            </p>
          ) : null}
          {empty ? null : <Render id={boot.root} />}
          {!ways ? <Label>{t(boot.proxied ? "proxy_sign_in" : "no_sign_in")}</Label> : null}
        </div>
      </div>
    </div>
  );
}
