"use client";

import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, Lock, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { SYNC_IN_PROGRESS, type Me } from "@/lib/api/types";

const POLL_MS = 2500;
const STEAM_PRIVACY_URL = "https://steamcommunity.com/my/edit/settings";

const FAILURE_MESSAGES: Record<string, string> = {
  steam_api_key_missing:
    "Library import isn't configured on this server yet. Please try again later.",
  provider_unavailable: "Steam didn't respond. This is usually temporary; try again in a minute.",
  provider_rate_limited: "Steam is limiting requests right now. Please try again in a few minutes.",
  provider_auth_error: "Steam rejected our request. The site operator has been notified.",
  steam_account_not_found: "Steam couldn't find your account profile.",
};

type Phase = "importing" | "private" | "empty" | "failed" | "ready";

function phaseOf(me: Me): Phase {
  const sync = me.latest_sync;
  if (sync && SYNC_IN_PROGRESS.includes(sync.status)) return "importing";
  if (me.profile_ready) return "ready";
  if (sync?.status === "blocked_private" || me.steam?.game_details_status === "private") {
    return "private";
  }
  if (sync?.status === "empty") return "empty";
  if (sync?.status === "failed") return "failed";
  return "importing";
}

export function OnboardingStatus({ initial }: { initial: Me }) {
  const router = useRouter();
  const [me, setMe] = useState(initial);
  const [retrying, setRetrying] = useState(false);
  const phase = phaseOf(me);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/me", { cache: "no-store" });
    if (res.ok) setMe((await res.json()) as Me);
  }, []);

  useEffect(() => {
    if (phase !== "importing") return;
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [phase, refresh]);

  const retry = async () => {
    setRetrying(true);
    try {
      const res = await fetch("/api/me/steam/sync", { method: "POST" });
      if (res.ok) setMe((await res.json()) as Me);
      // 409: the server is in sign-in-only mode (this page predates the switch).
      // Re-render on the server so the add-and-rate onboarding replaces this one.
      else if (res.status === 409) router.refresh();
    } finally {
      setRetrying(false);
    }
  };

  const retryButton = (
    <Button onClick={retry} disabled={retrying}>
      <RefreshCw className={retrying ? "animate-spin" : undefined} aria-hidden="true" />
      Check again
    </Button>
  );

  return (
    <Card aria-live="polite">
      <CardContent className="p-6 sm:p-8">
        {phase === "importing" ? (
          <div className="flex items-start gap-4">
            <Loader2 className="mt-1 size-6 shrink-0 animate-spin text-brand-400" aria-hidden="true" />
            <div>
              <h2 className="text-xl font-semibold text-fg">Importing your Steam library…</h2>
              <p className="mt-2 text-fg-muted">
                We&apos;re reading your games and playtime from Steam. This usually takes a few
                seconds; large libraries can take a minute.
              </p>
            </div>
          </div>
        ) : null}

        {phase === "private" ? (
          <div className="flex items-start gap-4">
            <Lock className="mt-1 size-6 shrink-0 text-caution" aria-hidden="true" />
            <div className="space-y-4">
              <div>
                <h2 className="text-xl font-semibold text-fg">Your game details are private</h2>
                <p className="mt-2 text-fg-muted">
                  Steam only shares your library with other sites when your game details are
                  public. We haven&apos;t built a profile for you, because an empty profile
                  would give you misleading recommendations.
                </p>
              </div>
              <ol className="list-decimal space-y-2 pl-5 text-sm text-fg">
                <li>
                  Open your{" "}
                  <a href={STEAM_PRIVACY_URL} target="_blank" rel="noopener noreferrer"
                     className="inline-flex items-center gap-1 text-brand-300 hover:text-brand-400">
                    Steam privacy settings <ExternalLink className="size-3.5" aria-hidden="true" />
                  </a>
                  .
                </li>
                <li>
                  Set <strong>My profile</strong> to <strong>Public</strong>.
                </li>
                <li>
                  Set <strong>Game details</strong> to <strong>Public</strong>.
                </li>
                <li>
                  Leave <strong>&ldquo;Always keep my total playtime private&rdquo;</strong>{" "}
                  unticked, so we can see how much you&apos;ve played each game.
                </li>
                <li>Come back here and press &ldquo;Check again&rdquo;. Steam may take a minute to apply the change.</li>
              </ol>
              {retryButton}
            </div>
          </div>
        ) : null}

        {phase === "empty" ? (
          <div className="flex items-start gap-4">
            <AlertTriangle className="mt-1 size-6 shrink-0 text-caution" aria-hidden="true" />
            <div className="space-y-4">
              <div>
                <h2 className="text-xl font-semibold text-fg">Your Steam library looks empty</h2>
                <p className="mt-2 text-fg-muted">
                  Steam reports no games on this account, so there&apos;s nothing to build a
                  profile from yet. If you do own games, check that they aren&apos;t on a
                  different Steam account.
                </p>
              </div>
              {retryButton}
            </div>
          </div>
        ) : null}

        {phase === "failed" ? (
          <div className="flex items-start gap-4">
            <AlertTriangle className="mt-1 size-6 shrink-0 text-negative" aria-hidden="true" />
            <div className="space-y-4">
              <div>
                <h2 className="text-xl font-semibold text-fg">We couldn&apos;t import your library</h2>
                <p className="mt-2 text-fg-muted">
                  {FAILURE_MESSAGES[me.latest_sync?.error_code ?? ""] ??
                    "Something went wrong while talking to Steam. Please try again."}
                </p>
              </div>
              {retryButton}
            </div>
          </div>
        ) : null}

        {phase === "ready" ? (
          <div className="flex items-start gap-4">
            <CheckCircle2 className="mt-1 size-6 shrink-0 text-positive" aria-hidden="true" />
            <div className="space-y-4">
              <div>
                <h2 className="text-xl font-semibold text-fg">
                  Imported {me.library.games_owned.toLocaleString("en")} games
                </h2>
                <p className="mt-2 text-fg-muted">
                  {me.library.games_played.toLocaleString("en")} of them have recorded playtime.
                  From now on we keep a history of your playtime, starting today. Steam
                  doesn&apos;t share earlier history.
                </p>
                {me.steam?.playtime_appears_hidden ? (
                  <p className="mt-3 rounded-lg border border-caution/30 bg-caution/10 p-3 text-sm text-fg">
                    Every game shows zero playtime. If you&apos;ve ticked &ldquo;Always keep my
                    total playtime private&rdquo; on Steam, untick it and press Check again.
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-3">
                <Link href="/library" className={buttonVariants()}>
                  See my library
                </Link>
                <Link href="/dashboard" className={buttonVariants({ variant: "secondary" })}>
                  Go to dashboard
                </Link>
              </div>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
