/**
 * Behavioural events from the browser: impressions, clicks, game page views and
 * Steam Store visits (spec §21). Everything else (likes, ratings...) is recorded by
 * the server as part of the action itself.
 *
 * - Events are queued and sent in batches (every few seconds, or when the page is
 *   hidden, with `keepalive` so they survive navigation).
 * - Every event carries an idempotency key, so retries are stored once.
 * - Impression keys include a per-page-view id: the same card seen twice in one
 *   visit is one impression; seen again on a later visit, it is a new one.
 * - Nothing is sent for signed-out previews (sample data has no exposure).
 */

export type ClientEventType = "impression" | "click" | "detail_view" | "store_visit";
export type Surface = "dashboard" | "play" | "buy" | "trending" | "game_page" | "profile" | "library";

export interface ClientEvent {
  type: ClientEventType;
  game_id: number;
  idempotency_key: string;
  occurred_at: string;
  recommendation_run_id?: number;
  position?: number;
  surface?: Surface;
  context?: Record<string, number | string | boolean>;
}

const FLUSH_DELAY_MS = 4000;
const MAX_BATCH = 50;

let queue: ClientEvent[] = [];
const sentKeys = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;
let listening = false;

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** One id per page load: impressions are counted once per card per page view. */
export const pageViewId: string = randomId().replaceAll("-", "").slice(0, 16);

export function newEventKey(prefix: string): string {
  return `${prefix}:${randomId()}`;
}

function send(batch: ClientEvent[], keepalive: boolean): void {
  if (batch.length === 0) return;
  void fetch("/api/me/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events: batch }),
    keepalive,
    credentials: "same-origin",
  }).catch(() => {
    // Best effort: behavioural events never interrupt the user. A failed batch is
    // dropped rather than retried forever; idempotency keys make retries safe.
  });
}

export function flushEvents(keepalive = false): void {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  while (queue.length) send(queue.splice(0, MAX_BATCH), keepalive);
}

function listen(): void {
  if (listening || typeof document === "undefined") return;
  listening = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushEvents(true);
  });
  window.addEventListener("pagehide", () => flushEvents(true));
}

export function trackEvent(event: Omit<ClientEvent, "occurred_at"> & { occurred_at?: string }): void {
  if (sentKeys.has(event.idempotency_key)) return;
  sentKeys.add(event.idempotency_key);
  queue.push({ occurred_at: new Date().toISOString(), ...event });
  listen();
  if (queue.length >= MAX_BATCH) flushEvents();
  else if (!timer) timer = setTimeout(() => flushEvents(), FLUSH_DELAY_MS);
}

/** Test helper. */
export function _resetEventsForTests(): void {
  queue = [];
  sentKeys.clear();
  if (timer) clearTimeout(timer);
  timer = null;
}
