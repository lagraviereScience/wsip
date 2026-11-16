# API reference

Generated from the application by `scripts/generate-api-docs.py` (that script is not in
this repository); the machine-readable schema is [api/openapi.json](api/openapi.json).
Checked by hand against `backend/app/api/routes/` on 2026-11-16: every route, query
parameter and limit below matches. Base path `/api`, JSON only. In production the
browser reaches it through the frontend, which forwards `/api/*` to the backend
([ADR-0023](adr/0023-frontend-only-traefik-routing.md)); the interactive docs
(`/api/docs`) exist only outside production.

- **Authentication**: Steam OpenID sign-in sets an HttpOnly session cookie
  (`wdywtp_session`). "session" endpoints return 401 without it. Sessions expire after
  30 days, or after 14 days without use.
- **CSRF**: state-changing requests ("+ Origin") must carry an `Origin` (or `Referer`)
  header equal to `PUBLIC_BASE_URL`; others get 403.
- **Rate limits**: 600 requests/min per session, 300/min per anonymous IP, 1200/min for
  public catalogue reads (429 with `Retry-After`), plus per-action limits (sign-in 20/min
  per IP, events 60/min, feedback 120/min, search 30/min, export 5/hour).
- **Errors**: JSON `{"detail": ...}`. Validation errors are 422; unexpected errors are 500
  with a `request_id` and no internals. Request bodies over 256 KiB get 413.
- Every user endpoint acts on the signed-in user's own data only.
- **Scoring mode**: `AI_GRADE` selects machine-learning (`"ai"`) or classic
  (`"classic"`) scoring for the whole deployment. `/api/health/ready` and every
  recommendation list report it as `scoring_mode`; each list's `run` also has
  `scoring_mode`, `config_version` and `algorithm` (docs/SCORING_MODES.md).

## auth

| Method | Path | Access | Description |
|---|---|---|---|
| `POST` | `/api/auth/logout-others` | session + Origin | Sign out every other device; this session stays signed in. |
| `POST` | `/api/auth/logout` | session + Origin | Logout |
| `GET` | `/api/auth/sessions` | session | The signed-in user's active sessions (no tokens or hashes are exposed). |
| `GET` | `/api/auth/steam/callback` | public | Steam Callback |
| `GET` | `/api/auth/steam/login` `?next` | public | Steam Login |

## catalogue

| Method | Path | Access | Description |
|---|---|---|---|
| `GET` | `/api/catalogue/features/{slug}/games` `?min_confidence&limit` | public | Games having the feature or any of its descendants (hierarchy-aware). |
| `GET` | `/api/catalogue/games/{game_id}` | public | Game Detail |
| `GET` | `/api/catalogue/providers` | public | Providers |
| `GET` | `/api/catalogue/taxonomy` | public | Taxonomy |

## feedback

| Method | Path | Access | Description |
|---|---|---|---|
| `POST` | `/api/me/events` | session + Origin | Impressions (actually visible cards), clicks, game page views, store visits. |
| `GET` | `/api/me/events` `?before&limit&feedback_only` | session | The user's own event history, newest first. |
| `GET` | `/api/me/feedback` | session | Every game the user reacted to or rated from a recommendation, to review or undo. |
| `PUT` | `/api/me/games/{game_id}/feedback/{kind}` | session + Origin | Turn one kind of feedback on (``on: true``) or undo it (``on: false``). |
| `PUT` | `/api/me/games/{game_id}/satisfaction` | session + Origin | "Did you enjoy this game?" Loved (2) ... Hated (-2); null clears the answer. |
| `GET` | `/api/me/games/{game_id}` | session | Game Page |
| `POST` | `/api/me/satisfaction-prompt/{game_id}` | session + Origin | Record that the question was shown, snoozed ("Not now") or declined. |
| `GET` | `/api/me/satisfaction-prompt` | session | Get Prompt |

## health

| Method | Path | Access | Description |
|---|---|---|---|
| `GET` | `/api/health/live` | public | Live |
| `GET` | `/api/health/ready` | public | Database, Redis and schema version checks (503 if any fails), plus the active recommendation ``scoring_mode`` ("ai" or "classic", from AI_GRADE). |

## me

| Method | Path | Access | Description |
|---|---|---|---|
| `PUT` | `/api/me/library/games/{steam_appid}` | session + Origin | Set whether the user owns a game and their rating (null = not played / no opinion). |
| `GET` | `/api/me/library/search` `?q` | session | Search Steam's store for games to add (results annotated with the user's state). |
| `GET` | `/api/me/library` | session | Get Library |
| `POST` | `/api/me/steam/sync` | session + Origin | Re-check game-details visibility and re-import the library (onboarding retry). |
| `GET` | `/api/me` | session | Get Me |

## privacy

| Method | Path | Access | Description |
|---|---|---|---|
| `GET` | `/api/me/export` | session | Download everything stored about the account, as JSON. |
| `GET` | `/api/me/privacy` | session | Get Privacy |
| `PUT` | `/api/me/privacy` | session + Origin | Opting out of global training takes effect from the next training run: the user's data is never read into a training dataset while opted out. |
| `DELETE` | `/api/me` | session + Origin | Permanently delete the account and all personal data. Requires ``{"confirm": "DELETE"}``. Signs the browser out. |

## recommendations

| Method | Path | Access | Description |
|---|---|---|---|
| `GET` | `/api/me/preferences/history` `?feature` | session | Preference History |
| `PUT` | `/api/me/preferences/{slug}` | session + Origin | Set a manual preference value and/or a hard exclusion for one canonical feature. |
| `DELETE` | `/api/me/preferences/{slug}` | session + Origin | Remove the manual value and exclusion; the inferred value applies again. |
| `GET` | `/api/me/profile` | session | Get Profile |
| `POST` | `/api/me/recommendations/refresh` | session + Origin | Rebuild profile and recommendations now (at most once a minute). |
| `GET` | `/api/me/recommendations/{category}` `?max_price_cents&free_only&min_review_pct&released_after&released_before&players&limit` | session | The latest list, built in the active scoring mode (``scoring_mode``: "ai" or "classic", from AI_GRADE; each ``run`` also carries its ``scoring_mode``, ``config_version`` and ``algorithm``). A list built in the other mode is never returned: the answer is ``status: "pending"`` while it is rebuilt. ``limit`` returns only the first N items (``total`` still counts all of them). |
