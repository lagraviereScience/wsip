"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const POLL_MS = 4000;
const MAX_POLLS = 45; // about three minutes

/** Shown while the first profile and recommendations are being built; re-renders until ready. */
export function PendingRefresher({ what = "recommendations" }: { what?: string }) {
  const router = useRouter();
  const [polls, setPolls] = useState(0);
  const gaveUp = polls >= MAX_POLLS;

  useEffect(() => {
    if (gaveUp) return;
    const id = window.setTimeout(() => {
      setPolls((n) => n + 1);
      router.refresh();
    }, POLL_MS);
    return () => window.clearTimeout(id);
  }, [polls, gaveUp, router]);

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-start gap-3 rounded-card border border-line bg-surface p-6"
    >
      <Loader2
        className={gaveUp ? "mt-0.5 size-5 text-fg-subtle" : "mt-0.5 size-5 animate-spin text-brand-400"}
        aria-hidden="true"
      />
      <div>
        <p className="font-medium text-fg">
          {gaveUp ? `Your ${what} are taking longer than usual.` : `Building your ${what}…`}
        </p>
        <p className="mt-1 text-sm text-fg-muted">
          {gaveUp
            ? "Reload the page in a minute. If it keeps happening, the background worker may be down."
            : "We analyse your library, work out your preferences and look for matching games on Steam. This usually takes under a minute."}
        </p>
      </div>
    </div>
  );
}
