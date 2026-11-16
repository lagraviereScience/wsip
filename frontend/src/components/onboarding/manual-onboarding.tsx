"use client";

import { ArrowRight, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";

import { GameSearch } from "@/components/library/game-search";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Me } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** Sign-in-only onboarding: add games you own and rate games you've played. */
export function ManualOnboarding({ initial }: { initial: Me }) {
  const [me, setMe] = useState(initial);
  const refresh = useCallback(async () => {
    const res = await fetch("/api/me", { cache: "no-store" });
    if (res.ok) setMe((await res.json()) as Me);
  }, []);

  const rated = me.library.games_rated;
  const goal = me.min_rated_games;
  const pct = Math.min(100, Math.round((rated / goal) * 100));

  return (
    <Card>
      <CardContent className="space-y-6 p-6 sm:p-8">
        <div>
          <h2 className="text-xl font-semibold text-fg">Tell us what you play</h2>
          <p className="mt-2 text-fg-muted">
            Search for games, tick the ones you own and say how much you enjoyed the ones
            you&apos;ve played. Your ratings are what we learn your taste from. We don&apos;t
            read your Steam library, so nothing is shared until you add it here.
          </p>
        </div>

        <div aria-live="polite">
          <div className="flex items-center justify-between text-sm">
            <span className="text-fg">
              {rated >= goal ? (
                <span className="inline-flex items-center gap-1.5 text-positive">
                  <CheckCircle2 className="size-4" aria-hidden="true" />
                  {rated} games rated. Your profile is ready.
                </span>
              ) : (
                <>Rate at least {goal} games you&apos;ve played ({rated}/{goal})</>
              )}
            </span>
            <span className="text-fg-subtle">{me.library.games_owned} owned</span>
          </div>
          <div
            className="mt-2 h-2 overflow-hidden rounded-full bg-surface-raised"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={goal}
            aria-valuenow={Math.min(rated, goal)}
            aria-label="Games rated"
          >
            <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-signal-400 transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>

        <GameSearch onChange={refresh} />

        <div className="flex flex-wrap gap-3 border-t border-line pt-6">
          <Link
            href="/library"
            aria-disabled={!me.profile_ready}
            className={cn(buttonVariants(), !me.profile_ready && "pointer-events-none opacity-50")}
          >
            Continue to my library <ArrowRight aria-hidden="true" />
          </Link>
          <Link href="/dashboard" className={buttonVariants({ variant: "ghost" })}>
            Skip for now
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
