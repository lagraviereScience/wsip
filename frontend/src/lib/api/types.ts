/** Response shapes of the backend REST API (mirrors backend/app/schemas). */

export type SyncStatus = "queued" | "running" | "succeeded" | "blocked_private" | "empty" | "failed";
export type GameDetailsStatus = "unknown" | "accessible" | "empty" | "private" | "error";

export interface SyncRun {
  id: number;
  status: SyncStatus;
  trigger: string;
  queued_at: string;
  finished_at: string | null;
  games_seen: number | null;
  error_code: string | null;
}

export interface SteamConnection {
  steam_id: string;
  profile_name: string | null;
  profile_url: string | null;
  avatar_url: string | null;
  profile_is_public: boolean | null;
  game_details_status: GameDetailsStatus;
  game_details_checked_at: string | null;
  playtime_appears_hidden: boolean;
  last_synced_at: string | null;
}

export interface Me {
  id: string;
  display_name: string;
  avatar_url: string | null;
  steam: SteamConnection | null;
  latest_sync: SyncRun | null;
  library: {
    games_owned: number;
    games_played: number;
    games_rated: number;
    total_playtime_minutes: number;
    recent_playtime_minutes: number;
  };
  /** "manual": sign-in only, users add and rate games. "steam_import": automatic. */
  library_mode: "manual" | "steam_import";
  min_rated_games: number;
  profile_ready: boolean;
}

export interface LibraryGame {
  game_id: number;
  name: string;
  steam_appid: string | null;
  header_image_url: string | null;
  capsule_image_url: string | null;
  game_type: string;
  release_date: string | null;
  owned: boolean;
  ownership_source: "steam_import" | "manual" | null;
  rating: Rating | null;
  /** null = unknown (manually added games). */
  playtime_forever_minutes: number | null;
  playtime_2weeks_minutes: number | null;
  last_played_at: string | null;
  achievements_achieved: number | null;
  achievements_total: number | null;
  review_label: string | null;
  top_features: string[];
}

export interface LibraryResponse {
  games: LibraryGame[];
  attribution: string;
}

/** Spec §18 satisfaction scale. */
export type Rating = -2 | -1 | 0 | 1 | 2;

export const RATINGS: { value: Rating; label: string }[] = [
  { value: 2, label: "Loved it" },
  { value: 1, label: "Liked it" },
  { value: 0, label: "Neutral" },
  { value: -1, label: "Disliked it" },
  { value: -2, label: "Hated it" },
];

export interface SearchResult {
  steam_appid: number;
  name: string;
  capsule_image_url: string | null;
  release_year: number | null;
  owned: boolean;
  rating: Rating | null;
}

export const SYNC_IN_PROGRESS: SyncStatus[] = ["queued", "running"];

// --- Stage 3: gamer profile and recommendations -------------------------------

export type PreferenceOrigin = "inferred" | "manual";
export type ApiConfidence = "low" | "medium" | "high";

export interface EvidenceGame {
  game_id: number;
  name: string;
  capsule_image_url: string | null;
  playtime_minutes: number | null;
  rating: Rating | null;
}

export interface ApiFeaturePreference {
  slug: string;
  name: string;
  category: string;
  category_name: string;
  group: string;
  parent: string | null;
  /** Effective value: manual when set, else inferred. null = no value (exclusion only). */
  value: number | null;
  confidence: number;
  origin: PreferenceOrigin | null;
  excluded: boolean;
  inferred: {
    value: number;
    confidence: number;
    historical: number | null;
    historical_confidence: number;
    recent: number | null;
    recent_confidence: number;
    satisfaction: number | null;
    satisfaction_confidence: number;
  } | null;
  manual: { value: number | null; excluded: boolean; updated_at: string } | null;
  minutes_lifetime: number;
  minutes_recent: number;
  evidence: EvidenceGame[];
}

export interface ApiProfile {
  status: "ready" | "pending";
  run: {
    id: number;
    created_at: string;
    params_version: string;
    games_considered: number;
    games_with_metadata: number;
    games_played: number;
    games_rated: number;
    features_inferred: number;
    confidence: number;
    total_minutes: number;
    recent_minutes: number;
  } | null;
  features: ApiFeaturePreference[];
  mode_balance: {
    singleplayer_minutes: number;
    multiplayer_minutes: number;
    singleplayer_share: number | null;
  };
  influential_games: EvidenceGame[];
}

export interface TaxonomyFeature {
  id: number;
  slug: string;
  name: string;
  parent_id: number | null;
  synonyms: string[];
  description: string | null;
  category: string;
  scoring_group: string;
}

export interface ApiReason {
  code: string;
  text: string;
  polarity: "positive" | "negative" | "info";
  feature?: string;
  points?: number;
}

export interface ApiContribution {
  feature: string;
  name: string;
  group: string;
  game_features: string[];
  preference: number;
  preference_confidence: number;
  origin: PreferenceOrigin;
  game_value: number;
  metadata_confidence: number;
  points: number;
}

