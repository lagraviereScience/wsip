/**
 * Data-access layer. Pages and components call these loaders and never import
 * mock fixtures directly. Each loader returns `{ source, data }`; while source
 * is "mock" the UI labels the content as sample data.
 *
 * Signed-in users get real data everywhere (Stage 3: profile and
 * recommendations come from the content-based engine). Signed-out visitors see
 * clearly labelled sample data.
 */

import "server-only";

import type {
  ApiFeedbackGame,
  ApiGamePage,
  ApiPrivacy,
  ApiProfile,
  ApiRecommendation,
  ApiRecommendations,
  LibraryResponse,
  Me,
  TaxonomyFeature,
} from "@/lib/api/types";
import { backendFetch, publicBackendFetch } from "@/lib/session";
import {
  MOCK_LIBRARY,
  MOCK_OWNED,
  MOCK_PROFILE,
  MOCK_RECENT_ACTIVITY,
  MOCK_TRENDING,
  MOCK_UNOWNED,
} from "@/mocks/fixtures";
import type {
  ActivityEntry,
  FeaturePreference,
  LibraryEntry,
  ProfileSummary,
  Recommendation,
  RecommendationCategory,
  RecommendationList,
  Sourced,
  UnownedFilters,
} from "@/lib/types";

const mock = <T,>(data: T): Sourced<T> => ({ source: "mock", data });
const real = <T,>(data: T): Sourced<T> => ({ source: "api", data });

const RECOMMENDATIONS: Record<RecommendationCategory, Recommendation[]> = {
  owned: MOCK_OWNED,
  unowned: MOCK_UNOWNED,
  trending: MOCK_TRENDING,
};

const DAY_MS = 86_400_000;

function daysAgo(iso: string | null, now: number): number | null {
  if (!iso) return null;
  return Math.max(0, Math.floor((now - Date.parse(iso)) / DAY_MS));
}

export const GROUP_LABEL: Record<string, string> = {
  genres_and_themes: "Genres and themes",
  gameplay_mechanics: "Gameplay mechanics",
  game_modes: "Game modes",
  game_structure: "Game structure",
  pace_and_complexity: "Pace and complexity",
};

function yearOf(iso: string | null): number | null {
  return iso ? Number(iso.slice(0, 4)) : null;
}

export function toRecommendation(
  r: ApiRecommendation,
  category: RecommendationCategory,
  now: number = Date.now(),
  run: { id: number; algorithm: string; scoring_mode?: string } | null = null,
): Recommendation {
  // Classic mode (AI_GRADE=FALSE) never shows a model prediction, whatever the item holds.
  const predicted = run?.scoring_mode === "classic" ? null : r.predicted_satisfaction;
  const review = r.review?.label
    ? `${r.review.label}${r.review.percent_positive !== null ? ` · ${r.review.percent_positive}%` : ""}`
    : null;
  const price = r.price;
  const discounted = !!price?.discount_pct && !!price.formatted_original;
  return {
    game: {
      id: String(r.game_id),
      title: r.name,
      tagline: r.short_description ?? "",
      tags: r.tags,
      artworkUrl: r.header_image_url ?? r.capsule_image_url,
      steamAppId: r.steam_appid ? Number(r.steam_appid) : null,
      releaseYear: yearOf(r.release_date),
    },
    category,
    // A calibrated, deployed satisfaction model is shown as predicted enjoyment;
    // anything else is the uncalibrated content "Match" (spec §18, §33), the same
    // number the game page shows. The category ranking score (which adds backlog or
    // trend) orders the list and appears in "Why this score".
    score: predicted != null ? predicted * 100 : r.satisfaction_score,
    scoreKind: predicted != null ? "calibrated_satisfaction" : "match",
    confidence: r.confidence_label,
    reasons: r.reasons.filter((x) => x.polarity !== "negative").map((x) => x.text),
    cautions: r.reasons.filter((x) => x.polarity === "negative").map((x) => x.text),
    owned: r.owned,
    playtimeMinutes: r.owned ? r.playtime_minutes : null,
    lastPlayedDaysAgo: daysAgo(r.last_played_at, now),
    priceLabel: price ? (price.is_free ? "Free to play" : price.formatted_final) : null,
    originalPriceLabel: discounted ? price.formatted_original : null,
    discountPct: discounted ? price.discount_pct : null,
    reviewLabel: review,
    trendLabel: r.trend_score !== null ? `Trend ${Math.round(r.trend_score)}` : null,
    exposure: run ? { runId: run.id, position: r.rank, modelVersion: run.algorithm } : null,
    feedback: r.feedback ?? null,
    breakdown: {
      matchScore: r.satisfaction_score,
      predictedSatisfaction: r.predicted_satisfaction != null ? r.predicted_satisfaction * 100 : null,
      rankingScore: r.score,
      collaborativeScore: r.collaborative_score ?? null,
      backlogScore: r.backlog_score,
      trendScore: r.trend_score,
      metadataConfidence: r.metadata_confidence,
      groups: r.group_scores.map((g) => ({
        group: g.group,
        label: GROUP_LABEL[g.group] ?? g.group,
        weight: g.weight,
        score: g.score,
      })),
      // The card shows the 10 largest; the rest stay in the API for auditing.
      contributions: r.contributions.slice(0, 10).map((c) => ({
        feature: c.feature,
        name: c.name,
        points: c.points,
        preference: c.preference,
        origin: c.origin,
      })),
    },
  };
}

