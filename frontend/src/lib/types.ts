import type { ApiGameFeedback } from "@/lib/api/types";

/**
 * Frontend domain types. These describe what the UI renders and are shared by
 * the mock data source (src/mocks) and, from later stages, the real API client.
 */

export type RecommendationCategory = "owned" | "unowned" | "trending";

/** The page each category's list lives on. */
export const LIST_LABEL: Record<RecommendationCategory, string> = {
  owned: "Games I Should Play",
  unowned: "Games I Should Buy",
  trending: "Trending Games",
};

export const CATEGORY_LABEL: Record<RecommendationCategory, string> = {
  owned: "From your library",
  unowned: "Worth buying",
  trending: "Trending",
};

/**
 * How much the score can be trusted. Until a calibrated satisfaction model
 * exists the UI shows a "Match" score, never a probability (spec §18, §33).
 */
export type Confidence = "low" | "medium" | "high";

export type ScoreKind = "match" | "calibrated_satisfaction";

export interface GameSummary {
  id: string;
  title: string;
  tagline: string;
  tags: string[];
  /** Placeholder artwork seed; real artwork URLs arrive with catalogue ingestion. */
  artworkUrl: string | null;
  steamAppId: number | null;
  releaseYear: number | null;
}

export interface Recommendation {
  game: GameSummary;
  category: RecommendationCategory;
  score: number; // 0–100
  scoreKind: ScoreKind;
  confidence: Confidence;
  reasons: string[];
  owned: boolean;
  playtimeMinutes: number | null;
  lastPlayedDaysAgo: number | null;
  priceLabel: string | null;
  reviewLabel: string | null;
  trendLabel: string | null;
  /** Price before discount, shown struck through when the game is on sale. */
  originalPriceLabel?: string | null;
  discountPct?: number | null;
  /** Reasons that count against the game (disliked features). */
  cautions?: string[];
  /** How the score was computed; absent for sample data. */
  breakdown?: ScoreBreakdown | null;
  /** Where this card was shown: for impressions and feedback (absent for samples). */
  exposure?: Exposure | null;
  /** The player's current feedback on this game. */
  feedback?: GameFeedback | null;
}

export interface Exposure {
  runId: number;
  position: number;
  modelVersion: string;
}

export type GameFeedback = ApiGameFeedback;

export interface ScoreBreakdown {
  matchScore: number;
  /** Calibrated predicted enjoyment (0–100) when a satisfaction model ranked the list. */
  predictedSatisfaction?: number | null;
  /** The category ranking score the list is sorted by. */
  rankingScore?: number;
  /** Collaborative percentile when a trained model was blended into the score. */
  collaborativeScore?: number | null;
  backlogScore: number | null;
  trendScore: number | null;
  metadataConfidence: number;
  groups: { group: string; label: string; weight: number; score: number | null }[];
  contributions: {
    feature: string;
    name: string;
    points: number;
    preference: number;
    origin: PreferenceOrigin;
  }[];
}

export interface TrendStatus {
  daysCollected: number;
  daysNeeded: number;
  firstDay: string | null;
  gamesTracked: number;
  /** Source health (Stage 6): hours since the last successful sample, share of calls answered. */
  freshnessHours?: number | null;
  reliability?: number | null;
  maxStalenessHours?: number | null;
  note?: string | null;
}

export interface PopularGame {
  game: GameSummary;
  players: number;
  matchScore: number;
  confidence: Confidence;
  reasons: string[];
}

export interface RecommendationList {
  status: "ready" | "pending";
  items: Recommendation[];
  generatedAt: string | null;
  dataState: "ok" | "incomplete" | "unavailable";
  note: string | null;
  filteredOut: number;
  hiddenByFeedback?: number;
  runId?: number | null;
  /** All items after filters; ``items`` may hold fewer when a limit was requested. */
  total?: number;
  /** "calibrated_satisfaction" when a deployed satisfaction model ranked the list. */
  scoreKind?: ScoreKind;
  /** The run's algorithm, e.g. "content-v2+cf#1+sat#2". */
  algorithm?: string | null;
  /** Deployment scoring mode (AI_GRADE): "ai" (trained models when deployed) or "classic". */
  scoringMode?: "ai" | "classic";
  trendStatus: TrendStatus | null;
  popularNow: PopularGame[];
}

export interface UnownedFilters {
  maxPrice?: number; // whole currency units
  freeOnly?: boolean;
  minReview?: number; // percent positive
  releasedAfter?: number; // year
  releasedBefore?: number;
  players?: "any" | "multiplayer" | "singleplayer";
}

export type PreferenceOrigin = "inferred" | "manual";

export interface FeaturePreference {
  feature: string;
  category: string;
  value: number; // −1 … +1
  confidence: number; // 0 … 1
  origin: PreferenceOrigin;
  slug?: string;
}

export interface ProfileSummary {
  displayName: string;
  avatarInitials: string;
  gamesOwned: number;
  gamesPlayed: number;
  totalPlaytimeMinutes: number;
  recentPlaytimeMinutes: number;
  profileConfidence: number; // 0 … 1
  singleplayerShare: number; // 0 … 1 of attributable playtime
  lastSyncedAt: string | null; // ISO-8601 UTC
  topPreferences: FeaturePreference[];
  dislikes: FeaturePreference[];
  excludedTags: string[];
}

export interface LibraryEntry {
  game: GameSummary;
  /** null = unknown (games added by hand have no playtime data). */
  playtimeMinutes: number | null;
  owned?: boolean;
  rating?: -2 | -1 | 0 | 1 | 2 | null;
  recentMinutes: number;
  lastPlayedDaysAgo: number | null;
  achievements?: { achieved: number; total: number } | null;
}

export interface ActivityEntry {
  game: GameSummary;
  recentMinutes: number;
}

/** Every data loader tags its result so mock data can never pass as real data. */
export type DataSource = "mock" | "api";

export interface Sourced<T> {
  source: DataSource;
  data: T;
}
