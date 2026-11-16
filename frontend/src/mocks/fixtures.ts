/**
 * MOCK DATA — fictional placeholder content for visual development only.
 * See ./README.md. Never import this file outside src/lib/data/.
 */

import type {
  ActivityEntry,
  GameSummary,
  LibraryEntry,
  ProfileSummary,
  Recommendation,
} from "@/lib/types";

const game = (
  id: string,
  title: string,
  tagline: string,
  tags: string[],
  releaseYear: number,
): GameSummary => ({ id, title, tagline, tags, artworkUrl: null, steamAppId: null, releaseYear });

export const MOCK_GAMES = {
  emberDeep: game("mock-01", "Ember Deep", "Dig, smelt and automate a city under a dying sun.", ["Automation", "Base building", "Survival", "Singleplayer"], 2024),
  saltAndSignal: game("mock-02", "Salt & Signal", "A lighthouse keeper's mystery on a drifting archipelago.", ["Exploration", "Mystery", "Relaxed", "Singleplayer"], 2023),
  ironVerge: game("mock-03", "Iron Verge", "Squad tactics across a fractured orbital ring.", ["Strategy", "Tactical", "Turn-based", "Co-op"], 2025),
  hollowCrown: game("mock-04", "Hollow Crown", "A sprawling action RPG of rival courts and cursed relics.", ["Action RPG", "Open world", "Character progression"], 2022),
  pixelHarvest: game("mock-05", "Pixel Harvest", "Grow a tiny farm on the back of a wandering giant.", ["Farming", "Crafting", "Relaxed", "Co-op"], 2021),
  neonRelay: game("mock-06", "Neon Relay", "Fast-paced roguelike courier runs through a vertical city.", ["Roguelike", "Fast-paced", "Procedural generation"], 2025),
  quietOrbit: game("mock-07", "Quiet Orbit", "Run a research station where every resource counts.", ["Resource management", "Simulation", "Complex management"], 2024),
  stoneTide: game("mock-08", "Stone Tide", "Raise a coastal kingdom before the sea takes it back.", ["City builder", "Strategy", "Sandbox"], 2023),
  lastLantern: game("mock-09", "Last Lantern", "Co-op survival horror in a flooded mine.", ["Horror", "Survival", "Online co-op", "PvE"], 2025),
  copperFields: game("mock-10", "Copper Fields", "Trade caravans between rival desert guilds.", ["Trading", "Strategy", "Sandbox"], 2020),
  wildGlyph: game("mock-11", "Wild Glyph", "Decode a living language to calm an angry forest.", ["Puzzle", "Exploration", "Linear"], 2024),
  overclock: game("mock-12", "Overclock Arena", "Competitive 3v3 mech brawler.", ["PvP", "Competitive", "Fast-paced"], 2025),
} satisfies Record<string, GameSummary>;

const G = MOCK_GAMES;

export const MOCK_PROFILE: ProfileSummary = {
  displayName: "Preview Player",
  avatarInitials: "PP",
  gamesOwned: 214,
  gamesPlayed: 131,
  totalPlaytimeMinutes: 187_340,
  recentPlaytimeMinutes: 1_290,
  profileConfidence: 0.72,
  singleplayerShare: 0.78,
  lastSyncedAt: "2026-11-14T08:30:00Z",
  topPreferences: [
    { feature: "Automation", category: "Gameplay mechanics", value: 0.86, confidence: 0.81, origin: "inferred" },
    { feature: "Base building", category: "Gameplay mechanics", value: 0.74, confidence: 0.77, origin: "inferred" },
    { feature: "Strategy", category: "Genres and themes", value: 0.68, confidence: 0.84, origin: "inferred" },
    { feature: "Exploration", category: "Gameplay mechanics", value: 0.61, confidence: 0.58, origin: "inferred" },
    { feature: "Singleplayer", category: "Game modes", value: 0.55, confidence: 0.9, origin: "manual" },
    { feature: "Sandbox", category: "Game structure", value: 0.49, confidence: 0.63, origin: "inferred" },
    { feature: "Relaxed", category: "Pace and complexity", value: 0.32, confidence: 0.41, origin: "inferred" },
  ],
  dislikes: [
    { feature: "PvP", category: "Game modes", value: -0.8, confidence: 0.95, origin: "manual" },
    { feature: "Horror", category: "Genres and themes", value: -0.42, confidence: 0.52, origin: "inferred" },
  ],
  excludedTags: ["Battle royale", "Gacha"],
};

