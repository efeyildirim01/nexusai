"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, use, useEffect, useState, type ReactNode } from "react";
import { api, authAction } from "@/lib/api";
import { atLeast, type Me, type Role } from "@/lib/types";
import { Badge, cx } from "./ui";

const MeContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = use(MeContext);
  if (!me) throw new Error("useMe must be used inside AppShell");
  return me;
}

const NAV: { href: string; label: string; minimum: Role; icon: string }[] = [
  { href: "/app", label: "Dashboard", minimum: "VIEWER", icon: "M3 13h8V3H3v10Zm0 8h8v-6H3v6Zm10 0h8V11h-8v10Zm0-18v6h8V3h-8Z" },
  { href: "/app/ask", label: "Ask AI", minimum: "ANALYST", icon: "M12 3a9 9 0 1 0 5.2 16.3L21 21l-1.7-3.8A9 9 0 0 0 12 3Z" },
  { href: "/app/data", label: "Data", minimum: "VIEWER", icon: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" },
  { href: "/app/team", label: "Team & audit", minimum: "VIEWER", icon: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm13 9v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    api<Me>("me").then(setMe).catch(() => undefined);
  }, []);

  async function signOut() {
    await authAction("signout", {}).catch(() => undefined);
    // Full navigation drops all client state of the signed-out session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/sign-in");
  }

  if (!me) {
    return <div className="flex flex-1 items-center justify-center text-sm text-slate-500">Loading workspace…</div>;
  }

  const nav = NAV.filter((item) => atLeast(me.user.role, item.minimum));
  return (
    <MeContext value={me}>
      <div className="flex min-h-screen flex-1">
        <aside
          className={cx(
            "fixed inset-y-0 left-0 z-30 w-60 border-r border-slate-200 bg-white px-3 py-5 transition-transform lg:static lg:translate-x-0",
            menuOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <Link href="/app" className="block px-3 text-lg font-semibold tracking-tight text-slate-900">
            Nexus<span className="text-indigo-600">AI</span>
          </Link>
          <p className="mt-1 truncate px-3 text-xs text-slate-500">{me.tenant.name}</p>
          <nav className="mt-6 space-y-1">
            {nav.map((item) => {
              const active = item.href === "/app" ? pathname === "/app" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMenuOpen(false)}
                  className={cx(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
                    active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                  )}
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden>
                    <path d={item.icon} strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>
        {menuOpen && (
          <button aria-label="Close menu" className="fixed inset-0 z-20 bg-slate-900/20 lg:hidden" onClick={() => setMenuOpen(false)} />
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
            <button className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Open menu">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
                <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
              </svg>
            </button>
            <div className="ml-auto flex items-center gap-3 text-sm">
              <span className="hidden text-slate-700 sm:inline">{me.user.full_name}</span>
              <Badge tone="indigo">{me.user.role}</Badge>
              <button onClick={signOut} className="rounded-lg px-2.5 py-1.5 text-slate-600 hover:bg-slate-100">
                Sign out
              </button>
            </div>
          </header>
          <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
        </div>
      </div>
    </MeContext>
  );
}
