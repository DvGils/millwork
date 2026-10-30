// The login page: the app's name and image, one button per OAuth provider,
// a password form when configured, and the denial message. No app code.

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Field, FieldLabel } from "@/components/ui/field";
import { icon } from "./icons";
import { safeUrl, mw } from "./lib";
import { t, theme } from "./theme";
import { Logo } from "./components/header";

export interface LoginBoot {
  name: string;
  providers: { id: string; label: string; kind: "oauth" | "password"; icon?: string | null }[];
  intents: { id: string; label: string }[];
  next: string;
  error?: string | null;
  image?: string | null;
}

export function Login({ boot }: { boot: LoginBoot }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(boot.error ?? null);
  const [busy, setBusy] = useState(false);
  const oauth = boot.providers.filter((p) => p.kind === "oauth");
  const passwordProvider = boot.providers.find((p) => p.kind === "password");
  const next = encodeURIComponent(boot.next || "/");
  const image = boot.image ?? theme().login_image ?? null;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(mw("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (r.ok) {
        window.location.assign(safeUrl(boot.next || "/"));
        return;
      }
      const body = (await r.json().catch(() => ({}))) as { reason?: string };
      setError(body.reason ?? `${t("sign_in_failed")} (${r.status})`);
    } catch {
      setError(t("sign_in_failed"));
    } finally {
      setBusy(false);
    }
  };

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
          {oauth.length ? (
            <div className="flex flex-col gap-2">
              {oauth.map((p) => {
                const Icon = icon(p.icon);
                return (
                  <Button key={p.id} variant="outline" className="w-full" onClick={() => window.location.assign(`${mw("/auth/oauth/")}${encodeURIComponent(p.id)}?next=${next}`)}>
                    {Icon ? <Icon /> : null}
                    {t("continue_with", { provider: p.label })}
                  </Button>
                );
              })}
              {boot.intents.map((it) => (
                <Button key={it.id} variant="ghost" className="w-full" onClick={() => window.location.assign(`${mw("/auth/oauth/")}${encodeURIComponent(oauth[0].id)}?next=${next}&intent=${encodeURIComponent(it.id)}`)}>
                  {it.label}
                </Button>
              ))}
            </div>
          ) : null}
          {passwordProvider ? (
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <Field>
                <FieldLabel htmlFor="mw-user">{t("username")}</FieldLabel>
                <Input id="mw-user" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
              </Field>
              <Field>
                <FieldLabel htmlFor="mw-pass">{t("password")}</FieldLabel>
                <Input id="mw-pass" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </Field>
              <Button type="submit" disabled={busy || !username || !password}>
                {t("sign_in")}
              </Button>
            </form>
          ) : null}
          {!oauth.length && !passwordProvider ? <Label>{t("no_sign_in")}</Label> : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </div>
      </div>
    </div>
  );
}
