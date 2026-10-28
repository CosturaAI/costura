"use client";

import {
  Activity,
  Building2,
  Check,
  ChevronsLeft,
  ChevronsRight,
  ChevronsUpDown,
  LayoutDashboard,
  ListChecks,
  LogIn,
  LogOut,
  type LucideIcon,
  MailOpen,
  Menu,
  Plus,
  Search,
  Settings,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useSelectedLayoutSegment } from "next/navigation";
import { useCallback, useState, useSyncExternalStore } from "react";

import { signOutAction } from "@/actions/sign-out";
import { switchOrganizationAction } from "@/actions/view";
import { ScopeSelectors, type ScopeSelectorProps } from "@/components/scope-bar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Role } from "@/lib/roles";
import { roleLabel } from "@/lib/roles";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const PAGES = [
  { segment: "overview", label: "Overview", group: "Overview", icon: LayoutDashboard },
  { segment: "explore", label: "Analyze", group: "Analyze", icon: Search },
  { segment: "anomalies", label: "Anomalies", group: "Guardrails", icon: Activity },
  { segment: "budgets", label: "Budgets", group: "Guardrails", icon: Wallet },
  { segment: "reconcile", label: "Reconciliation", group: "Data health", icon: ListChecks },
] as const;

type PageSegment = (typeof PAGES)[number]["segment"];

const GROUPS = ["Overview", "Analyze", "Guardrails", "Data health"] as const;

/** `usage` redirects to explore; entity pages highlight Analyze, where they are reached from;
 * run history and resources sit under Data health without an item of their own. */
const ALIASES: Record<string, PageSegment> = {
  usage: "explore",
  keys: "explore",
  accounts: "explore",
  people: "explore",
  workspaces: "explore",
  models: "explore",
  runs: "reconcile",
  inventory: "reconcile",
};

const COLLAPSED_KEY = "costura.sidebar.collapsed";
const COLLAPSED_EVENT = "costura:sidebar";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function subscribeCollapsed(callback: () => void): () => void {
  window.addEventListener(COLLAPSED_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(COLLAPSED_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

function writeCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, value ? "1" : "0");
  } catch {
    // storage unavailable: the rail stays as rendered
  }
  document.documentElement.dataset.sidebar = value ? "collapsed" : "expanded";
  window.dispatchEvent(new Event(COLLAPSED_EVENT));
}

/** The signed-in user as the account menu shows them: e-mail, the organizations they can
 * open, and how many invitations wait for the address. */
export type SidebarUser = {
  email: string;
  invitations?: number;
  organizations: { slug: string; name: string; role: Role | null }[];
};

/** The active organization, as the sidebar brand and the account menu name it. */
type SidebarAccount = { slug: string; name: string; role: Role | null; isDemo: boolean };

type SidebarProps = {
  account: SidebarAccount;
  /** Count shown after a label (open anomalies on Anomalies); 0 hides it. */
  badges?: Partial<Record<PageSegment, number>>;
  /** Signed-in user; when given, the footer is the account menu. `null` marks a
   * visitor without a session (the public sample organization): the footer shows Sign in
   * instead. Undefined renders no footer. */
  user?: SidebarUser | null;
  /** Scope controls rendered inside the mobile sheet. */
  scope?: ScopeSelectorProps;
  /** Display name from COSTURA_BRAND_NAME. Defaults to Costura. */
  brandName?: string;
};

function useActiveSegment(): string {
  const segment = useSelectedLayoutSegment() ?? "overview";
  return ALIASES[segment] ?? segment;
}

