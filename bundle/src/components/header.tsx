// The app bar: the theme's logo, the title, links, the page's actions and a
// user menu with the theme choice and sign-out. Reads the theme and the
// signed-in user from the boot object; the app only says what to show.

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "cn";
import { icon } from "../icons";
import { safeUrl } from "../lib";
import { Render } from "../render";
import { t, theme, useMode, useScheme, type Mode } from "../theme";
import type { Renderer } from "../render";

interface BootUser {
  id: string;
  name: string;
  picture_url?: string | null;
}

function bootUser(): BootUser | null {
  return (window as unknown as { __mw?: { user?: BootUser | null } }).__mw?.user ?? null;
}

export function Logo({ className }: { className?: string }) {
  const scheme = useScheme();
  const logo = theme().logo;
  if (!logo) return null;
  const src = scheme === "dark" && logo.dark ? logo.dark : logo.light;
  return <img src={safeUrl(src, { image: true })} alt="" className={cn("h-8 w-auto", className)} />;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

export function UserMenu() {
  const [mode, setMode] = useMode();
  const user = bootUser();
  const Sun = icon("sun");
  const Moon = icon("moon");
  const scheme = useScheme();
  const ModeIcon = scheme === "dark" ? Moon : Sun;
  const signOut = () => {
    void fetch("/_mw/auth/logout", { method: "POST" }).finally(() => window.location.assign("/_mw/login"));
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="sm" aria-label={t("menu")} className="gap-2">
            {user ? (
              user.picture_url ? (
                <img src={safeUrl(user.picture_url, { image: true })} alt="" className="size-6 rounded-full" />
              ) : (
                <span className="flex size-6 items-center justify-center rounded-full bg-muted text-[11px] font-medium">{initials(user.name)}</span>
              )
            ) : ModeIcon ? (
              <ModeIcon />
            ) : null}
            {user ? <span className="hidden max-w-40 truncate sm:inline">{user.name}</span> : null}
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-44">
        {user ? (
          <>
            <DropdownMenuGroup>
              <DropdownMenuLabel className="truncate">{user.name}</DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
          </>
        ) : null}
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">{t("theme")}</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={mode} onValueChange={(v) => setMode(v as Mode)}>
            <DropdownMenuRadioItem value="light">{t("light")}</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark">{t("dark")}</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="system">{t("system")}</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        {user ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={signOut}>{t("sign_out")}</DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export const Header: Renderer = ({ props, children }) => {
  const links = ((props.links as { $node: string }[] | undefined) ?? []).map((s) => s.$node);
  return (
    <header
      className={cn(
        "sticky top-0 z-20 flex h-16 shrink-0 items-center gap-5 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80",
        props.cls as string,
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {props.logo !== false ? <Logo /> : null}
        {props.title ? <span className="truncate text-lg font-semibold tracking-tight">{String(props.title)}</span> : null}
      </div>
      {links.length ? (
        <nav className="hidden items-center gap-4 text-sm md:flex">
          {links.map((id) => (
            <Render key={id} id={id} />
          ))}
        </nav>
      ) : null}
      <div className="ml-auto flex items-center gap-2">
        {children}
        {props.user_menu !== false ? <UserMenu /> : null}
      </div>
    </header>
  );
};
