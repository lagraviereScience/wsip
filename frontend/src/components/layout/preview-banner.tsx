import { FlaskConical } from "lucide-react";

import type { DataSource } from "@/lib/types";

const MESSAGES = {
  full: {
    title: "Preview with sample data.",
    body: "The games, scores and playtimes on this page are invented placeholders. Sign in through Steam to see your own library.",
  },
  recommendations: {
    title: "Recommendations are coming soon.",
    body: "Cards marked Sample are invented placeholders. Your library, playtime and sync status are real.",
  },
} as const;

/** Shown whenever a page renders mock data, so placeholders never pass as real. */
export function PreviewBanner({
  source,
  variant = "full",
}: {
  source: DataSource;
  variant?: keyof typeof MESSAGES;
}) {
  if (source !== "mock") return null;
  const m = MESSAGES[variant];
  return (
    <div
      role="note"
      className="mb-6 flex items-start gap-3 rounded-xl border border-caution/30 bg-caution/10 px-4 py-3 text-sm text-fg"
    >
      <FlaskConical className="mt-0.5 size-4 shrink-0 text-caution" aria-hidden="true" />
      <p>
        <span className="font-semibold">{m.title}</span>{" "}
        <span className="text-fg-muted">{m.body}</span>
      </p>
    </div>
  );
}
