# PROMPT 2 — Steam authentication, library import and game catalogue

Implement Steam authentication and the first real data ingestion pipeline.

## A. Steam OpenID

Implement proper Steam OpenID 2.0 authentication.

Follow official Valve documentation.

Implement secure sessions and server-side validation.

Create a user automatically when a Steam account first connects.

Store SteamID64.

Retrieve available public profile information.

Do not use mocked authentication in production code.

Use test fixtures for automated tests.

## B. Public game details requirement

The onboarding process must check whether the user's Steam game details are accessible.

If inaccessible:
- Explain how to change the Steam privacy setting.
- Prevent normal profile generation.
- Allow the user to retry verification.
- Do not silently create a misleading empty profile.

## C. Steam library import

Retrieve:
- Owned games.
- AppIDs.
- Game names where available.
- Total playtime.
- Recent playtime.
- Last played timestamps where available.
- Achievements where practical.

Use background jobs for imports.

Implement retry logic, caching, request throttling and error handling.

Record initial playtime snapshots.

## D. Central game catalogue

Implement:
- Canonical games.
- External identifiers.
- Source tracking.
- Game metadata ingestion.
- Duplicate resolution.

Steam AppID must be used as the first external identifier.

Do not create duplicates when the same game is imported by multiple users.

## E. Canonical taxonomy

Implement the hierarchical taxonomy described in the master specification.

Create a provider-tag mapping mechanism.

Import raw source tags and map them to canonical features.

Maintain mapping confidence and provenance.

Support:
- Genres.
- Themes.
- Mechanics.
- Game modes.
- Game structures.
- Pace and complexity.

Implement the first Steam metadata provider.

Implement the IGDB adapter only after checking its current commercial terms and required authentication.

Make other integrations modular.

Never scrape unauthorised websites.

## Acceptance criteria

- Steam authentication works.
- User identity is verified.
- Private game details are handled correctly.
- A real public library can be imported.
- Library data is stored persistently.
- Duplicate games are prevented.
- Playtime snapshots are recorded.
- Game features can be mapped and queried.
- Provider failures do not break Steam integration.
- Tests cover authentication, privacy failures, data import and duplicate handling.
