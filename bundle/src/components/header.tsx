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
import { isInternalPath, mw, safeUrl, signOutUrl } from "../lib";
import { Render } from "../render";
import { useNode } from "../store";
import { navigate } from "../ws";
import { t, theme, useMode, useScheme, type Mode } from "../theme";
import type { Renderer } from "../render";

interface BootUser {
  id: string;
  name: string;
  picture_url?: string | null;
  // Present when a proxy signed the person in: its sign-out URL, or null when
  // it has none and the menu offers no sign-out. Absent for millwork's own login.
  sign_out?: string | null;
}

function bootUser(): BootUser | null {
  return (window as unknown as { __mw?: { user?: BootUser | null } }).__mw?.user ?? null;
}

// The catalogue's Logo node: the theme's logo on a page of the app's own, such
// as an error page, outside the app bar.
export const LogoNode: Renderer = ({ props }) => <Logo className={props.cls as string | undefined} />;

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

// A header link as a menu item, for the narrow screen where the nav is hidden:
// the same destination and the same in-app navigation as the link itself.
function MenuLink({ id }: { id: string }) {
  const node = useNode(id);
  if (!node) return null;
  const p = node.props;
  const href = safeUrl(p.href);
  const Icon = icon(p.icon);
  const internal = isInternalPath(p.href) && p.target !== "_blank";
  const go = () => {
    if (internal) navigate(p.href as string);
    else if (p.target === "_blank") window.open(href, "_blank", "noreferrer");
    else window.location.assign(href);
  };
  return (
    <DropdownMenuItem onClick={go}>
      {Icon ? <Icon className="size-3.5" /> : null}
      {String(p.label ?? href)}
    </DropdownMenuItem>
  );
}

export function UserMenu({ links = [] }: { links?: string[] }) {
  const [mode, setMode] = useMode();
  const user = bootUser();
  const Sun = icon("sun");
  const Moon = icon("moon");
  const scheme = useScheme();
  const ModeIcon = scheme === "dark" ? Moon : Sun;
  const signOut = () => {
    void fetch(mw("/auth/logout"), { method: "POST" }).finally(() => window.location.assign(signOutUrl()));
  };
  const canSignOut = user !== null && user.sign_out !== null;
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
        {links.length ? (
          <>
            <DropdownMenuGroup className="md:hidden">
              {links.map((id) => (
                <MenuLink key={id} id={id} />
              ))}
            </DropdownMenuGroup>
            <DropdownMenuSeparator className="md:hidden" />
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
            {canSignOut ? <DropdownMenuItem onClick={signOut}>{t("sign_out")}</DropdownMenuItem> : null}
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
      data-slot="header"
      className={cn(
        "sticky top-0 z-20 flex h-16 shrink-0 items-center gap-5 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80",
        props.cls as string,
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {props.logo !== false ? <Logo /> : null}
        {props.title ? <span data-slot="header-title" className="truncate text-lg font-semibold tracking-tight">{String(props.title)}</span> : null}
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
        {props.user_menu !== false ? <UserMenu links={links} /> : null}
      </div>
    </header>
  );
};
