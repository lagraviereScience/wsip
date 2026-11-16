import { Hand } from "lucide-react";

import type { ScoreBreakdown } from "@/lib/types";
import { cn } from "@/lib/utils";

function signed(points: number): string {
  const v = Math.round(points * 10) / 10;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

/**
 * The exact score decomposition: every row is a canonical feature's contribution
 * in score points, and they add up to the Match score minus the neutral 50.
 * Uses <details> so it works without client JavaScript.
 */
export function ScoreBreakdownDetails({
  breakdown: b,
  categoryScore,
}: {
  breakdown: ScoreBreakdown;
  categoryScore: number;
}) {
  const rows = b.contributions.filter((c) => Math.abs(c.points) >= 0.05).slice(0, 10);
  return (
    <details className="group/details rounded-lg border border-line bg-canvas/40 text-sm">
      <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-fg-muted marker:hidden hover:text-fg">
        Why this score
        <span className="ml-1 text-fg-subtle group-open/details:hidden">(show)</span>
      </summary>
      <div className="space-y-3 border-t border-line px-3 py-3">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {b.predictedSatisfaction !== null && b.predictedSatisfaction !== undefined ? (
            <>
              <dt className="text-fg-subtle">Predicted enjoyment</dt>
              <dd className="text-right font-medium text-fg">{Math.round(b.predictedSatisfaction)}%</dd>
            </>
          ) : null}
          <dt className="text-fg-subtle">Match (content)</dt>
          <dd className="text-right text-fg">{Math.round(b.matchScore)}</dd>
          {b.collaborativeScore !== null && b.collaborativeScore !== undefined ? (
            <>
              <dt className="text-fg-subtle">Players with similar libraries</dt>
              <dd className="text-right text-fg">{Math.round(b.collaborativeScore)}th pct.</dd>
            </>
          ) : null}
          {b.backlogScore !== null ? (
            <>
              <dt className="text-fg-subtle">Backlog</dt>
              <dd className="text-right text-fg">{Math.round(b.backlogScore)}</dd>
            </>
          ) : null}
          {b.trendScore !== null ? (
            <>
              <dt className="text-fg-subtle">Trend</dt>
              <dd className="text-right text-fg">{Math.round(b.trendScore)}</dd>
            </>
          ) : null}
          <dt className="text-fg-subtle">Ranking score</dt>
          <dd className="text-right font-medium text-fg">{Math.round(categoryScore)}</dd>
          <dt className="text-fg-subtle">Metadata confidence</dt>
          <dd className="text-right text-fg">{Math.round(b.metadataConfidence * 100)}%</dd>
        </dl>

        <div>
          <p className="mb-1 text-xs font-semibold text-fg-subtle">By category (50 = neutral)</p>
          <ul className="space-y-0.5 text-xs">
            {b.groups.map((g) => (
              <li key={g.group} className="flex justify-between gap-2">
                <span className="text-fg-muted">
                  {g.label} <span className="text-fg-subtle">· {Math.round(g.weight * 100)}%</span>
                </span>
                <span className="text-fg">{g.score === null ? "unknown" : Math.round(g.score)}</span>
              </li>
            ))}
          </ul>
        </div>

        {rows.length ? (
          <div>
            <p className="mb-1 text-xs font-semibold text-fg-subtle">Features (points)</p>
            <ul className="space-y-0.5 text-xs">
              {rows.map((c) => (
                <li key={c.feature} className="flex justify-between gap-2">
                  <span className="inline-flex items-center gap-1 text-fg-muted">
                    {c.name}
                    {c.origin === "manual" ? (
                      <Hand className="size-3 text-brand-300" aria-label="your setting" />
                    ) : null}
                  </span>
                  <span className={cn(c.points >= 0 ? "text-positive" : "text-negative")}>
                    {signed(c.points)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-fg-subtle">
            No known preferences match this game yet, so it scores neutral.
          </p>
        )}
      </div>
    </details>
  );
}
