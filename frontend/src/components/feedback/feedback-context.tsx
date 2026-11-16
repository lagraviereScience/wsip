"use client";

import { Undo2 } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { ApiGameFeedback, DismissalReason, FeedbackKind } from "@/lib/api/types";
import { pageViewId, trackEvent, type Surface } from "@/lib/events";
import type { Exposure } from "@/lib/types";

export const EMPTY_FEEDBACK = (gameId: number): ApiGameFeedback => ({
  game_id: gameId,
  reaction: null,
  favourite: false,
  saved: false,
  dismissal: null,
  dismissal_reason: null,
  already_played: false,
  rating: null,
  rating_source: null,
});

export const RATINGS: { value: number; label: string }[] = [
  { value: 2, label: "Loved it" },
  { value: 1, label: "Liked it" },
  { value: 0, label: "Neutral" },
  { value: -1, label: "Disliked it" },
  { value: -2, label: "Hated it" },
];

const REJECT_LABEL: Record<string, string> = {
  dislike: "You disliked this game",
  not_interested: "Marked not interested",
  not_my_type: "Marked not your type",
  already_played: "Marked as already played",
  rated_negative: "You didn't enjoy this game",
};

/** Why the game should leave recommendation lists, if it should. Mirrors the server. */
export function rejection(f: ApiGameFeedback): string | null {
  if (f.dismissal) return f.dismissal;
  if (f.reaction === "dislike") return "dislike";
  if (f.already_played) return "already_played";
  if (f.rating !== null && f.rating < 0) return "rated_negative";
  return null;
}

/** Turning one kind on also switches off contradicting kinds (as the server does). */
export function applyLocally(f: ApiGameFeedback, kind: FeedbackKind, on: boolean, reason?: DismissalReason | null): ApiGameFeedback {
  const n = { ...f };
  if (kind === "like" || kind === "dislike") n.reaction = on ? kind : f.reaction === kind ? null : f.reaction;
  if (kind === "favourite") n.favourite = on;
  if (kind === "save_for_later") n.saved = on;
  if (kind === "not_interested" || kind === "not_my_type") {
    if (on) {
      n.dismissal = kind;
      n.dismissal_reason = kind === "not_interested" ? (reason ?? null) : null;
    } else if (f.dismissal === kind) {
      n.dismissal = null;
      n.dismissal_reason = null;
    }
  }
  if (kind === "already_played") n.already_played = on;
  if (on) {
    if ((kind === "like" || kind === "favourite" || kind === "save_for_later") && n.dismissal) {
      n.dismissal = null;
      n.dismissal_reason = null;
    }
    if ((kind === "favourite" || kind === "save_for_later") && n.reaction === "dislike") n.reaction = null;
    if (kind === "dislike" || kind === "not_my_type") {
      n.favourite = false;
      n.saved = false;
      if (kind === "not_my_type" && n.reaction === "like") n.reaction = null;
    }
    if (kind === "not_interested" || kind === "already_played") n.saved = false;
  }
  return n;
}

interface FeedbackApi {
  gameId: number;
  title: string;
  feedback: ApiGameFeedback;
  busy: boolean;
  error: string | null;
  set: (kind: FeedbackKind, on: boolean, reason?: DismissalReason | null) => Promise<void>;
  rate: (rating: number | null, source: "post_play" | "already_played") => Promise<void>;
}

const Ctx = createContext<FeedbackApi | null>(null);

export function useGameFeedback(): FeedbackApi | null {
  return useContext(Ctx);
}

interface Props {
  gameId: number;
  title: string;
  initial: ApiGameFeedback | null;
  exposure?: Exposure | null;
  surface: Surface;
  /** In recommendation lists a rejected game collapses into an "Undo" row. */
  hideWhenRejected?: boolean;
  /** Record an impression once the element has been at least half visible for 1 s. */
  trackImpression?: boolean;
  className?: string;
  children: ReactNode;
}

const VISIBLE_RATIO = 0.5;
const VISIBLE_MS = 1000;

/**
 * Wraps a recommendation card (or the game page): records real visibility
 * (impressions), clicks on links marked `data-track`, and owns the feedback state
 * the controls inside it read and change.
 */
