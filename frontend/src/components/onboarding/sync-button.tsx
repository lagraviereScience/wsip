"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";

export function SyncButton() {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "pending" | "queued" | "error">("idle");
  return (
    <div className="flex items-center gap-3">
      {state === "queued" ? <span className="text-sm text-fg-muted">Import queued</span> : null}
      {state === "error" ? <span className="text-sm text-negative">Couldn&apos;t start import</span> : null}
      <Button
        variant="secondary"
        disabled={state === "pending"}
        onClick={async () => {
          setState("pending");
          const res = await fetch("/api/me/steam/sync", { method: "POST" });
          if (res.status === 409) {
            // Sign-in-only mode: there is nothing to sync; show the current page.
            setState("idle");
            router.refresh();
            return;
          }
          setState(res.ok ? "queued" : "error");
          if (res.ok) router.push("/onboarding");
        }}
      >
        <RefreshCw className={state === "pending" ? "animate-spin" : undefined} aria-hidden="true" />
        Sync now
      </Button>
    </div>
  );
}
