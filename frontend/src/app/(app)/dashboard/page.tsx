import { ArrowRight, Clock, RefreshCw } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";

import { SatisfactionPrompt } from "@/components/feedback/satisfaction-prompt";
import { GameCover } from "@/components/games/game-cover";
import { RecommendationCard } from "@/components/games/recommendation-card";
import { PreviewBanner } from "@/components/layout/preview-banner";
import { PreferenceBar } from "@/components/profile/preference-bar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { SectionHeader } from "@/components/ui/section-header";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { OnboardingNotice } from "@/components/onboarding/onboarding-notice";
import { Badge } from "@/components/ui/badge";
import { PendingRefresher } from "@/components/recommendations/pending-refresher";
import {
  getFeedbackList,
  getProfileSummary,
  getRecentActivity,
  getRecommendationList,
} from "@/lib/data";
import { getCurrentUser } from "@/lib/session";
import { formatPlaytime } from "@/lib/utils";

export const metadata: Metadata = { title: "Dashboard" };

const SEE_ALL = "inline-flex items-center gap-1 text-sm text-brand-300 hover:text-brand-400";

async function Dashboard() {
  const me = await getCurrentUser();
  const [owned, unowned, trending, profile, activity, feedback] = await Promise.all([
    // Only what the dashboard shows: top pick, backlog picks, two store picks, two trending.
    getRecommendationList(me, "owned", undefined, 12),
    getRecommendationList(me, "unowned", undefined, 4),
    getRecommendationList(me, "trending", undefined, 3),
    getProfileSummary(me),
    getRecentActivity(me),
    getFeedbackList(me),
  ]);
  const saved = feedback.filter((g) => g.saved);
  const sample = owned.source === "mock";
  const pending = owned.data.status === "pending";
  // Top pick: the best owned suggestion, else the best store match.
  const topPick = owned.data.items[0] ?? unowned.data.items[0];
  const backlog = owned.data.items
    .slice(owned.data.items[0] ? 1 : 0)
    .filter((r) => (r.playtimeMinutes ?? 0) < 120);
  const p = profile.data;
  const trendingCollecting = trending.data.dataState !== "ok" ? trending.data.trendStatus : null;

  return (
    <>
      <PreviewBanner source={owned.source} />
      {me ? <OnboardingNotice me={me} /> : null}
      <PageHeader
        eyebrow="Dashboard"
        title="What should I play right now?"
        description="Your best options right now, from your backlog, the store and what's trending."
      />
      {me ? <SatisfactionPrompt /> : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section aria-labelledby="top-pick">
          <h2 id="top-pick" className="sr-only">
            Top pick
          </h2>
          {pending ? (
            <PendingRefresher />
          ) : topPick ? (
            <RecommendationCard recommendation={topPick} className="h-full" sample={sample} />
          ) : (
            <p className="rounded-card border border-dashed border-line p-8 text-center text-fg-muted">
              Nothing to recommend yet.
            </p>
          )}
        </section>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Your gamer profile
                {profile.source === "mock" ? <Badge tone="caution">Sample</Badge> : null}
              </CardTitle>
              <CardDescription>
                {Math.round(p.profileConfidence * 100)}% profile confidence ·{" "}
                {Math.round(p.singleplayerShare * 100)}% singleplayer
                {p.excludedTags.length ? ` · ${p.excludedTags.length} excluded` : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {p.topPreferences.slice(0, 3).map((pref) => (
                <PreferenceBar key={pref.feature} preference={pref} />
              ))}
              <Link href="/profile" className={SEE_ALL}>
                Full profile <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent activity</CardTitle>
              <CardDescription className="flex items-center gap-1.5">
                <RefreshCw className="size-3.5" aria-hidden="true" />
                Last synced{" "}
                {p.lastSyncedAt ? (
                  <time dateTime={p.lastSyncedAt}>
                    {new Date(p.lastSyncedAt).toLocaleString("en-GB", {
                      dateStyle: "medium",
                      timeStyle: "short",
                      timeZone: "UTC",
                    })}{" "}
                    UTC
                  </time>
                ) : (
                  "never"
                )}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {activity.data.length === 0 ? (
                <p className="text-sm text-fg-muted">
                  {me?.library_mode === "manual"
                    ? "Playtime tracking needs automatic Steam import, which is off. Your ratings drive recommendations instead."
                    : me && !me.profile_ready
                      ? "Available once your library is imported."
                      : "No play in the last two weeks."}
                </p>
              ) : (
                <ul className="space-y-3">
                  {activity.data.map((a) => (
                    <li key={a.game.id} className="flex items-center gap-3">
                      <GameCover
                        title={a.game.title}
                        artworkUrl={a.game.artworkUrl}
                        className="size-11 shrink-0 rounded-lg [&_span]:text-base"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-fg">{a.game.title}</p>
                        <p className="flex items-center gap-1 text-xs text-fg-subtle">
                          <Clock className="size-3" aria-hidden="true" />
                          {formatPlaytime(a.recentMinutes)} in the last 2 weeks
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {saved.length ? (
        <section className="mt-12" aria-labelledby="saved-for-later">
          <SectionHeader
            title="Saved for later"
            description="Games you bookmarked from your recommendations."
            action={
              <Link href="/profile#feedback" className={SEE_ALL}>
                Manage <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            }
          />
          <ul id="saved-for-later" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {saved.slice(0, 8).map((g) => (
              <li key={g.game_id}>
                <Link
                  href={`/games/${g.game_id}`}
                  className="flex items-center gap-3 rounded-card border border-line bg-surface p-3 hover:border-line-strong"
                >
                  <GameCover
                    title={g.name}
                    artworkUrl={g.capsule_image_url}
                    className="h-11 w-20 shrink-0 rounded-lg [&_span]:text-base"
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-fg">{g.name}</span>
                    <span className="text-xs text-fg-subtle">{g.owned ? "Owned" : "Not owned"}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-12">
        <SectionHeader
          title="Worth digging out of your backlog"
          description="Owned games you've barely touched that fit your profile."
          action={
            <Link href="/play" className={SEE_ALL}>
              See all <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          }
        />
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {backlog.slice(0, 3).map((r) => (
            <RecommendationCard key={r.game.id} recommendation={r} sample={sample} />
          ))}
        </div>
      </section>

      <section className="mt-12 grid gap-10 xl:grid-cols-2">
        <div>
          <SectionHeader
            title="Trending for you"
            action={
              <Link href="/trending" className={SEE_ALL}>
                See all <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            }
          />
          {trendingCollecting ? (
            <p className="rounded-card border border-dashed border-line p-6 text-sm text-fg-muted">
              Trends need {trendingCollecting.daysNeeded} days of player-count history;{" "}
              {trendingCollecting.daysCollected} collected so far. Until then we show no trend
              scores rather than guess.{" "}
              <Link href="/trending" className="text-brand-300 hover:text-brand-400">
                Popular right now
              </Link>
            </p>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
              {trending.data.items.slice(0, 2).map((r) => (
                <RecommendationCard key={r.game.id} recommendation={r} sample={sample} />
              ))}
            </div>
          )}
        </div>
        <div>
          <SectionHeader
            title="Worth buying"
            action={
              <Link href="/buy" className={SEE_ALL}>
                See all <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            }
          />
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            {unowned.data.items.slice(topPick === unowned.data.items[0] ? 1 : 0, (topPick === unowned.data.items[0] ? 1 : 0) + 2).map((r) => (
              <RecommendationCard key={r.game.id} recommendation={r} sample={sample} />
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Dashboard />
    </Suspense>
  );
}