export function FeedbackScope({
  gameId,
  title,
  initial,
  exposure = null,
  surface,
  hideWhenRejected = false,
  trackImpression = true,
  className,
  children,
}: Props) {
  const [feedback, setFeedback] = useState<ApiGameFeedback>(initial ?? EMPTY_FEEDBACK(gameId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const context = useMemo(
    () => (exposure ? { recommendation_run_id: exposure.runId, position: exposure.position } : {}),
    [exposure],
  );

  useEffect(() => {
    const el = ref.current;
    if (!trackImpression || !exposure || !el || typeof IntersectionObserver === "undefined") return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.intersectionRatio >= VISIBLE_RATIO) {
          timer ??= setTimeout(() => {
            trackEvent({
              type: "impression",
              game_id: gameId,
              idempotency_key: `imp:${pageViewId}:${exposure.runId}:${gameId}`,
              surface,
              ...context,
              context: { visible_ms: VISIBLE_MS },
            });
            observer.disconnect();
          }, VISIBLE_MS);
        } else if (timer) {
          clearTimeout(timer);
          timer = null;
        }
      },
      { threshold: [0, VISIBLE_RATIO, 1] },
    );
    observer.observe(el);
    return () => {
      if (timer) clearTimeout(timer);
      observer.disconnect();
    };
  }, [trackImpression, exposure, gameId, surface, context]);

  const onClickCapture = useCallback(
    (e: React.MouseEvent) => {
      const link = (e.target as HTMLElement).closest<HTMLElement>("[data-track]");
      const kind = link?.dataset.track;
      if (kind !== "click" && kind !== "store_visit") return;
      trackEvent({
        type: kind,
        game_id: gameId,
        idempotency_key: `${kind}:${pageViewId}:${gameId}:${Date.now()}`,
        surface,
        ...context,
      });
    },
    [gameId, surface, context],
  );

  const send = useCallback(
    async (url: string, body: object, optimistic: ApiGameFeedback) => {
      const previous = feedback;
      setFeedback(optimistic);
      setBusy(true);
      setError(null);
      try {
        const res = await fetch(url, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, ...context, surface }),
        });
        if (!res.ok) throw new Error(String(res.status));
        setFeedback((await res.json()) as ApiGameFeedback);
      } catch {
        setFeedback(previous);
        setError("Couldn't save that. Please try again.");
      } finally {
        setBusy(false);
      }
    },
    [feedback, context, surface],
  );

  const api = useMemo<FeedbackApi>(
    () => ({
      gameId,
      title,
      feedback,
      busy,
      error,
      set: (kind, on, reason = null) =>
        send(
          `/api/me/games/${gameId}/feedback/${kind}`,
          kind === "not_interested" && on && reason ? { on, reason } : { on },
          applyLocally(feedback, kind, on, reason),
        ),
      rate: (rating, source) =>
        send(`/api/me/games/${gameId}/satisfaction`, { rating, source }, {
          ...feedback,
          rating,
          rating_source: rating === null ? null : source,
        }),
    }),
    [gameId, title, feedback, busy, error, send],
  );

  const rejected = rejection(feedback);
  if (hideWhenRejected && rejected) {
    return (
      <Ctx.Provider value={api}>
        <div className="flex flex-col items-start justify-between gap-3 rounded-card border border-dashed border-line bg-surface/50 p-5 text-sm">
          <div>
            <p className="font-medium text-fg">{title}</p>
            <p className="text-fg-muted">
              {REJECT_LABEL[rejected]}. We won&apos;t recommend it again
              {rejected === "not_interested" || rejected === "already_played"
                ? "."
                : ", and similar games count a little less."}
            </p>
          </div>
          <UndoButton />
          {error ? <p className="text-negative">{error}</p> : null}
        </div>
      </Ctx.Provider>
    );
  }
  return (
    <Ctx.Provider value={api}>
      <div ref={ref} onClickCapture={onClickCapture} className={className}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

function UndoButton() {
  const api = useGameFeedback();
  if (!api) return null;
  const f = api.feedback;
  async function undo() {
    if (!api) return;
    if (f.dismissal) await api.set(f.dismissal, false);
    else if (f.reaction === "dislike") await api.set("dislike", false);
    else if (f.already_played) await api.set("already_played", false);
    if (f.rating !== null && f.rating < 0) await api.rate(null, "post_play");
  }
  return (
    <button
      type="button"
      onClick={undo}
      disabled={api.busy}
      className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-fg hover:bg-surface-hover"
    >
      <Undo2 className="size-4" aria-hidden="true" /> Undo
    </button>
  );
}