function NavLink({
  href,
  label,
  icon: Icon,
  active,
  count,
  collapsed,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  count: number;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      title={collapsed ? label : undefined}
      className={cn(
        "flex min-h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium transition-colors",
        active
          ? "bg-accent text-primary"
          : "text-secondary-foreground hover:bg-muted hover:text-foreground",
        collapsed && "justify-center px-0",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      <span className={cn("sidebar-expanded flex-1 truncate", collapsed && "sr-only")}>
        {label}
      </span>
      {count > 0 ? (
        <span
          aria-label={`${count} open`}
          className={cn(
            "inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-severity-critical px-1.5 font-mono text-xs leading-none text-on-solid",
            collapsed && "absolute top-1 right-1 h-4 min-w-4 px-1 text-[10px]",
          )}
        >
          {count}
        </span>
      ) : null}
    </Link>
  );
}

function NavGroups({
  badges,
  collapsed,
  onNavigate,
}: {
  badges: Partial<Record<PageSegment, number>>;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const active = useActiveSegment();
  return (
    <nav aria-label="Sections" className="flex flex-1 flex-col gap-4 overflow-y-auto px-2 py-3">
      {GROUPS.map((group) => {
        const pages = PAGES.filter((page) => page.group === group);
        return (
          <div key={group} className="space-y-0.5">
            {pages.length > 1 ? (
              <p
                className={cn(
                  "sidebar-expanded px-2.5 pb-1 text-xs font-medium tracking-wider text-muted-foreground uppercase",
                  collapsed && "sr-only",
                )}
              >
                {group}
              </p>
            ) : null}
            {pages.map((page) => (
              <div key={page.segment} className="relative">
                <NavLink
                  href={`/${page.segment}`}
                  label={page.label}
                  icon={page.icon}
                  active={active === page.segment}
                  count={badges[page.segment] ?? 0}
                  collapsed={collapsed}
                  onNavigate={onNavigate}
                />
              </div>
            ))}
          </div>
        );
      })}
    </nav>
  );
}

function SettingsLink({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const active = useActiveSegment() === "settings";
  return (
    <div className="border-t border-border px-2 py-2">
      <NavLink
        href="/settings"
        label="Settings"
        icon={Settings}
        active={active}
        count={0}
        collapsed={collapsed}
        onNavigate={onNavigate}
      />
    </div>
  );
}

/**
 * The account menu: the trigger names the active organization and the caller's
 * role in it, like a workspace switcher; the menu lists the e-mail, every organization the
 * caller can open with a check on the active one, the way to a new one or to pending
 * invitations, the organization settings and the way out. Switching posts to a server action
 * that opens `/o/{slug}`, which writes the view cookie and lands on the same page.
 */
function UserFooter({
  account,
  user,
  collapsed,
  onNavigate,
}: {
  account: SidebarAccount;
  user: SidebarUser;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const invitations = user.invitations ?? 0;
  const subtitle = account.isDemo
    ? "Sample organization"
    : `${roleLabel(account.role)} - ${account.name}`;
  return (
    <div className="border-t border-border px-2 py-2">
      <DropdownMenu>
        <DropdownMenuTrigger
          title={collapsed ? account.name : undefined}
          className={cn(
            "flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm transition-colors hover:bg-muted data-[state=open]:bg-muted",
            collapsed && "justify-center px-0",
          )}
        >
          <span
            aria-hidden
            data-initial={account.name.slice(0, 1)}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-subtle text-xs font-semibold text-secondary-foreground uppercase before:content-[attr(data-initial)]"
          />
          <span className="sr-only">Account menu: </span>
          <span className={cn("sidebar-expanded min-w-0 flex-1", collapsed && "sr-only")}>
            <span className="block truncate font-medium text-foreground">{account.name}</span>
            <span className="block truncate text-xs text-muted-foreground">{subtitle}</span>
          </span>
          <ChevronsUpDown
            className={cn(
              "sidebar-expanded h-4 w-4 shrink-0 text-muted-foreground",
              collapsed && "sr-only",
            )}
            aria-hidden
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-64">
          <DropdownMenuLabel className="truncate" title={user.email}>
            {user.email}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Organizations</DropdownMenuLabel>
            {user.organizations.map((organization) => {
              const active = organization.slug === account.slug;
              return (
                <form key={organization.slug} action={switchOrganizationAction}>
                  <input type="hidden" name="slug" value={organization.slug} />
                  <input type="hidden" name="next" value={pathname} />
                  <DropdownMenuItem asChild disabled={active}>
                    <button
                      type="submit"
                      className="w-full"
                      aria-current={active ? "true" : undefined}
                      onClick={onNavigate}
                    >
                      <Building2 className="text-muted-foreground" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{organization.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {roleLabel(organization.role)}
                        </span>
                      </span>
                      {active ? <Check className="text-primary" aria-label="Active" /> : null}
                    </button>
                  </DropdownMenuItem>
                </form>
              );
            })}
          </DropdownMenuGroup>
          <DropdownMenuItem asChild>
            <Link href="/new" onClick={onNavigate}>
              <Plus className="text-muted-foreground" aria-hidden />
              New organization
            </Link>
          </DropdownMenuItem>
          {invitations > 0 ? (
            <DropdownMenuItem asChild>
              <Link href="/join" onClick={onNavigate}>
                <MailOpen className="text-muted-foreground" aria-hidden />
                <span className="flex-1">Invitations</span>
                <span
                  aria-label={`${invitations} pending`}
                  className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-severity-critical px-1.5 font-mono text-xs leading-none text-on-solid"
                >
                  {invitations}
                </span>
              </Link>
            </DropdownMenuItem>
          ) : null}
          {!account.isDemo ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link href="/settings/organization" onClick={onNavigate}>
                  <Settings className="text-muted-foreground" aria-hidden />
                  Organization settings
                </Link>
              </DropdownMenuItem>
            </>
          ) : null}
          <DropdownMenuSeparator />
          <form action={signOutAction}>
            <DropdownMenuItem asChild>
              <button type="submit" className="w-full">
                <LogOut className="text-muted-foreground" aria-hidden />
                Sign out
              </button>
            </DropdownMenuItem>
          </form>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

/** The way in, for a visitor reading the public sample organization. */
function GuestFooter({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <div className="border-t border-border px-2 py-2">
      <NavLink
        href="/sign-in"
        label="Sign in"
        icon={LogIn}
        active={false}
        count={0}
        collapsed={collapsed}
        onNavigate={onNavigate}
      />
    </div>
  );
}

function Footer({
  account,
  user,
  collapsed,
  onNavigate,
}: {
  account: SidebarAccount;
  user: SidebarProps["user"];
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  if (user === undefined) return null;
  if (user === null) return <GuestFooter collapsed={collapsed} onNavigate={onNavigate} />;
  return <UserFooter account={account} user={user} collapsed={collapsed} onNavigate={onNavigate} />;
}

/** Same geometry as public/brand/logo.svg. Drawn here: an img of that file shows the broken-image icon in Safari. */
function LogoMark() {
  return (
    <svg
      viewBox="0 0 512 512"
      aria-hidden
      width={36}
      height={36}
      data-brand-mark=""
      className="h-9 w-9 shrink-0"
    >
      <g className="fill-brand-600">
        <rect x="84" y="262" width="66" height="146" rx="12" />
        <rect x="276" y="150" width="66" height="258" rx="12" />
      </g>
      <path
        d="M40 318 C 90 268, 130 366, 180 330 S 270 262, 309 220 S 360 150, 402 118"
        fill="none"
        className="stroke-accent-indigo"
        strokeWidth="10"
        strokeLinecap="round"
        strokeDasharray="20 16"
      />
      <rect x="180" y="206" width="66" height="202" rx="12" className="fill-brand-600" />
      <g transform="translate(416 106) rotate(40)">
        <line
          x1="0"
          y1="16"
          x2="0"
          y2="-40"
          className="stroke-brand-600"
          strokeWidth="12"
          strokeLinecap="round"
        />
        <line
          x1="0"
          y1="-36"
          x2="0"
          y2="-80"
          className="stroke-brand-600"
          strokeWidth="5"
          strokeLinecap="round"
        />
        <ellipse cx="0" cy="4" rx="3.5" ry="9" className="fill-surface-50" />
      </g>
    </svg>
  );
}

function Brand({
  orgName,
  collapsed,
  brandName = "Costura",
}: {
  orgName: string;
  collapsed: boolean;
  brandName?: string;
}) {
  return (
    <Link
      href="/overview"
      className={cn("flex items-center gap-2 px-4 py-4", collapsed && "justify-center px-0")}
    >
      <LogoMark />
      <span className={cn("sidebar-expanded min-w-0", collapsed && "sr-only")}>
        <span className="flex items-center gap-1.5">
          <span className="text-base leading-tight font-bold tracking-tight text-primary">
            {brandName}
          </span>
          <span className="badge-brand uppercase">
            Beta<span className="sr-only">: this release can still have bugs</span>
          </span>
        </span>
        <span className="block truncate text-xs text-muted-foreground">{orgName}</span>
      </span>
    </Link>
  );
}

/** Desktop sidebar: 240 px, collapsible to a 56 px icon rail; the choice persists in localStorage. */
export function Sidebar({ account, badges = {}, user, brandName }: SidebarProps) {
  const collapsed = useSyncExternalStore(subscribeCollapsed, readCollapsed, () => false);
  const toggle = useCallback(() => writeCollapsed(!collapsed), [collapsed]);
  return (
    <aside
      aria-label="Sidebar"
      data-sidebar-rail=""
      data-collapsed={collapsed || undefined}
      className={cn(
        "sticky top-(--public-demo-bar) hidden h-[calc(100dvh-var(--public-demo-bar))] shrink-0 flex-col border-r border-border bg-card lg:flex print:hidden",
        collapsed ? "w-14" : "w-60",
      )}
    >
      <Brand orgName={account.name} collapsed={collapsed} brandName={brandName} />
      <NavGroups badges={badges} collapsed={collapsed} />
      <SettingsLink collapsed={collapsed} />
      <Footer account={account} user={user} collapsed={collapsed} />
      <div className="border-t border-border p-2">
        <button
          type="button"
          onClick={toggle}
          aria-pressed={collapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex min-h-9 w-full items-center justify-center gap-2 rounded-lg text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {collapsed ? (
            <ChevronsRight className="h-4 w-4" aria-hidden />
          ) : (
            <>
              <ChevronsLeft className="h-4 w-4" aria-hidden />
              <span className="sidebar-expanded">Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

/** The pages a phone reaches in one tap; the fourth is Data health, as the sidebar group
 * names it, and lands on Reconciliation. The sheet has the rest. */
const MOBILE_TABS: readonly {
  segment: PageSegment;
  href: string;
  label: string;
}[] = [
  { segment: "overview", href: "/overview", label: "Overview" },
  { segment: "explore", href: "/explore", label: "Analyze" },
  { segment: "anomalies", href: "/anomalies", label: "Anomalies" },
  { segment: "reconcile", href: "/reconcile", label: "Data health" },
];

function mobileTabActive(active: string, segment: PageSegment): boolean {
  if (segment !== "reconcile") return active === segment;
  return active === "reconcile" || active === "runs" || active === "inventory";
}

/**
 * Below `lg`: a fixed row of tabs at the bottom of the viewport, so a section change costs one
 * tap instead of opening the sheet. The sheet stays for the rest of the pages, the scope
 * selectors, settings and sign-out.
 */
export function BottomTabs({ badges = {} }: { badges?: SidebarProps["badges"] }) {
  const active = useActiveSegment();
  return (
    <nav
      aria-label="Quick sections"
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-border bg-card/95 backdrop-blur lg:hidden print:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {MOBILE_TABS.map((tab) => {
        const page = PAGES.find((item) => item.segment === tab.segment)!;
        const count = badges[tab.segment] ?? 0;
        const isActive = mobileTabActive(active, tab.segment);
        return (
          <Link
            key={tab.segment}
            href={tab.href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "relative flex min-h-12 flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
              isActive ? "text-primary" : "text-muted-foreground",
            )}
          >
            <page.icon className="h-5 w-5" aria-hidden />
            {tab.label}
            {count > 0 ? (
              <span
                aria-label={`${count} open`}
                className="absolute top-1 right-[calc(50%-1.25rem)] inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-severity-critical px-1 font-mono text-[10px] leading-none text-on-solid"
              >
                {count}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

/** Below `lg`: the same navigation in a sheet opened from the menu button in the scope bar. */
export function MobileNav({ account, badges = {}, user, scope, brandName }: SidebarProps) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card text-secondary-foreground hover:bg-background lg:hidden">
        <Menu className="h-4 w-4" aria-hidden />
        <span className="sr-only">Open navigation</span>
      </SheetTrigger>
      <SheetContent side="left" className="flex w-72 flex-col p-0">
        <SheetHeader className="sr-only">
          <SheetTitle>Navigation</SheetTitle>
          <SheetDescription>Sections of the {brandName ?? "Costura"} dashboard</SheetDescription>
        </SheetHeader>
        <Brand orgName={account.name} collapsed={false} brandName={brandName} />
        {scope ? (
          <div className="border-y border-border px-4 py-3">
            <ScopeSelectors {...scope} stacked onNavigate={close} />
          </div>
        ) : null}
        <NavGroups badges={badges} collapsed={false} onNavigate={close} />
        <SettingsLink collapsed={false} onNavigate={close} />
        <Footer account={account} user={user} collapsed={false} onNavigate={close} />
      </SheetContent>
    </Sheet>
  );
}
