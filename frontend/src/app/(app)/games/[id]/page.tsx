import { AlertTriangle, Check, ExternalLink, Sparkles, Star } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { SignInButton } from "@/components/auth/sign-in-button";
import { DetailViewTracker } from "@/components/feedback/detail-view-tracker";
import { FeedbackBar } from "@/components/feedback/feedback-bar";
import { FeedbackScope } from "@/components/feedback/feedback-context";
import { GameCover } from "@/components/games/game-cover";
import { ScoreBadge } from "@/components/games/score-badge";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getGamePage } from "@/lib/data";
import { getCurrentUser } from "@/lib/session";
import { LIST_LABEL } from "@/lib/types";
import { cn, formatPlaytime } from "@/lib/utils";

export const metadata: Metadata = { title: "Game" };

function signed(points: number): string {
  const v = Math.round(points * 10) / 10;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

async function Game({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const gameId = Number(id);
  if (!Number.isInteger(gameId) || gameId < 1) notFound();
  const me = await getCurrentUser();
  if (!me) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Sign in to see this game</CardTitle>
          <CardDescription>Game pages show how well a game matches your own profile.</CardDescription>
        </CardHeader>
        <CardContent>
          <SignInButton next={`/games/${gameId}`} />
        </CardContent>
      </Card>
    );
  }
  const g = await getGamePage(me, gameId);
  if (!g) notFound();
  const storeUrl = g.steam_appid ? `https://store.steampowered.com/app/${g.steam_appid}/` : null;
  const positives = g.reasons.filter((r) => r.polarity !== "negative");
  const cautions = g.reasons.filter((r) => r.polarity === "negative");
  const rows = [...g.contributions].sort((a, b) => Math.abs(b.points) - Math.abs(a.points)).slice(0, 12);

  return (
    <FeedbackScope
      gameId={g.game_id}
      title={g.name}
      initial={g.feedback}
      exposure={g.recommendation_run_id && g.rank ? { runId: g.recommendation_run_id, position: g.rank, modelVersion: "" } : null}
      surface="game_page"
      trackImpression={false}
    >
      <DetailViewTracker gameId={g.game_id} runId={g.recommendation_run_id} position={g.rank} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <GameCover title={g.name} artworkUrl={g.header_image_url} className="aspect-[16/9] w-full rounded-card" />
          <div>
            <p className="text-sm text-fg-subtle">
              {g.category ? `Recommended in ${LIST_LABEL[g.category]}` : "Not in your current lists"}
              {g.release_date ? ` · Released ${new Date(g.release_date).getUTCFullYear()}` : ""}
            </p>
            <h1 className="mt-1 font-display text-3xl font-semibold text-fg">{g.name}</h1>
            {g.short_description ? <p className="mt-2 text-fg-muted">{g.short_description}</p> : null}
          </div>
          <ul className="flex flex-wrap gap-1.5" aria-label="Tags">
            {g.tags.map((t) => (
              <li key={t}>
                <Badge>{t}</Badge>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-fg-muted">
            {g.owned ? (
              <span className="inline-flex items-center gap-1 text-positive">
                <Check className="size-4" aria-hidden="true" /> Owned
                {g.playtime_minutes !== null ? (
                  <span className="text-fg-subtle"> · {formatPlaytime(g.playtime_minutes)}</span>
                ) : null}
              </span>
            ) : g.price ? (
              <span className="font-medium text-fg">
                {g.price.is_free ? "Free to play" : g.price.formatted_final}
                {g.price.discount_pct ? <Badge tone="positive" className="ml-2">−{g.price.discount_pct}%</Badge> : null}
              </span>
            ) : null}
            {g.review?.label ? (
              <span className="inline-flex items-center gap-1">
                <Star className="size-3.5 text-caution" aria-hidden="true" />
                {g.review.label}
                {g.review.percent_positive !== null ? ` · ${g.review.percent_positive}%` : ""}
              </span>
            ) : null}
            {storeUrl ? (
              <a
                href={storeUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-track="store_visit"
                className="inline-flex items-center gap-1 text-brand-300 hover:text-brand-400"
              >
                Steam Store <ExternalLink className="size-3.5" aria-hidden="true" />
              </a>
            ) : null}
          </div>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Your feedback</CardTitle>
              <CardDescription>Shapes your profile and your future recommendations. Press again to undo.</CardDescription>
            </CardHeader>
            <CardContent>
              <FeedbackBar />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>How it matches you</CardTitle>
              <CardDescription>
                Computed now from your current profile. Match is not a probability of enjoyment.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {g.match !== null && g.confidence_label ? (
                <ScoreBadge score={g.match} kind="match" confidence={g.confidence_label} />
              ) : (
                <p className="text-sm text-fg-muted">We don&apos;t have enough store data on this game yet.</p>
              )}
              {positives.length ? (
                <ul className="space-y-1 text-sm text-fg-muted">
                  {positives.map((r) => (
                    <li key={r.text} className="flex gap-2">
                      <Sparkles className="mt-0.5 size-3.5 shrink-0 text-brand-300" aria-hidden="true" />
                      {r.text}
                    </li>
                  ))}
                </ul>
              ) : null}
              {cautions.length ? (
                <ul className="space-y-1 text-sm text-fg-muted">
                  {cautions.map((r) => (
                    <li key={r.text} className="flex gap-2">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-caution" aria-hidden="true" />
                      {r.text}
                    </li>
                  ))}
                </ul>
              ) : null}
              {rows.length ? (
                <ul className="space-y-0.5 border-t border-line pt-3 text-xs">
                  {rows.map((c) => (
                    <li key={c.feature} className="flex justify-between gap-2">
                      <span className="text-fg-muted">{c.name}</span>
                      <span className={cn(c.points >= 0 ? "text-positive" : "text-negative")}>{signed(c.points)}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Time to beat</CardTitle>
            </CardHeader>
            <CardContent className="text-sm">
              {g.completion ? (
                <dl className="grid grid-cols-3 gap-2 text-center">
                  {(
                    [
                      ["Rushed", g.completion.hastily_hours],
                      ["Normal", g.completion.normally_hours],
                      ["Everything", g.completion.completely_hours],
                    ] as const
                  ).map(([label, h]) => (
                    <div key={label}>
                      <dt className="text-xs text-fg-subtle">{label}</dt>
                      <dd className="font-medium text-fg">{h != null ? `${h} h` : "unknown"}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-fg-muted">Not available for this game.</p>
              )}
            </CardContent>
          </Card>
          <div className="space-y-1 text-xs text-fg-subtle">
            <p>
              <Link href="/profile#feedback" className="text-brand-300 hover:text-brand-400">
                All your feedback
              </Link>
            </p>
            {(g.sources ?? []).map((s) => (
              <p key={s.data}>
                {s.data}: {s.source}, updated{" "}
                {new Date(s.fetched_at).toLocaleDateString("en-GB", { dateStyle: "medium", timeZone: "UTC" })}
              </p>
            ))}
          </div>
        </div>
      </div>
    </FeedbackScope>
  );
}

export default function GamePage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Game params={params} />
    </Suspense>
  );
}
