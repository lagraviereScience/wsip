# ADR-0013: Steam Store metadata through Valve's public store APIs

- Status: Accepted · Date: 2026-11-14

## Context
The taxonomy needs Steam user tags (OPEN_QUESTIONS #4). The `store.steampowered.com/api/appdetails` endpoint is undocumented, lacks user tags and is strictly rate-limited. Scraping store pages is not authorised.

## Decision
Use Valve's own Web API services, which need no key:
- `IStoreBrowseService/GetItems/v1`: up to 50 apps per call. It returns name, type, short description, release date, asset paths, player-support categories, user tags with vote weights, and review summary.
- `IStoreService/GetTagList/v1`: tag id to English name.
- `IStoreBrowseService/GetStoreCategories/v1`: category id to name.

These were verified live on 2026-11-14. Trimmed real responses are stored as test fixtures.

## Consequences
- These endpoints are not formally documented, so the shape could change. The client validates defensively, failures are contained (`game_sources.status = error` is retried on the next refresh), and imports never depend on them.
- Displayed Steam data is attributed ("Game data provided by Steam"), as the Steam Web API Terms of Use require.
- Prices are not ingested yet. They are region-dependent and belong to the "Games I Should Buy" stage.
