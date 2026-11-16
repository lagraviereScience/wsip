# External data providers: review and status

Spec §9 requires checking API availability, authentication, rate limits, commercial
rights, storage and caching rights, attribution and redistribution before any
provider is used. This is the review as of **2026-11-14**, updated **2026-11-15** for Stages 3 and 6. It is not legal advice;
items marked ⚖ need confirmation before public launch.

The live status is available at `GET /api/catalogue/providers`.

| Provider | Purpose | Status | Access and auth | Limits | Terms notes |
|---|---|---|---|---|---|
| Steam Web API | Libraries, playtime, achievements, profiles | **Enabled** with the operator's `STEAM_WEB_API_KEY` (ADR-0015; live import verified 2026-11-15). Without a key: manual fallback (ADR-0014) | Key from steamcommunity.com/dev/apikey; backend only | 100,000 calls/day per key; we pace at 60/min | Steam Web API Terms of Use: retrieve user data only at the user's request; keep the key confidential; a privacy policy must disclose stored Steam data and where it is stored ⚖; no implied Valve endorsement; Steam data must not appear to come from a third party |
| Steam Store (IStoreBrowseService / IStoreService / IStoreQueryService) | Game search, metadata, user tags, categories, review summaries | **Enabled** | Public Valve Web API, no key | Not published; we pace at 30/min, 50 apps per call | Same Steam terms; attribute as "Game data provided by Steam". Undocumented shape, so the parser is defensive (ADR-0013) |
| Steam Store discovery: `IStoreQueryService/Query`, `ISteamChartsService/GetMostPlayedGames`, `IStoreTopSellersService/GetWeeklyTopSellers` | Unowned candidates (Stage 3, ADR-0016) | **Enabled** | Public Valve Web API, no key | Store throttle (30/min); per-user discovery at most once per 6 h; charts daily | Same Steam terms. `Query` `sort=12` is undocumented (verified 2026-11-15); the parser accepts `ids` or `store_items` |
| Steam prices (`best_purchase_option` in `GetItems`) | Purchase metadata | **Enabled** | Same call as metadata | — | Shown separately from scores; storefront country `STEAM_STORE_COUNTRY` |
| `ISteamUserStats/GetNumberOfCurrentPlayers` | Self-collected player counts for trends | **Enabled** | Public, no key | Own throttle `steam_players` (120/min); 400 games every 2 h | The only trend input. Every sampling pass is recorded (`player_count_passes`) so **freshness** (hours since the last successful pass) and **reliability** (share of calls answered, 7 days) are measured; trend scores pause above 26 h staleness or below 50% reliability (configurable) |
| Steam OpenID | Sign-in | **Enabled** | steamcommunity.com/openid | — | Steam passwords never reach us |
| Steam Community profile XML | Signed-in user's own name, avatar and visibility (sign-in-only mode) | **Enabled** | `steamcommunity.com/profiles/<id>/?xml=1`, no key | Paced at 30/min | Public Valve XML; only fetched for the user who just signed in; parsed with defusedxml. The games XML feed no longer exists, and the HTML games page is **not** scraped |
| IGDB | **Completion times** (`game_time_to_beats`: hastily / normally / completely, seconds), matched by Steam appid via `external_games` (source 1 = Steam) | **Implemented, disabled** until `IGDB_ENABLED`, `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` are set and the terms below are confirmed. Field names checked against IGDB's published `igdbapi.proto` (2026-11-15); not tested against the live API (no credentials) | Twitch client credentials (OAuth client_credentials; secret sent in the request body) | 4 req/s per IGDB docs; we pace at 180/min; daily job, 500 games per run, refreshed after 30 days | Docs: free for non-commercial use under the Twitch Developer Services Agreement; commercial use needs a partnership (partner@igdb.com). An IGDB FAQ claims commercial use is free, which contradicts this ⚖. **Needs written confirmation for this public site before enabling** |
| RAWG | Additional metadata | **Disabled** | API key | Free tier quota | Requires attribution and a backlink; plan limits for larger sites ⚖. Not evaluated in depth yet |
| OpenCritic | Reviews | **Disabled** | Paid (RapidAPI) | Per plan | Paid access only |
| HowLongToBeat | Duration estimates | **Not used** | No public API | — | Scraping not authorised; IGDB is the authorised alternative for completion times |
| SteamDB | Historical player statistics | **Not used** (evaluated 2026-11-15) | No public API | — | Its terms prohibit scraping and automated access; no licence for reuse. Not a permitted source |
| SteamCharts | Player-count history | **Not used** (evaluated 2026-11-15) | No public API or published terms granting reuse | — | Would require scraping, which is not assumed permitted. Its history would have allowed trends from day one; instead trends start once 42 days are self-collected (about 2026-12-27) |

## Attribution and freshness

Every stored provider value carries its source and fetch time: `game_sources`
(metadata), `game_review_summaries.fetched_at`, `game_prices.fetched_at` (per
storefront country), `game_completion_times.fetched_at` (source `igdb`), and
`player_count_passes`. The game page lists them ("Reviews: Steam Store, updated …").
Unknown values are stored and shown as unknown, never estimated.

## Failure isolation

Provider errors are typed (`ProviderUnavailable`, `ProviderRateLimited`,
`ProviderBadResponse`, `ProviderAuthError`), retried with bounded backoff, and
contained per provider:

- a metadata outage never fails a library import, and sign-in never depends on the
  Web API key;
- after a provider stays unavailable through all retries, a **circuit breaker** skips
  calls to it for 2 minutes (`PROVIDER_CIRCUIT_COOLDOWN_S`), so rebuilds, imports and
  sampling don't each wait through retries during an outage (found in Stage 6
  performance testing);
- recommendations are precomputed and served from the database, so they keep working
  while every provider is down; trending pauses only when its data becomes stale;
- per-provider outcome counts (ok, unavailable, rate limited, short-circuited) for the
  last 24 hours: `python -m app.cli status`.

## Sources consulted

- Steam web authentication: https://partner.steamgames.com/doc/features/auth
- IPlayerService: https://partner.steamgames.com/doc/webapi/IPlayerService
- Steam Web API Terms of Use: https://steamcommunity.com/dev/apiterms
- IGDB API docs (account creation, commercial partnership): https://api-docs.igdb.com/
- Twitch developer forum, commercial use of IGDB: https://discuss.dev.twitch.com/t/commercial-use-of-igdb-api/23567
