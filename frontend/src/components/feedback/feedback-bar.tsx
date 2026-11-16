"use client";

import { Bookmark, ChevronDown, Heart, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { RATINGS, useGameFeedback } from "@/components/feedback/feedback-context";
import type { DismissalReason } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const REASONS: { value: DismissalReason; label: string }[] = [
  { value: "price", label: "Too expensive" },
  { value: "timing", label: "Not right now" },
  { value: "owned_elsewhere", label: "I own it elsewhere" },
  { value: "other", label: "Just not interested" },
];

function Toggle({
  pressed,
  onClick,
  label,
  children,
  tone = "brand",
  disabled,
}: {
  pressed: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
  tone?: "brand" | "negative" | "caution";
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-lg border transition-colors [&_svg]:size-4",
        pressed
          ? tone === "negative"
            ? "border-negative/40 bg-negative/15 text-negative"
            : tone === "caution"
              ? "border-caution/40 bg-caution/15 text-caution"
              : "border-brand-400/50 bg-brand-500/20 text-brand-200"
          : "border-line text-fg-subtle hover:bg-surface-hover hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

/**
 * Like, Dislike, Favourite, Save for later, and under "More": Not interested (with
 * a reason, so a price rejection is never read as a gameplay dislike), Not my type
 * and Already played (with an optional "Did you enjoy it?"). Every control toggles:
 * pressing it again undoes it.
 */
export function FeedbackBar({ compact = false }: { compact?: boolean }) {
  const api = useGameFeedback();
  const [open, setOpen] = useState<null | "menu" | "reason" | "rating">(null);
  if (!api) return null;
  const f = api.feedback;
  const busy = api.busy;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={`Your feedback on ${api.title}`}>
        <Toggle pressed={f.reaction === "like"} label="Like" onClick={() => api.set("like", f.reaction !== "like")} disabled={busy}>
          <ThumbsUp aria-hidden="true" />
        </Toggle>
        <Toggle
          pressed={f.reaction === "dislike"}
          label="Dislike"
          tone="negative"
          onClick={() => api.set("dislike", f.reaction !== "dislike")}
          disabled={busy}
        >
          <ThumbsDown aria-hidden="true" />
        </Toggle>
        <Toggle pressed={f.favourite} label="Favourite" tone="caution" onClick={() => api.set("favourite", !f.favourite)} disabled={busy}>
          <Heart aria-hidden="true" className={f.favourite ? "fill-current" : undefined} />
        </Toggle>
        <Toggle pressed={f.saved} label="Save for later" onClick={() => api.set("save_for_later", !f.saved)} disabled={busy}>
          <Bookmark aria-hidden="true" className={f.saved ? "fill-current" : undefined} />
        </Toggle>
        <button
          type="button"
          aria-expanded={open !== null}
          onClick={() => setOpen(open ? null : "menu")}
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-line px-2.5 text-xs text-fg-subtle hover:bg-surface-hover hover:text-fg"
        >
          More <ChevronDown className="size-3.5" aria-hidden="true" />
        </button>
      </div>

      {open === "menu" ? (
        <div className="flex flex-wrap gap-1.5 text-xs">
          <MenuButton pressed={f.dismissal === "not_interested"} onClick={() =>
            f.dismissal === "not_interested" ? api.set("not_interested", false).then(() => setOpen(null)) : setOpen("reason")
          } disabled={busy}>
            Not interested
          </MenuButton>
          <MenuButton pressed={f.dismissal === "not_my_type"} onClick={() => api.set("not_my_type", f.dismissal !== "not_my_type").then(() => setOpen(null))} disabled={busy}>
            Not my type
          </MenuButton>
          <MenuButton
            pressed={f.already_played}
            onClick={() =>
              f.already_played
                ? api.set("already_played", false).then(() => setOpen(null))
                : setOpen("rating")
            }
            disabled={busy}
          >
            Already played
          </MenuButton>
        </div>
      ) : null}

      {open === "reason" ? (
        <fieldset className="space-y-1.5 text-xs">
          <legend className="mb-1 text-fg-subtle">Why? (Price or timing won&apos;t count against games like it.)</legend>
          <div className="flex flex-wrap gap-1.5">
            {REASONS.map((r) => (
              <MenuButton key={r.value} pressed={false} disabled={busy} onClick={() => api.set("not_interested", true, r.value).then(() => setOpen(null))}>
                {r.label}
              </MenuButton>
            ))}
          </div>
        </fieldset>
      ) : null}

      {open === "rating" ? (
        <fieldset className="space-y-1.5 text-xs">
          <legend className="mb-1 text-fg-subtle">Did you enjoy it?</legend>
          <div className="flex flex-wrap gap-1.5">
            {RATINGS.map((r) => (
              <MenuButton
                key={r.value}
                pressed={false}
                disabled={busy}
                onClick={async () => {
                  await api.set("already_played", true);
                  await api.rate(r.value, "already_played");
                  setOpen(null);
                }}
              >
                {r.label}
              </MenuButton>
            ))}
            <MenuButton pressed={false} disabled={busy} onClick={() => api.set("already_played", true).then(() => setOpen(null))}>
              Skip
            </MenuButton>
          </div>
        </fieldset>
      ) : null}

      {!compact && f.rating !== null ? (
        <p className="text-xs text-fg-subtle">
          Your rating: {RATINGS.find((r) => r.value === f.rating)?.label ?? f.rating}
        </p>
      ) : null}
      {api.error ? <p className="text-xs text-negative" role="alert">{api.error}</p> : null}
    </div>
  );
}

function MenuButton({
  pressed,
  onClick,
  disabled,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-lg border px-2.5 py-1",
        pressed ? "border-brand-400/50 bg-brand-500/20 text-brand-200" : "border-line text-fg-muted hover:bg-surface-hover hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}
