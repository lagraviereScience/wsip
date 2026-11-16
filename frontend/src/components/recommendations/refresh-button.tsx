"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";

const SETTLE_MS = 20_000;

/** Rebuild profile and recommendations now (the server allows one rebuild per minute). */
export function RefreshRecommendationsButton() {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "working" | "limited" | "error">("idle");

  async function refresh() {
    setState("working");
    try {
      const res = await fetch("/api/me/recommendations/refresh", { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      const body = (await res.json()) as { queued: boolean };
      if (!body.queued) {
        setState("limited");
        return;
      }
      window.setTimeout(() => {
        router.refresh();
        setState("idle");
      }, SETTLE_MS);
    } catch {
      setState("error");
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button variant="secondary" size="sm" onClick={refresh} disabled={state === "working"}>
        <RefreshCw className={state === "working" ? "animate-spin" : undefined} aria-hidden="true" />
        {state === "working" ? "Rebuilding…" : "Rebuild"}
      </Button>
      <span className="text-xs text-fg-subtle" aria-live="polite">
        {state === "limited" ? "Already rebuilt in the last minute." : null}
        {state === "error" ? "Couldn't start a rebuild." : null}
      </span>
    </div>
  );
}
