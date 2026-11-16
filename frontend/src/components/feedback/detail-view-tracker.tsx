"use client";

import { useEffect } from "react";

import { pageViewId, trackEvent } from "@/lib/events";

/** Records one game page view per page load, linked to the latest recommendation. */
export function DetailViewTracker({
  gameId,
  runId,
  position,
}: {
  gameId: number;
  runId: number | null;
  position: number | null;
}) {
  useEffect(() => {
    trackEvent({
      type: "detail_view",
      game_id: gameId,
      idempotency_key: `view:${pageViewId}:${gameId}`,
      surface: "game_page",
      ...(runId ? { recommendation_run_id: runId } : {}),
      ...(position ? { position } : {}),
    });
  }, [gameId, runId, position]);
  return null;
}
