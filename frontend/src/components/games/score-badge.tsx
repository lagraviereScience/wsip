import type { Confidence, ScoreKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  low: "Low confidence",
  medium: "Medium confidence",
  high: "High confidence",
};

const CONFIDENCE_DOTS: Record<Confidence, number> = { low: 1, medium: 2, high: 3 };

/**
 * Displays a 0–100 score. An uncalibrated score is labelled "Match" and never
 * shown as a percentage, so it cannot be read as a probability of enjoyment.
 */
export function ScoreBadge({
  score,
  kind,
  confidence,
}: {
  score: number;
  kind: ScoreKind;
  confidence: Confidence;
}) {
  const label = kind === "calibrated_satisfaction" ? "Predicted enjoyment" : "Match";
  // A probability never reads as exactly 0% or 100%: below 1% shows "<1%".
  const pct = Math.round(score);
  const value =
    kind === "calibrated_satisfaction"
      ? score < 1 ? "<1%" : score > 99 ? ">99%" : `${pct}%`
      : Math.round(score);
  return (
    <div
      className="flex items-center gap-3"
      aria-label={`${label} ${value}, ${CONFIDENCE_LABEL[confidence].toLowerCase()}`}
    >
      <div className="flex flex-col items-center rounded-xl border border-signal-500/30 bg-signal-500/10 px-2.5 py-1">
        <span className="font-display text-xl leading-none font-bold text-signal-300">{value}</span>
        <span className="mt-0.5 text-[10px] font-medium tracking-wider text-signal-400 uppercase">
          {label}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="flex gap-1" aria-hidden="true">
          {[1, 2, 3].map((i) => (
            <span
              key={i}
              className={cn(
                "h-1.5 w-4 rounded-full",
                i <= CONFIDENCE_DOTS[confidence] ? "bg-signal-400" : "bg-line-strong",
              )}
            />
          ))}
        </span>
        <span className="text-xs text-fg-subtle">{CONFIDENCE_LABEL[confidence]}</span>
      </div>
    </div>
  );
}
