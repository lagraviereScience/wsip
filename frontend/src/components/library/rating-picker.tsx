"use client";

import { RATINGS, type Rating } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const TONE: Record<Rating, string> = {
  2: "data-[on=true]:border-positive/60 data-[on=true]:bg-positive/15 data-[on=true]:text-positive",
  1: "data-[on=true]:border-signal-500/60 data-[on=true]:bg-signal-500/15 data-[on=true]:text-signal-300",
  0: "data-[on=true]:border-line-strong data-[on=true]:bg-surface-hover data-[on=true]:text-fg",
  [-1]: "data-[on=true]:border-caution/60 data-[on=true]:bg-caution/15 data-[on=true]:text-caution",
  [-2]: "data-[on=true]:border-negative/60 data-[on=true]:bg-negative/15 data-[on=true]:text-negative",
};

/** "Did you enjoy this game?" on the spec §18 five-level scale, plus "Not played yet". */
export function RatingPicker({
  value,
  onChange,
  disabled = false,
  gameName,
}: {
  value: Rating | null;
  onChange: (rating: Rating | null) => void;
  disabled?: boolean;
  gameName: string;
}) {
  const options: { value: Rating | null; label: string }[] = [
    ...RATINGS,
    { value: null, label: "Not played yet" },
  ];
  return (
    <div role="radiogroup" aria-label={`Did you enjoy ${gameName}?`} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value === o.value;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={on}
            data-on={on}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={cn(
              "rounded-full border border-line px-2.5 py-1 text-xs text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50",
              o.value === null
                ? "data-[on=true]:border-line-strong data-[on=true]:bg-surface-hover data-[on=true]:text-fg"
                : TONE[o.value],
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