export interface ApiGroupScore {
  group: string;
  weight: number;
  score: number | null;
  reliability: number;
  evidence: number;
}

export interface ApiRecommendation {
  rank: number;
  game_id: number;
  name: string;
  steam_appid: string | null;
  header_image_url: string | null;
  capsule_image_url: string | null;
  short_description: string | null;
  release_date: string | null;
  owned: boolean;
  playtime_minutes: number | null;
  last_played_at: string | null;
  score: number;
  satisfaction_score: number;
  backlog_score: number | null;
  trend_score: number | null;
  confidence: number;
  confidence_label: ApiConfidence;
  metadata_confidence: number;
  group_scores: ApiGroupScore[];
  contributions: ApiContribution[];
  reasons: ApiReason[];
  candidate_sources: string[];
  tags: string[];
  review: { count: number | null; percent_positive: number | null; label: string | null } | null;
  price: {
    is_free: boolean;
    final_cents: number | null;
    original_cents: number | null;
    discount_pct: number | null;
    formatted_final: string | null;
    formatted_original: string | null;
    country: string;
    fetched_at: string;
  } | null;
  /** Collaborative percentile 0–100 when a trained model was blended in. */
  collaborative_score?: number | null;
  /** Calibrated P(satisfied), 0–1, when a deployed satisfaction model ranked the list. */
  predicted_satisfaction?: number | null;
  feedback?: ApiGameFeedback | null;
}

export type FeedbackKind =
  | "like"
  | "dislike"
  | "favourite"
  | "save_for_later"
  | "not_interested"
  | "not_my_type"
  | "already_played";

export type DismissalReason = "price" | "timing" | "owned_elsewhere" | "other";

export interface ApiGameFeedback {
  game_id: number;
  reaction: "like" | "dislike" | null;
  favourite: boolean;
  saved: boolean;
  dismissal: "not_interested" | "not_my_type" | null;
  dismissal_reason: DismissalReason | null;
  already_played: boolean;
  rating: number | null;
  rating_source: string | null;
}

export interface ApiFeedbackGame extends ApiGameFeedback {
  name: string;
  steam_appid: string | null;
  capsule_image_url: string | null;
  owned: boolean;
  updated_at: string | null;
}

export interface ApiSatisfactionPrompt {
  game_id: number;
  name: string;
  capsule_image_url: string | null;
  minutes_since_recommended: number;
  question: string;
}

export interface ApiGamePage {
  game_id: number;
  name: string;
  steam_appid: string | null;
  header_image_url: string | null;
  short_description: string | null;
  release_date: string | null;
  tags: string[];
  owned: boolean;
  playtime_minutes: number | null;
  feedback: ApiGameFeedback;
  match: number | null;
  confidence_label: ApiConfidence | null;
  reasons: ApiReason[];
  contributions: { feature: string; name: string; group: string; points: number; origin: string | null }[];
  recommendation_run_id: number | null;
  category: "owned" | "unowned" | "trending" | null;
  rank: number | null;
  review: { count: number | null; percent_positive: number | null; label: string | null } | null;
  price: {
    is_free: boolean;
    formatted_final: string | null;
    formatted_original: string | null;
    discount_pct: number | null;
  } | null;
  completion?: {
    source: string;
    hastily_hours: number | null;
    normally_hours: number | null;
    completely_hours: number | null;
    submissions: number | null;
    fetched_at: string;
  } | null;
  sources?: { data: string; source: string; fetched_at: string }[];
}

export interface ApiSession {
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
  current: boolean;
}

export interface ApiPrivacy {
  contribute_to_global_training: boolean;
  allow_scheduled_sync: boolean;
  updated_at: string;
}

export type ScoringMode = "ai" | "classic";

export interface ApiRecommendations {
  category: "owned" | "unowned" | "trending";
  status: "ready" | "pending";
  /** The deployment's scoring mode (AI_GRADE): "ai" or "classic". */
  scoring_mode?: ScoringMode;
  score_kind: "match" | "calibrated_satisfaction";
  run: {
    id: number;
    category: string;
    created_at: string;
    algorithm: string;
    scoring_mode?: ScoringMode;
    config_version?: string | null;
    model_version_id?: number | null;
    data_state: "ok" | "incomplete" | "unavailable";
    note: string | null;
    candidates_considered: number;
    candidates_excluded: number;
    items_count: number;
  } | null;
  items: ApiRecommendation[];
  filtered_out: number;
  hidden_by_feedback?: number;
  total?: number;
  trend_status: {
    days_collected: number;
    days_needed: number;
    first_day: string | null;
    games_tracked: number;
    source?: string | null;
    last_success_at?: string | null;
    freshness_hours?: number | null;
    reliability_7d?: number | null;
    max_staleness_hours?: number | null;
  } | null;
  popular_now: {
    game_id: number;
    name: string;
    steam_appid: string | null;
    capsule_image_url: string | null;
    players: number;
    sampled_at: string;
    satisfaction_score: number;
    confidence_label: ApiConfidence;
    reasons: ApiReason[];
  }[];
  attribution: string;
}
