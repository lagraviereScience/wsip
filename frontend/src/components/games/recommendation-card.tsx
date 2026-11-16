import { AlertTriangle, Check, ExternalLink, Sparkles, Star, TrendingUp } from "lucide-react";
import Link from "next/link";

import { GameCover } from "@/components/games/game-cover";
import { ScoreBadge } from "@/components/games/score-badge";
import { FeedbackBar } from "@/components/feedback/feedback-bar";
import { FeedbackScope } from "@/components/feedback/feedback-context";
import { ScoreBreakdownDetails } from "@/components/games/score-breakdown";
import { Badge } from "@/components/ui/badge";
import type { Surface } from "@/lib/events";
import { CATEGORY_LABEL, type Recommendation } from "@/lib/types";
import { cn, formatDaysAgo, formatPlaytime } from "@/lib/utils";

export function RecommendationCard({
  recommendation: r,
  className,
  sample = false,
  surface = "dashboard",
}: {
  recommendation: Recommendation;
  className?: string;
  /** Placeholder data: labelled so it can never pass as a real recommendation. */
  sample?: boolean;
  /** Where the card is shown (recorded with impressions and feedback). */
  surface?: Surface;
}) {
  const card = <CardBody r={r} className={className} sample={sample} />;
  if (sample) return card;
  return (
    <FeedbackScope
      gameId={Number(r.game.id)}
      title={r.game.title}
      initial={r.feedback ?? null}
      exposure={r.exposure ?? null}
      surface={surface}
      hideWhenRejected
      className="flex"
    >
      {card}
    </FeedbackScope>
  );
}

function CardBody({
  r,
  className,
  sample,
}: {
  r: Recommendation;
  className?: string;
  sample: boolean;
}) {
  const storeUrl = r.game.steamAppId
    ? `https://store.steampowered.com/app/${r.game.steamAppId}/`
    : null;
  const gameUrl = sample ? null : `/games/${r.game.id}`;

  return (
    <article
      className={cn(
        "group flex w-full flex-col overflow-hidden rounded-card border border-line bg-surface transition-colors hover:border-line-strong",
        className,
      )}
    >
      <div className="relative">
        {gameUrl ? (
          <Link href={gameUrl} data-track="click" tabIndex={-1} aria-hidden="true">
            <GameCover title={r.game.title} artworkUrl={r.game.artworkUrl} className="aspect-[16/9] w-full" />
          </Link>
        ) : (
          <GameCover title={r.game.title} artworkUrl={r.game.artworkUrl} className="aspect-[16/9] w-full" />
        )}
        <div className="absolute top-3 left-3 flex gap-1.5">
          {sample ? (
            <Badge tone="caution" className="bg-canvas/80 backdrop-blur">
              Sample
            </Badge>
          ) : null}
          <Badge tone="brand" className="bg-canvas/70 backdrop-blur">
            {CATEGORY_LABEL[r.category]}
          </Badge>
          {r.trendLabel ? (
            <Badge tone="caution" className="bg-canvas/70 backdrop-blur">
              <TrendingUp aria-hidden="true" />
              {r.trendLabel}
            </Badge>
          ) : null}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-4 p-5">
        <div>
          <h3 className="text-lg leading-snug font-semibold text-fg">
            {gameUrl ? (
              <Link href={gameUrl} data-track="click" className="hover:text-brand-300">
                {r.game.title}
              </Link>
            ) : (
              r.game.title
            )}
          </h3>
          <p className="mt-1 line-clamp-2 text-sm text-fg-muted">{r.game.tagline}</p>
        </div>

        <ScoreBadge score={r.score} kind={r.scoreKind} confidence={r.confidence} />

        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold tracking-wider text-fg-subtle uppercase">
            <Sparkles className="size-3.5" aria-hidden="true" />
            Why this game
          </p>
          <ul className="space-y-1 text-sm text-fg-muted">
            {r.reasons.map((reason) => (
              <li key={reason} className="flex gap-2">
                <span className="mt-2 size-1 shrink-0 rounded-full bg-brand-400" aria-hidden="true" />
                {reason}
              </li>
            ))}
          </ul>
          {r.cautions?.length ? (
            <ul className="mt-2 space-y-1 text-sm text-fg-muted">
              {r.cautions.map((c) => (
                <li key={c} className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-caution" aria-hidden="true" />
                  {c}
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        {r.breakdown ? <ScoreBreakdownDetails breakdown={r.breakdown} categoryScore={r.breakdown.rankingScore ?? r.score} /> : null}

        <ul className="flex flex-wrap gap-1.5" aria-label="Tags">
          {r.game.tags.slice(0, 4).map((tag) => (
            <li key={tag}>
              <Badge>{tag}</Badge>
            </li>
          ))}
        </ul>

        {sample ? null : <FeedbackBar compact />}

        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4 text-sm">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-fg-muted">
            {r.owned ? (
              <span className="inline-flex items-center gap-1 text-positive">
                <Check className="size-4" aria-hidden="true" />
                Owned
                {r.playtimeMinutes !== null ? (
                  <span className="text-fg-subtle">
                    · {formatPlaytime(r.playtimeMinutes)}
                    {r.lastPlayedDaysAgo !== null ? ` · ${formatDaysAgo(r.lastPlayedDaysAgo)}` : ""}
                  </span>
                ) : null}
              </span>
            ) : r.priceLabel ? (
              <span className="inline-flex items-center gap-1.5">
                {r.discountPct ? (
                  <Badge tone="positive">−{r.discountPct}%</Badge>
                ) : null}
                {r.originalPriceLabel ? (
                  <s className="text-fg-subtle">{r.originalPriceLabel}</s>
                ) : null}
                <span className="font-medium text-fg">{r.priceLabel}</span>
              </span>
            ) : null}
            {r.reviewLabel ? (
              <span className="inline-flex items-center gap-1">
                <Star className="size-3.5 text-caution" aria-hidden="true" />
                {r.reviewLabel}
              </span>
            ) : null}
          </div>
          {storeUrl ? (
            <a
              href={storeUrl}
              target="_blank"
              rel="noopener noreferrer"
              data-track={sample ? undefined : "store_visit"}
              className="inline-flex items-center gap-1 text-brand-300 hover:text-brand-400"
            >
              Steam Store <ExternalLink className="size-3.5" aria-hidden="true" />
            </a>
          ) : (
            <span className="text-xs text-fg-subtle">Store link unavailable</span>
          )}
        </div>
      </div>
    </article>
  );
}

export const PAGE_SIZE = 24;

export function RecommendationGrid({
  items,
  sample = false,
  limit,
  showAllHref,
  total,
  surface = "dashboard",
}: {
  items: Recommendation[];
  /** Size of the full list when ``items`` was fetched with a limit. */
  total?: number;
  sample?: boolean;
  surface?: Surface;
  /** Render only the first N (keeps pages light); offer a link to the rest. */
  limit?: number;
  showAllHref?: string;
}) {
  if (items.length === 0) {
    return (
      <p className="rounded-card border border-dashed border-line p-8 text-center text-fg-muted">
        Nothing to recommend here with these settings.
      </p>
    );
  }
  const shown = limit ? items.slice(0, limit) : items;
  return (
    <>
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((r) => (
          <RecommendationCard key={r.game.id} recommendation={r} sample={sample} surface={surface} />
        ))}
      </div>
      {showAllHref && shown.length < (total ?? items.length) ? (
        <p className="mt-6 text-center">
          <a href={showAllHref} className="text-sm text-brand-300 hover:text-brand-400">
            Show all {total ?? items.length}
          </a>
        </p>
      ) : null}
    </>
  );
}
