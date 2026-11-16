import { Info } from "lucide-react";

import { RefreshRecommendationsButton } from "@/components/recommendations/refresh-button";
import type { RecommendationList } from "@/lib/types";

function formatUtc(iso: string): string {
  return `${new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" })} UTC`;
}

/** When the list was generated, what was left out and why, and a rebuild control. */
export function ListStatus({ list, children }: { list: RecommendationList; children?: React.ReactNode }) {
  if (!list.generatedAt) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 text-sm text-fg-subtle">
      <div className="space-y-1">
        <p>
          Generated {formatUtc(list.generatedAt)}{" "}
          {list.scoringMode === "classic"
            ? "with classic scoring: a fixed formula over your profile and each game's features, with no machine learning. “Match” is a compatibility score, not a probability."
            : list.scoreKind === "calibrated_satisfaction"
            ? "and ranked by predicted enjoyment: a calibrated probability from the satisfaction model, checked against players' real ratings before it was used."
            : list.algorithm?.includes("+cf")
              ? "from your profile and players with similar libraries. “Match” is a compatibility score, not a probability."
              : "from your profile (content-based). “Match” is a compatibility score, not a probability."}
        </p>
        {list.note ? (
          <p className="flex items-start gap-1.5">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {list.note}
          </p>
        ) : null}
        {list.filteredOut ? <p>{list.filteredOut} hidden by your filters.</p> : null}
        {children}
      </div>
      <RefreshRecommendationsButton />
    </div>
  );
}
