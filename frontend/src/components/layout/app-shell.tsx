import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { MobileNav, SidebarNav } from "@/components/layout/nav-links";
import { UserMenu } from "@/components/layout/user-menu";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line bg-surface/60 px-4 py-6 backdrop-blur lg:flex">
        <Link href="/" className="mb-8 px-2">
          <Logo />
        </Link>
        <SidebarNav />
        <div className="mt-auto space-y-4">
          <p className="rounded-xl border border-line bg-surface-raised p-3 text-xs text-fg-subtle">
            Recommendations are built from your own play history. No general-purpose AI
            chatbot involved.
          </p>
          <Suspense fallback={<div className="h-9 animate-pulse rounded-lg bg-surface-raised" />}>
            <UserMenu />
          </Suspense>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-canvas/85 px-4 pt-4 backdrop-blur lg:hidden">
          <div className="mb-3 flex items-center justify-between gap-3">
            <Link href="/">
              <Logo />
            </Link>
            <div className="w-auto">
              <Suspense fallback={null}>
                <UserMenu compact />
              </Suspense>
            </div>
          </div>
          <MobileNav />
        </header>
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
          {children}
        </main>
        <footer className="border-t border-line px-4 py-6 text-center text-xs text-fg-subtle sm:px-6 lg:px-10">
          What Do You Want to Play? is not affiliated with Valve Corporation or Steam. Game
          data provided by Steam.
        </footer>
      </div>
    </div>
  );
}
