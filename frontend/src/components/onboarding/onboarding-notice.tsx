import { ArrowRight, Lock } from "lucide-react";
import Link from "next/link";

import type { Me } from "@/lib/api/types";

/** Shown on app pages while a signed-in user's library can't be used yet. */
export function OnboardingNotice({ me }: { me: Me }) {
  if (me.profile_ready) return null;
  const isPrivate = me.library_mode === "steam_import" && me.steam?.game_details_status === "private";
  const manual = me.library_mode === "manual";
  return (
    <Link
      href="/onboarding"
      className="mb-6 flex items-center gap-3 rounded-xl border border-brand-500/30 bg-brand-500/10 px-4 py-3 text-sm text-fg hover:bg-brand-500/15"
    >
      <Lock className="size-4 shrink-0 text-brand-300" aria-hidden="true" />
      <span className="flex-1">
        {manual
          ? `Rate at least ${me.min_rated_games} games you've played to build your profile (${me.library.games_rated} so far).`
          : isPrivate
            ? "Your Steam game details are private, so we can't read your library yet."
            : "We're still setting up your library."}{" "}
        <span className="font-medium text-brand-300">Finish setup</span>
      </span>
      <ArrowRight className="size-4 text-brand-300" aria-hidden="true" />
    </Link>
  );
}
