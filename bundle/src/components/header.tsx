// The app bar: the theme's logo, the title, links, the page's actions and a
// user menu with the theme choice and sign-out. Reads the theme and the
// signed-in user from the boot object; the app only says what to show.
// On a narrow screen the links do not fit, and a menu button at the left
// opens them in a panel, together with the page's sidebar when it has one.

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
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "cn";
import { useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { icon } from "../icons";
import { safeUrl, signOut } from "../lib";
import { Render } from "../render";
import { store, useMounts } from "../store";
import { t, theme, useMode, useScheme, type Mode } from "../theme";
import type { Renderer } from "../render";
import { InSidebar, PageNavContext, type PageNav } from "./anchor";

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

// The header's links as a column, for the panel of a narrow screen, with the
// look links have in a sidebar. A press on one closes the panel, also when it
// goes nowhere new, as a link to a place on the page it is on.
export function NavLinks({ links, onGo }: { links: string[]; onGo: () => void }) {
  if (!links.length) return null;
  return (
    <nav
      className="flex flex-col gap-1"
      onClick={(e) => {
        if ((e.target as Element).closest("a")) onGo();
      }}
    >
      <InSidebar.Provider value={true}>
        {links.map((id) => (
          <Render key={id} id={id} />
        ))}
      </InSidebar.Provider>
    </nav>
  );
}

// Those of `ids` whose node is not hidden, kept current as they change.
function useShown(ids: string[]): string[] {
  const all = ids.join("\n");
  const subscribe = useCallback(
    (listener: () => void) => {
      const offs = (all ? all.split("\n") : []).map((id) => store.subscribe(id, listener));
      return () => offs.forEach((off) => off());
    },
    [all],
  );
  const read = () => ids.filter((id) => store.get(id) && !store.get(id)?.props.hidden).join("\n");
  const shown = useSyncExternalStore(subscribe, read, read);
  return useMemo(() => (shown ? shown.split("\n") : []), [shown]);
}

// The button of a narrow screen, where the header's links do not fit. On a
// page whose sidebar is a panel there it opens that panel, which lists the
// links above the sidebar's own. Anywhere else it opens a panel of its own
// with the links. A header with nothing to open has no button.
function NavButton({ links, page }: { links: string[]; page: PageNav | null }) {
  const [own, setOwn] = useState(false);
  const viaSidebar = Boolean(page?.panel);
  const open = viaSidebar ? Boolean(page?.open) : own;
  // The panel is over with the page it was opened on, however the page was
  // left, and with the narrow screen it is for.
  const mounts = useMounts();
  const narrow = useIsMobile();
  useEffect(() => setOwn(false), [mounts, narrow]);
  const Menu = icon("menu");
  if (!viaSidebar && !links.length) return null;
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={t("navigation")}
        aria-expanded={open}
        className="-ml-1 shrink-0 md:hidden print:hidden"
        onClick={() => (viaSidebar ? page?.toggle() : setOwn(true))}
      >
        {Menu ? <Menu /> : null}
      </Button>
      {viaSidebar ? null : (
        <Sheet open={own} onOpenChange={setOwn}>
          <SheetContent
            side="left"
            className="overflow-y-auto bg-sidebar p-3 text-sidebar-foreground data-[side=left]:w-72 data-[side=left]:max-w-[85vw] [&>button]:hidden"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{t("navigation")}</SheetTitle>
              <SheetDescription>{t("navigation")}</SheetDescription>
            </SheetHeader>
            <NavLinks links={links} onGo={() => setOwn(false)} />
          </SheetContent>
        </Sheet>
      )}
    </>
  );
}

export function UserMenu() {
  const [mode, setMode] = useMode();
  const user = bootUser();
  const Sun = icon("sun");
  const Moon = icon("moon");
  const scheme = useScheme();
  const ModeIcon = scheme === "dark" ? Moon : Sun;
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
            {canSignOut ? <DropdownMenuItem onClick={() => void signOut()}>{t("sign_out")}</DropdownMenuItem> : null}
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export const Header: Renderer = ({ props, children }) => {
  const links = ((props.links as { $node: string }[] | undefined) ?? []).map((s) => s.$node);
  const shown = useShown(links);
  // A header that shows tells the page it is on that it has the button for
  // the page's sidebar, and which links go with it.
  const page = useContext(PageNavContext);
  const announce = page?.announce;
  const hidden = Boolean(props.hidden);
  useEffect(() => {
    if (!announce || hidden) return;
    announce(shown);
    return () => announce(null);
  }, [announce, hidden, shown]);
  return (
    <header
      data-slot="header"
      className={cn(
        "sticky top-0 z-20 flex h-16 shrink-0 items-center gap-5 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80",
        props.cls as string,
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <NavButton links={shown} page={page} />
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
        {props.user_menu !== false ? <UserMenu /> : null}
      </div>
    </header>
  );
};
