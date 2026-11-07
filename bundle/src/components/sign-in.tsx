// One way to sign in, where the page puts it: an OAuth provider's button, or
// the username and password form. The login page is laid out with these, and
// a public page may hold one too.

import { useId, useState } from "react";
import type { Renderer } from "../render";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel } from "@/components/ui/field";
import { icon } from "../icons";
import { PasswordInput } from "./inputs";
import { brands } from "../brands";
import { mw, safeUrl, toApp } from "../lib";
import { t } from "../theme";

// Where a sign-in lands afterwards: the page the visitor was sent to the login
// page from, or on any other page that page, by its path as the login page
// itself is given one.
function loginBoot(): { next?: string } | undefined {
  return (window as unknown as { __mw?: { login?: { next?: string } } }).__mw?.login;
}

function nextPath(): string {
  const login = loginBoot();
  return login ? login.next || "/" : toApp(window.location.pathname);
}

// Said when a password is tried, so the login page takes down the reason an
// earlier sign-in was refused: the form shows its own.
export const ATTEMPT = "mw:sign-in";

// A provider's icon: a brand's mark, an image of the app's own, or an icon of
// the bundle's by name.
function ProviderIcon({ name }: { name: unknown }) {
  if (typeof name !== "string" || !name) return null;
  const Brand = brands[name];
  if (Brand) return <Brand />;
  if (name.startsWith("/")) return <img src={safeUrl(name, { image: true })} alt="" className="size-4" />;
  const Icon = icon(name);
  return Icon ? <Icon /> : null;
}

function PasswordForm({ label, cls }: { label: string | null; cls?: string }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A page may hold the form more than once, and each labels its own fields.
  const id = useId();

  const submit = async () => {
    setBusy(true);
    setError(null);
    window.dispatchEvent(new Event(ATTEMPT));
    try {
      const r = await fetch(mw("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (r.ok) {
        // On the login page the visitor goes where they were headed. Anywhere
        // else they are already there, and the page is loaded again signed in.
        if (loginBoot()) window.location.assign(safeUrl(nextPath()));
        else window.location.reload();
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
    <form
      className={cn("flex flex-col gap-3", cls)}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <Field>
        <FieldLabel htmlFor={`${id}user`}>{t("username")}</FieldLabel>
        <Input id={`${id}user`} name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
      </Field>
      <Field>
        <FieldLabel htmlFor={`${id}pass`}>{t("password")}</FieldLabel>
        <PasswordInput id={`${id}pass`} name="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <Button type="submit" disabled={busy || !username || !password}>
        {label ?? t("sign_in")}
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}

export const SignIn: Renderer = ({ props }) => {
  const label = typeof props.label === "string" && props.label ? props.label : null;
  if (props.kind === "password") return <PasswordForm label={label} cls={props.cls as string} />;
  const intent = typeof props.intent === "string" && props.intent ? props.intent : null;
  const go = () => {
    const query = `next=${encodeURIComponent(nextPath())}${intent ? `&intent=${encodeURIComponent(intent)}` : ""}`;
    window.location.assign(`${mw("/auth/oauth/")}${encodeURIComponent(String(props.provider))}?${query}`);
  };
  // An intent is another way through the same provider, so it is the quieter button.
  return (
    <Button variant={intent ? "ghost" : "outline"} className={cn("w-full", props.cls as string)} onClick={go}>
      {intent ? null : <ProviderIcon name={props.icon} />}
      {label ?? t("continue_with", { provider: String(props.name ?? "") })}
    </Button>
  );
};
