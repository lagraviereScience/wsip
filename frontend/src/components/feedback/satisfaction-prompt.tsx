"use client";

import { MessageCircleQuestion, X } from "lucide-react";
import { useEffect, useState } from "react";

import { RATINGS } from "@/components/feedback/feedback-context";
import { GameCover } from "@/components/games/game-cover";
import type { ApiSatisfactionPrompt } from "@/lib/api/types";
import { formatPlaytime } from "@/lib/utils";

type State =
  | { kind: "loading" }
  | { kind: "none" }
  | { kind: "ask"; prompt: ApiSatisfactionPrompt }
  | { kind: "thanks"; name: string }
  | { kind: "error"; prompt: ApiSatisfactionPrompt };

/**
 * "Did you enjoy X?" for one game you played after we recommended it. The server
 * decides whether to ask: at most one question at a time, one new question a week,
 * never about a game you snoozed (two weeks) or declined. Closing it counts as "Not now".
 */
export function SatisfactionPrompt() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/me/satisfaction-prompt");
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as { prompt: ApiSatisfactionPrompt | null };
        if (cancelled) return;
        if (!body.prompt) {
          setState({ kind: "none" });
          return;
        }
        setState({ kind: "ask", prompt: body.prompt });
        void post(body.prompt.game_id, "shown");
      } catch {
        if (!cancelled) setState({ kind: "none" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading" || state.kind === "none") return null;
  if (state.kind === "thanks") {
    return (
      <p className="mb-6 rounded-card border border-line bg-surface/60 px-4 py-3 text-sm text-fg-muted" role="status">
        Thanks! Your answer about {state.name} now shapes your recommendations.
      </p>
    );
  }
  const p = state.prompt;

  async function answer(rating: number) {
    try {
      const res = await fetch(`/api/me/games/${p.game_id}/satisfaction`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, source: "post_play" }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setState({ kind: "thanks", name: p.name });
    } catch {
      setState({ kind: "error", prompt: p });
    }
  }

  async function dismiss(action: "snooze" | "decline") {
    setState({ kind: "none" });
    await post(p.game_id, action);
  }

  return (
    <section
      aria-labelledby="satisfaction-question"
      className="mb-6 flex flex-wrap items-center gap-4 rounded-card border border-brand-400/30 bg-brand-500/10 p-4"
    >
      <GameCover title={p.name} artworkUrl={p.capsule_image_url} className="h-14 w-28 shrink-0 rounded-lg [&_span]:text-base" />
      <div className="min-w-56 flex-1">
        <h2 id="satisfaction-question" className="flex items-center gap-2 font-medium text-fg">
          <MessageCircleQuestion className="size-4 text-brand-300" aria-hidden="true" />
          {p.question}
        </h2>
        <p className="text-xs text-fg-subtle">
          You&apos;ve played it for {formatPlaytime(p.minutes_since_recommended)} since we recommended
          it. Your answer is the best signal we get.
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {RATINGS.map((r) => (
            <button
              key={r.value}
              type="button"
              onClick={() => answer(r.value)}
              className="rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-fg hover:bg-surface-hover"
            >
              {r.label}
            </button>
          ))}
          <button type="button" onClick={() => dismiss("decline")} className="px-2 py-1 text-xs text-fg-subtle hover:text-fg">
            Don&apos;t ask about this game
          </button>
        </div>
        {state.kind === "error" ? (
          <p className="mt-1 text-xs text-negative" role="alert">
            Couldn&apos;t save your answer. Please try again.
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => dismiss("snooze")}
        aria-label="Not now"
        title="Not now"
        className="self-start rounded-lg p-1 text-fg-subtle hover:bg-surface-hover hover:text-fg"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </section>
  );
}

async function post(gameId: number, action: "shown" | "snooze" | "decline"): Promise<void> {
  try {
    await fetch(`/api/me/satisfaction-prompt/${gameId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
  } catch {
    // Best effort.
  }
}
