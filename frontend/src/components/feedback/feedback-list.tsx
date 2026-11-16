"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { FeedbackBar } from "@/components/feedback/feedback-bar";
import { FeedbackScope, RATINGS, useGameFeedback } from "@/components/feedback/feedback-context";
import { GameCover } from "@/components/games/game-cover";
import type { ApiFeedbackGame } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "positive", label: "Liked & favourites" },
  { key: "saved", label: "Saved" },
  { key: "hidden", label: "Hidden" },
  { key: "rated", label: "Rated" },
] as const;
type Filter = (typeof FILTERS)[number]["key"];

function matches(g: ApiFeedbackGame, f: Filter): boolean {
  switch (f) {
    case "positive":
      return g.favourite || g.reaction === "like";
    case "saved":
      return g.saved;
    case "hidden":
      return !!g.dismissal || g.reaction === "dislike" || g.already_played || (g.rating ?? 0) < 0;
    case "rated":
      return g.rating !== null;
    default:
      return true;
  }
}

const REASON_LABEL: Record<string, string> = {
  price: "too expensive",
  timing: "not right now",
  owned_elsewhere: "owned elsewhere",
  other: "not interested",
};

function Summary() {
  const api = useGameFeedback();
  if (!api) return null;
  const f = api.feedback;
  const parts: string[] = [];
  if (f.favourite) parts.push("Favourite");
  if (f.reaction === "like") parts.push("Liked");
  if (f.reaction === "dislike") parts.push("Disliked");
  if (f.saved) parts.push("Saved for later");
  if (f.dismissal === "not_my_type") parts.push("Not my type");
  if (f.dismissal === "not_interested")
    parts.push(`Not interested${f.dismissal_reason ? ` (${REASON_LABEL[f.dismissal_reason]})` : ""}`);
  if (f.already_played) parts.push("Already played");
  const rating = RATINGS.find((r) => r.value === f.rating);
  return (
    <p className="text-xs text-fg-subtle">
      {parts.length ? parts.join(" · ") : "No feedback"}
      {rating ? ` · ${rating.label}` : ""}
      {rating ? (
        <button
          type="button"
          onClick={() => api.rate(null, "post_play")}
          disabled={api.busy}
          className="ml-2 text-brand-300 hover:text-brand-400"
        >
          Clear rating
        </button>
      ) : null}
    </p>
  );
}

/** Everything you told us about specific games, to review, change or undo. */
export function FeedbackList({ games }: { games: ApiFeedbackGame[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const shown = useMemo(() => games.filter((g) => matches(g, filter)), [games, filter]);
  if (games.length === 0) {
    return (
      <p className="text-sm text-fg-muted">
        Nothing yet. Use the buttons on recommendation cards to like, save or hide games.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "rounded-lg border px-2.5 py-1 text-xs",
              filter === f.key ? "border-brand-400/50 bg-brand-500/20 text-brand-200" : "border-line text-fg-muted hover:text-fg",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>
      <ul className="divide-y divide-line">
        {shown.map((g) => (
          <li key={g.game_id} className="py-3">
            <FeedbackScope gameId={g.game_id} title={g.name} initial={g} surface="profile" trackImpression={false}>
              <div className="flex flex-wrap items-center gap-4">
                <GameCover title={g.name} artworkUrl={g.capsule_image_url} className="h-11 w-20 shrink-0 rounded-lg [&_span]:text-base" />
                <div className="min-w-44 flex-1">
                  <Link href={`/games/${g.game_id}`} className="text-sm font-medium text-fg hover:text-brand-300">
                    {g.name}
                  </Link>
                  <Summary />
                </div>
                <FeedbackBar compact />
              </div>
            </FeedbackScope>
          </li>
        ))}
      </ul>
    </div>
  );
}
