# ADR-0016: Content-based recommendation baseline and its data sources

- Status: Accepted · Date: 2026-11-15 · Stage 3

## Context
Prompt 3 asks for real recommendations, built with content-based filtering, in three categories. Spec §16 fixes the category weights, §12 and §20 give the playtime and backlog formulas, and §20.3 forbids fabricated trends. There is no training data yet (spec §18 says to fall back to content-based recommendations), and the catalogue initially holds only users' own games.

## Decision
1. **A pure, versioned engine** (`content-v1`) in `app/recommendations/`, with no database, network or clock access. All parameters live in one `EngineParams` dataclass, can be overridden through `RECOMMENDER_OVERRIDES`, and are stored with every run. Formulas: [docs/RECOMMENDATIONS.md](../RECOMMENDATIONS.md).
2. **Three signals kept separate**: satisfaction (ratings), historical behaviour and recent behaviour. Behaviour is a lift of playtime share over catalogue prevalence, capped at −0.5 and at 0.6 confidence, so playtime is never read as satisfaction.
3. **No double counting in the hierarchy**: within-category shares when building profiles, and "most specific usable preference per lineage" when scoring.
4. **Exact, additive explanations**: every contribution's points sum to Match − 50. Reasons are templates over those contributions. No language model is used.
5. **Candidate discovery from Valve's public store API only**:
   - `IStoreQueryService/Query`: games carrying the player's top liked features, in Steam's popularity order (`sort=12`, undocumented, verified live).
   - `ISteamChartsService/GetMostPlayedGames` and `IStoreTopSellersService/GetWeeklyTopSellers`.
6. **Prices** come from `best_purchase_option` in `IStoreBrowseService/GetItems` (already fetched for metadata) and are stored per storefront country. They are shown separately and never affect the ranking (spec §20.2).
7. **Trends only from self-collected history**: `ISteamUserStats/GetNumberOfCurrentPlayers`, sampled every 2 hours. Trend scores need 42 days of data. Until then the trending run is `unavailable`, and the page shows collection progress plus a "Popular right now" list that is clearly labelled as not a trend.
8. **Precomputed runs**: profile → discovery → three category runs, rebuilt after every library import, after manual preference changes (debounced by 5 s, without discovery) and on demand (at most once a minute). Pages read the latest stored run; filters apply when the list is read.

## Alternatives considered
- **Scoring on request**: rejected. Discovery and catalogue-wide scoring cost seconds, and stored runs give reproducibility (spec §26 `recommendation_runs`).
- **SteamSpy, SteamDB or SteamCharts for trends or tags**: rejected. They are third-party, have unclear terms, and SteamDB prohibits scraping (PROVIDERS.md).
- **Absolute popularity as "trending"**: rejected by spec §20.3. It is shown only as a separate, labelled list.
- **Collaborative filtering now**: deferred to the ML stage. It needs interaction data from many users (spec §17).

## Consequences
- Matches are uncalibrated. The UI says "Match", never a percentage.
- The quality of the unowned list depends on discovery breadth, which grows with each user's liked features and with the daily chart import.
- Trending switches on automatically about 42 days after the first player-count sample (2026-11-15).