function filterParams(f: UnownedFilters | undefined): string {
  if (!f) return "";
  const q = new URLSearchParams();
  if (f.maxPrice !== undefined) q.set("max_price_cents", String(Math.round(f.maxPrice * 100)));
  if (f.freeOnly) q.set("free_only", "true");
  if (f.minReview !== undefined) q.set("min_review_pct", String(f.minReview));
  if (f.releasedAfter !== undefined) q.set("released_after", String(f.releasedAfter));
  if (f.releasedBefore !== undefined) q.set("released_before", String(f.releasedBefore));
  if (f.players && f.players !== "any") q.set("players", f.players);
  const s = q.toString();
  return s ? `?${s}` : "";
}

const EMPTY_LIST: Omit<RecommendationList, "items" | "status"> = {
  generatedAt: null,
  dataState: "ok",
  note: null,
  filteredOut: 0,
  trendStatus: null,
  popularNow: [],
};

export async function getRecommendationList(
  me: Me | null,
  category: RecommendationCategory,
  filters?: UnownedFilters,
  limit?: number,
): Promise<Sourced<RecommendationList>> {
  if (!me) return mock({ ...EMPTY_LIST, status: "ready", items: RECOMMENDATIONS[category] });
  // Ask only for what the page shows: smaller responses, less server work.
  const qs = filterParams(filters);
  const lim = limit ? `${qs ? "&" : "?"}limit=${limit}` : "";
  const res = await backendFetch(`/api/me/recommendations/${category}${qs}${lim}`);
  if (!res?.ok) throw new Error(`recommendations request failed (${res?.status ?? "no session"})`);
  const body = (await res.json()) as ApiRecommendations;
  const now = Date.now();
  return real({
    status: body.status,
    items: body.items.map((r) => toRecommendation(r, category, now, body.run)),
    generatedAt: body.run?.created_at ?? null,
    dataState: body.run?.data_state ?? "ok",
    note: body.run?.note ?? null,
    filteredOut: body.filtered_out,
    hiddenByFeedback: body.hidden_by_feedback ?? 0,
    total: body.total ?? body.items.length,
    scoreKind: body.scoring_mode === "classic" ? "match" : body.score_kind,
    algorithm: body.run?.algorithm ?? null,
    scoringMode: body.scoring_mode ?? "ai",
    runId: body.run?.id ?? null,
    trendStatus: body.trend_status
      ? {
          daysCollected: body.trend_status.days_collected,
          daysNeeded: body.trend_status.days_needed,
          firstDay: body.trend_status.first_day,
          gamesTracked: body.trend_status.games_tracked,
          freshnessHours: body.trend_status.freshness_hours ?? null,
          reliability: body.trend_status.reliability_7d ?? null,
          maxStalenessHours: body.trend_status.max_staleness_hours ?? null,
          note: body.run?.note ?? null,
        }
      : null,
    popularNow: body.popular_now.map((p) => ({
      game: {
        id: String(p.game_id),
        title: p.name,
        tagline: "",
        tags: [],
        artworkUrl: p.capsule_image_url,
        steamAppId: p.steam_appid ? Number(p.steam_appid) : null,
        releaseYear: null,
      },
      players: p.players,
      matchScore: p.satisfaction_score,
      confidence: p.confidence_label,
      reasons: p.reasons.filter((x) => x.polarity !== "negative").map((x) => x.text),
    })),
  });
}

/** Mock-only list for signed-out previews (kept for components that need a flat list). */
export async function getRecommendations(
  category: RecommendationCategory,
): Promise<Sourced<Recommendation[]>> {
  return mock(RECOMMENDATIONS[category]);
}

export async function getProfileApi(me: Me | null): Promise<ApiProfile | null> {
  if (!me) return null;
  const res = await backendFetch("/api/me/profile");
  if (!res?.ok) throw new Error(`profile request failed (${res?.status ?? "no session"})`);
  return (await res.json()) as ApiProfile;
}

/** Games the player reacted to or rated from recommendations (for review and undo). */
export async function getFeedbackList(me: Me | null): Promise<ApiFeedbackGame[]> {
  if (!me) return [];
  const res = await backendFetch("/api/me/feedback");
  if (!res?.ok) throw new Error(`feedback request failed (${res?.status ?? "no session"})`);
  return ((await res.json()) as { games: ApiFeedbackGame[] }).games;
}

