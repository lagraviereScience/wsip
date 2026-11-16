# ADR-0014: Sign-in-only mode, with a manual library and explicit ratings

- Status: Accepted · Date: 2026-11-14 · Decided by: product owner
- **Amended 2026-11-15 by [ADR-0015](0015-automatic-steam-import-primary.md):** automatic import is the product path; manual mode is only the fallback when no key is configured.

## Context
The product owner decided that the project should use **only "Sign in through Steam"**, with no Steam Web API key.

Steam OpenID proves identity but grants no data access (spec §28). Without a key:
- `IPlayerService/GetOwnedGames` returns HTTP 401 (verified live).
- The former community games XML feed (`/games?tab=all&xml=1`) now returns an HTML page. Reading it would be scraping, which spec §9 forbids.
- There is therefore **no authorised, key-free way to read a user's library or playtime.**

Valve endpoints that still work without a key: the public profile XML (`/profiles/<id>/?xml=1`: name, avatar, visibility), store search (`IStoreQueryService/SearchSuggestions`) and store metadata (`IStoreBrowseService/GetItems`), all verified live.

## Decision
The app runs in one of two library modes, chosen by configuration:

| Mode | When | Library source |
|---|---|---|
| `manual` (current) | `STEAM_WEB_API_KEY` unset | Users search Steam's store, tick the games they own and rate the games they've played |
| `steam_import` | key set | Automatic import as built earlier in Stage 2 (code kept and tested, but switched off) |

In `manual` mode:
- Sign-in stays real Steam OpenID (ADR-0008). Name and avatar come best-effort from the public profile XML, parsed with defusedxml.
- No import is queued, and `POST /api/me/steam/sync` returns 409.
- `PUT /api/me/library/games/{appid}` with `{owned, rating}` validates the AppID against the store, adds the game to the shared catalogue and ingests its metadata and canonical features immediately.
- Ratings use spec §18's scale (Loved 2 … Hated −2) in `user_feedback`, the primary training label.
- `user_library.source = 'manual'`. Playtime is **NULL (unknown)**, never invented as 0.
- The profile counts as ready after `MIN_RATED_GAMES_FOR_PROFILE` (default 5) ratings.
- The "game details must be public" requirement no longer applies, because nothing is read from the library.

If a key is added later, imports start. Platform data supersedes manual ownership (`source` becomes `steam_import`), ratings are kept, and manual entries Steam doesn't know about are never marked removed.

## Consequences (deviations from the master specification)
- **Lost while in manual mode:** playtime analysis (§12, §13), playtime snapshots and recent or historical interests, achievements, sustained-playtime evaluation (§25), and backlog scoring by playtime (§20.1, where U and D need playtime and recency).
- **Changed:** ownership is self-reported, so "owned" and "unowned" lists depend on what the user ticked.
- **Kept:** sign-in, catalogue, taxonomy, metadata, explicit satisfaction labels (now collected earlier and in larger numbers), and the whole Steam-import path for later.
- Later stages must treat playtime as optional input and lean on ratings. Content scoring (§16) is unaffected.
