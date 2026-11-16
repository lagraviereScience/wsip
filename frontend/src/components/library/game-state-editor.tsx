"use client";

import { Check } from "lucide-react";
import { useState } from "react";

import { RatingPicker } from "@/components/library/rating-picker";
import type { Rating } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export interface GameState {
  owned: boolean;
  rating: Rating | null;
}

/** Saves "I own it" and the rating for one game (PUT /api/me/library/games/{appid}). */
export function GameStateEditor({
  appid,
  name,
  initial,
  onSaved,
  ownedLocked = false,
}: {
  appid: number;
  name: string;
  initial: GameState;
  onSaved?: (state: GameState, previous: GameState) => void;
  /** Ownership imported from Steam can't be changed by hand. */
  ownedLocked?: boolean;
}) {
  const [state, setState] = useState(initial);
  const [status, setStatus] = useState<"idle" | "saving" | "error">("idle");

  const save = async (next: GameState) => {
    const previous = state;
    setState(next);
    setStatus("saving");
    try {
      const res = await fetch(`/api/me/library/games/${appid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next),
      });
      if (!res.ok) throw new Error(String(res.status));
      setStatus("idle");
      onSaved?.(next, previous);
    } catch {
      setState(previous);
      setStatus("error");
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <label
          className={cn(
            "inline-flex items-center gap-2 text-sm",
            ownedLocked ? "text-fg-subtle" : "cursor-pointer text-fg",
          )}
        >
          <input
            type="checkbox"
            className="size-4 accent-brand-500"
            checked={state.owned}
            disabled={ownedLocked || status === "saving"}
            onChange={(e) => save({ ...state, owned: e.target.checked })}
          />
          I own it on Steam
        </label>
        {status === "saving" ? <span className="text-xs text-fg-subtle">Saving…</span> : null}
        {status === "error" ? (
          <span className="text-xs text-negative">Couldn&apos;t save. Try again.</span>
        ) : null}
        {status === "idle" && (state.owned || state.rating !== null) ? (
          <span className="inline-flex items-center gap-1 text-xs text-positive">
            <Check className="size-3" aria-hidden="true" /> In your library
          </span>
        ) : null}
      </div>
      <RatingPicker
        gameName={name}
        value={state.rating}
        disabled={status === "saving"}
        onChange={(rating) => save({ ...state, rating })}
      />
    </div>
  );
}
