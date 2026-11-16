import { Activity, Info, Users } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

import { GameCover } from "@/components/games/game-cover";
import { RecommendationGrid } from "@/components/games/recommendation-card";
import { ScoreBadge } from "@/components/games/score-badge";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { PreviewBanner } from "@/components/layout/preview-banner";
import { ListStatus } from "@/components/recommendations/list-status";
import { PendingRefresher } from "@/components/recommendations/pending-refresher";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { SectionHeader } from "@/components/ui/section-header";
import { getRecommendationList } from "@/lib/data";
import { getCurrentUser } from "@/lib/session";
import type { RecommendationList, TrendStatus } from "@/lib/types";

export const metadata: Metadata = { title: "Trending Games" };

function availableFrom(t: TrendStatus): string | null {
  if (!t.firstDay) return null;
  const d = new Date(`${t.firstDay}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + t.daysNeeded);
  return d.toLocaleDateString("en-GB", { dateStyle: "long", timeZone: "UTC" });
}

function Collecting({ t }: { t: TrendStatus }) {
  const pct = Math.min(100, Math.round((t.daysCollected / t.daysNeeded) * 100));
  const from = availableFrom(t);
  return (
    <Card className="mb-10">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="size-5 text-brand-300" aria-hidden="true" />
          Collecting player-count history
        </CardTitle>
        <CardDescription>
          A trend compares the last 7 days with the 4 weeks before, and checks whether growth is
          speeding up, so it needs {t.daysNeeded} days of history. Until then this page shows no
          trend scores rather than guessing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div
          className="h-2 overflow-hidden rounded-full bg-surface-raised"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={t.daysNeeded}
          aria-valuenow={t.daysCollected}
          aria-label="Days of history collected"
        >
          <span className="block h-full bg-brand-500" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-sm text-fg-muted">
          {t.daysCollected} of {t.daysNeeded} days collected
          {t.gamesTracked ? ` · ${t.gamesTracked.toLocaleString("en")} games tracked` : ""}
          {from ? ` · trends available from about ${from}` : ""}
        </p>
        <SourceHealth t={t} />
      </CardContent>
    </Card>
  );
}

/** Freshness and reliability of the player-count source (shown, never assumed). */
function SourceHealth({ t }: { t: TrendStatus }) {
  const stale =
    t.freshnessHours != null && t.maxStalenessHours != null && t.freshnessHours > t.maxStalenessHours;
  return (
    <p className={stale ? "text-xs text-caution" : "text-xs text-fg-subtle"}>
      Source: Steam&apos;s public current-player counts, sampled every two hours by this site
      {t.freshnessHours != null ? ` · last sample ${Math.round(t.freshnessHours)} h ago` : ""}
      {t.reliability != null ? ` · ${Math.round(t.reliability * 100)}% of requests answered (7 days)` : ""}
      {stale ? " · data is stale, so trend scores are paused" : ""}
    </p>
  );
}

function PopularNow({ list }: { list: RecommendationList }) {
  if (!list.popularNow.length) return null;
  return (
    <section>
      <SectionHeader
        title="Popular right now"
        description="The most-played games at the last count, ranked by size, not growth. This is absolute popularity, not a trend. Games you own or have excluded are left out."
      />
      {/* min-w-0: grid items otherwise refuse to shrink below their content and
          overflowed phone screens (found in the Stage 6 browser check). */}
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {list.popularNow.map((p) => (
          <li key={p.game.id} className="flex min-w-0 gap-3 rounded-card border border-line bg-surface p-4 sm:gap-4">
            <GameCover
              title={p.game.title}
              artworkUrl={p.game.artworkUrl}
              className="h-16 w-28 shrink-0 rounded-lg sm:h-20 sm:w-36"
            />
            <div className="min-w-0 flex-1 space-y-2">
              <p className="truncate font-medium text-fg">
                {p.game.steamAppId ? (
                  <a
                    href={`https://store.steampowered.com/app/${p.game.steamAppId}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-brand-300"
                  >
                    {p.game.title}
                  </a>
                ) : (
                  p.game.title
                )}
              </p>
              <p className="flex items-center gap-1 text-xs text-fg-subtle">
                <Users className="size-3.5" aria-hidden="true" />
                {p.players.toLocaleString("en")} playing
              </p>
              <ScoreBadge score={p.matchScore} kind="match" confidence={p.confidence} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

async function Content() {
  const me = await getCurrentUser();
  const { source, data } = await getRecommendationList(me, "trending");
  const collecting = data.dataState !== "ok" && data.trendStatus;
  return (
    <>
      <PreviewBanner source={source} />
      <PageHeader
        eyebrow="Trending"
        title="Trending Games"
        description="Games whose player numbers are actually growing, not just the biggest games, ranked by how well they suit you (80%) and how strong the trend is (20%)."
      />
      {data.status === "pending" ? (
        <PendingRefresher />
      ) : (
        <>
          {collecting ? <Collecting t={data.trendStatus!} /> : null}
          {data.items.length ? (
            <>
              <ListStatus list={data} />
              <RecommendationGrid items={data.items} sample={source === "mock"} surface="trending" />
              {data.trendStatus ? (
                <div className="mt-6">
                  <SourceHealth t={data.trendStatus} />
                </div>
              ) : null}
            </>
          ) : !collecting && source === "api" ? (
            <p className="mb-10 flex items-start gap-2 rounded-card border border-dashed border-line p-6 text-fg-muted">
              <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {data.note ?? "No game currently passes the trend data-quality checks."}
            </p>
          ) : null}
          <PopularNow list={data} />
        </>
      )}
    </>
  );
}

export default function TrendingPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content />
    </Suspense>
  );
}
