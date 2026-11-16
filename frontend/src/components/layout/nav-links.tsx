"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import { NAV_ITEMS } from "@/lib/navigation";
import { cn } from "@/lib/utils";

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

// The current path is request data: on dynamic routes (/games/[id]) it must be read
// inside <Suspense>. The fallback is the same navigation without the highlight.
export function SidebarNav() {
  return (
    <Suspense fallback={<SidebarList pathname="" />}>
      <SidebarWithPath />
    </Suspense>
  );
}

function SidebarWithPath() {
  return <SidebarList pathname={usePathname()} />;
}

function SidebarList({ pathname }: { pathname: string }) {
  return (
    <nav aria-label="Primary" className="flex flex-col gap-1">
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
              active
                ? "bg-brand-500/15 text-fg ring-1 ring-brand-500/30"
                : "text-fg-muted hover:bg-surface-hover hover:text-fg",
            )}
          >
            <Icon className={cn("size-[18px]", active ? "text-brand-400" : "text-fg-subtle")} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function MobileNav() {
  return (
    <Suspense fallback={<MobileList pathname="" />}>
      <MobileWithPath />
    </Suspense>
  );
}

function MobileWithPath() {
  return <MobileList pathname={usePathname()} />;
}

function MobileList({ pathname }: { pathname: string }) {
  return (
    <nav
      aria-label="Primary"
      className="scrollbar-none -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-3"
    >
      {NAV_ITEMS.map(({ href, shortLabel, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm",
              active
                ? "border-brand-500/40 bg-brand-500/15 text-fg"
                : "border-line text-fg-muted",
            )}
          >
            <Icon className="size-4" />
            {shortLabel}
          </Link>
        );
      })}
    </nav>
  );
}