/** One game for the signed-in player; null when the game does not exist. */
export async function getGamePage(me: Me, gameId: number): Promise<ApiGamePage | null> {
  const res = await backendFetch(`/api/me/games/${gameId}`);
  if (res?.status === 404 || res?.status === 422) return null;
  if (!res?.ok) throw new Error(`game request failed (${res?.status ?? "no session"})`);
  return (await res.json()) as ApiGamePage;
}

export async function getPrivacy(me: Me | null): Promise<ApiPrivacy | null> {
  if (!me) return null;
  const res = await backendFetch("/api/me/privacy");
  if (!res?.ok) throw new Error(`privacy request failed (${res?.status ?? "no session"})`);
  return (await res.json()) as ApiPrivacy;
}

export async function getTaxonomy(): Promise<TaxonomyFeature[]> {
  const res = await publicBackendFetch("/api/catalogue/taxonomy");
  if (!res.ok) throw new Error(`taxonomy request failed (${res.status})`);
  return ((await res.json()) as { features: TaxonomyFeature[] }).features;
}

function toPreference(f: ApiProfile["features"][number]): FeaturePreference {
  return {
    feature: f.name,
    category: f.category_name,
    value: f.value ?? 0,
    confidence: f.confidence,
    origin: f.origin ?? "inferred",
    slug: f.slug,
  };
}

/** Summary used by the dashboard and profile header. Real when signed in. */
export async function getProfileSummary(
  me: Me | null,
  profile?: ApiProfile | null,
): Promise<Sourced<ProfileSummary>> {
  if (!me) return mock(MOCK_PROFILE);
  const p = profile === undefined ? await getProfileApi(me) : profile;
  const features = p?.features ?? [];
  const scored = features.filter((f) => f.value !== null && !f.excluded);
  const strength = (f: (typeof features)[number]) => Math.abs(f.value ?? 0) * f.confidence;
  return real({
    displayName: me.display_name,
    avatarInitials: me.display_name.slice(0, 2).toUpperCase(),
    gamesOwned: me.library.games_owned,
    gamesPlayed: me.library.games_played,
    totalPlaytimeMinutes: me.library.total_playtime_minutes,
    recentPlaytimeMinutes: me.library.recent_playtime_minutes,
    profileConfidence: p?.run?.confidence ?? 0,
    singleplayerShare: p?.mode_balance.singleplayer_share ?? 0.5,
    lastSyncedAt: me.steam?.last_synced_at ?? null,
    topPreferences: scored
      .filter((f) => (f.value ?? 0) > 0)
      .sort((a, b) => strength(b) - strength(a))
      .slice(0, 8)
      .map(toPreference),
    dislikes: scored
      .filter((f) => (f.value ?? 0) < 0)
      .sort((a, b) => strength(b) - strength(a))
      .slice(0, 6)
      .map(toPreference),
    excludedTags: features.filter((f) => f.excluded).map((f) => f.name),
  });
}

export async function getLibrary(me: Me | null): Promise<Sourced<LibraryEntry[]>> {
  if (!me) return mock(MOCK_LIBRARY);
  const res = await backendFetch("/api/me/library");
  if (!res?.ok) throw new Error(`library request failed (${res?.status ?? "no session"})`);
  const body = (await res.json()) as LibraryResponse;
  const now = Date.now();
  return real(
    body.games.map((g) => ({
      game: {
        id: String(g.game_id),
        title: g.name,
        tagline: "",
        tags: g.top_features,
        artworkUrl: g.capsule_image_url ?? g.header_image_url,
        steamAppId: g.steam_appid ? Number(g.steam_appid) : null,
        releaseYear: g.release_date ? Number(g.release_date.slice(0, 4)) : null,
      },
      playtimeMinutes: g.playtime_forever_minutes,
      owned: g.owned,
      rating: g.rating,
      recentMinutes: g.playtime_2weeks_minutes ?? 0,
      lastPlayedDaysAgo: daysAgo(g.last_played_at, now),
      achievements:
        g.achievements_total !== null && g.achievements_achieved !== null
          ? { achieved: g.achievements_achieved, total: g.achievements_total }
          : null,
    })),
  );
}

export async function getRecentActivity(me: Me | null): Promise<Sourced<ActivityEntry[]>> {
  if (!me) return mock(MOCK_RECENT_ACTIVITY);
  if (!me.profile_ready) return real([]);
  const library = await getLibrary(me);
  return real(
    library.data
      .filter((e) => e.recentMinutes > 0)
      .sort((a, b) => b.recentMinutes - a.recentMinutes)
      .slice(0, 5)
      .map((e) => ({ game: e.game, recentMinutes: e.recentMinutes })),
  );
}
