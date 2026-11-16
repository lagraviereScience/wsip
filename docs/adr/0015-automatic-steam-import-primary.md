# ADR-0015: Automatic Steam import is the primary library source

- Status: Accepted · Date: 2026-11-15 · Decided by: product owner · Supersedes the default chosen in [ADR-0014](0014-sign-in-only-mode.md)

## Context
ADR-0014 made sign-in-only mode (a manual library, no Steam Web API key) the default.
The product owner then clarified that the main feature is: **sign in through Steam, and the
app reads the library, playtime and activity automatically.** Picking games by hand is not
wanted.

Steam OpenID returns only a SteamID (no data scopes), and `IPlayerService/GetOwnedGames`
requires a Web API key. The key is a **server-side secret registered once by the site
operator**. Users never see or need one.

## Decision
- The operator registers a Steam Web API key and sets `STEAM_WEB_API_KEY` in `.env`. With
  the key set, `library_mode` is `steam_import`, the flow built in Stage 2.
- Sign-in queues an import. Libraries re-sync daily for recently active users, and Settings offers "Sync now".
- Manual mode from ADR-0014 stays only as a **fallback when no key is configured**. It is not the product path.
- Users' Steam "Game details" must be public. The app detects private libraries and explains how to fix this.

## Verification (2026-11-15, live)
A real import of the owner's library succeeded in about 10 seconds: 539 games, 265 played,
529,690 minutes total, 2,306 minutes in the last two weeks. Store metadata was ingested for
513 games, while 25 are delisted. Achievement progress was fetched for the 10 most recently
played games. All signed-in pages render the real data.

## Consequences
- The spec's playtime-based features (§12, §13, §20.1, §25) are back in scope.
- The key must stay confidential. It is never logged (test-enforced) and must be rotated if it leaks.
- Steam Web API terms apply: fetch user data only at the user's request, and disclose the stored data in the privacy policy (OPEN_QUESTIONS #15).
