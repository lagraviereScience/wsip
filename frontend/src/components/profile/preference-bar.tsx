import { Hand, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { FeaturePreference } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A diverging bar for a −1 … +1 preference, with its confidence and origin. */
export function PreferenceBar({ preference: p }: { preference: FeaturePreference }) {
  const pct = Math.round(Math.abs(p.value) * 50);
  const positive = p.value >= 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-fg">{p.feature}</p>
          <p className="truncate text-xs text-fg-subtle">{p.category}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-fg-subtle">{Math.round(p.confidence * 100)}% sure</span>
          {p.origin === "manual" ? (
            <Badge tone="brand">
              <Hand aria-hidden="true" /> Manual
            </Badge>
          ) : (
            <Badge>
              <Sparkles aria-hidden="true" /> Inferred
            </Badge>
          )}
        </div>
      </div>
      <div
        className="relative h-2 rounded-full bg-surface-raised"
        role="meter"
        aria-label={`${p.feature} preference`}
        aria-valuemin={-1}
        aria-valuemax={1}
        aria-valuenow={p.value}
      >
        <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" aria-hidden="true" />
        <span
          className={cn(
            "absolute inset-y-0",
            positive
              ? "left-1/2 rounded-r-full bg-gradient-to-r from-brand-500 to-signal-400"
              : "right-1/2 rounded-l-full bg-negative/80",
          )}
          style={{ width: `${pct}%`, opacity: 0.45 + p.confidence * 0.55 }}
        />
      </div>
    </div>
  );
}