export const MOCK_OWNED: Recommendation[] = [
  {
    game: G.quietOrbit, category: "owned", score: 91, scoreKind: "match", confidence: "high",
    reasons: ["Strong match with your Automation and Resource management play", "Owned for 8 months, never launched"],
    owned: true, playtimeMinutes: 0, lastPlayedDaysAgo: null, priceLabel: null, reviewLabel: "Very positive", trendLabel: null,
  },
  {
    game: G.stoneTide, category: "owned", score: 84, scoreKind: "match", confidence: "medium",
    reasons: ["Shares Strategy and Sandbox with your most-played games", "Only 40 minutes played"],
    owned: true, playtimeMinutes: 40, lastPlayedDaysAgo: 210, priceLabel: null, reviewLabel: "Mostly positive", trendLabel: null,
  },
  {
    game: G.saltAndSignal, category: "owned", score: 78, scoreKind: "match", confidence: "medium",
    reasons: ["Fits your recent interest in Exploration", "Short and relaxed — good between longer sessions"],
    owned: true, playtimeMinutes: 0, lastPlayedDaysAgo: null, priceLabel: null, reviewLabel: "Overwhelmingly positive", trendLabel: null,
  },
  {
    game: G.wildGlyph, category: "owned", score: 66, scoreKind: "match", confidence: "low",
    reasons: ["Exploration match; limited metadata for this game"],
    owned: true, playtimeMinutes: 95, lastPlayedDaysAgo: 400, priceLabel: null, reviewLabel: "Positive", trendLabel: null,
  },
];

export const MOCK_UNOWNED: Recommendation[] = [
  {
    game: G.emberDeep, category: "unowned", score: 93, scoreKind: "match", confidence: "high",
    reasons: ["Automation + Base building — your two strongest preferences", "Singleplayer-first, as you prefer"],
    owned: false, playtimeMinutes: null, lastPlayedDaysAgo: null, priceLabel: "€24.99", reviewLabel: "Very positive", trendLabel: null,
  },
  {
    game: G.copperFields, category: "unowned", score: 81, scoreKind: "match", confidence: "medium",
    reasons: ["Trading and Strategy match your management games"],
    owned: false, playtimeMinutes: null, lastPlayedDaysAgo: null, priceLabel: "€14.99 · −40%", reviewLabel: "Mostly positive", trendLabel: null,
  },
  {
    game: G.pixelHarvest, category: "unowned", score: 74, scoreKind: "match", confidence: "medium",
    reasons: ["Crafting and Relaxed pace", "Co-op is optional"],
    owned: false, playtimeMinutes: null, lastPlayedDaysAgo: null, priceLabel: "€9.99", reviewLabel: "Very positive", trendLabel: null,
  },
];

export const MOCK_TRENDING: Recommendation[] = [
  {
    game: G.ironVerge, category: "trending", score: 86, scoreKind: "match", confidence: "medium",
    reasons: ["Strategy and Tactical match your profile", "Player count rising week over week"],
    owned: false, playtimeMinutes: null, lastPlayedDaysAgo: null, priceLabel: "€29.99", reviewLabel: "Very positive", trendLabel: "Rising fast",
  },
  {
    game: G.neonRelay, category: "trending", score: 63, scoreKind: "match", confidence: "low",
    reasons: ["Procedural generation match; pace is faster than you usually play"],
    owned: false, playtimeMinutes: null, lastPlayedDaysAgo: null, priceLabel: "€17.99", reviewLabel: "Positive", trendLabel: "Rising",
  },
];

export const MOCK_LIBRARY: LibraryEntry[] = [
  { game: G.hollowCrown, playtimeMinutes: 9_480, recentMinutes: 620, lastPlayedDaysAgo: 1 },
  { game: G.stoneTide, playtimeMinutes: 40, recentMinutes: 0, lastPlayedDaysAgo: 210 },
  { game: G.quietOrbit, playtimeMinutes: 0, recentMinutes: 0, lastPlayedDaysAgo: null },
  { game: G.saltAndSignal, playtimeMinutes: 0, recentMinutes: 0, lastPlayedDaysAgo: null },
  { game: G.wildGlyph, playtimeMinutes: 95, recentMinutes: 0, lastPlayedDaysAgo: 400 },
  { game: G.lastLantern, playtimeMinutes: 310, recentMinutes: 0, lastPlayedDaysAgo: 95 },
  { game: G.overclock, playtimeMinutes: 1_220, recentMinutes: 0, lastPlayedDaysAgo: 540 },
];

export const MOCK_RECENT_ACTIVITY: ActivityEntry[] = [
  { game: G.hollowCrown, recentMinutes: 620 },
  { game: G.emberDeep, recentMinutes: 0 },
].filter((a) => a.recentMinutes > 0);
