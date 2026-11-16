# Behaviour events and explicit feedback (Stage 4)

How the app collects evidence about recommendation quality (spec §21, §22, Prompt 4
A–C). Design decisions: [ADR-0017](adr/0017-behaviour-events-and-feedback-state.md).

| Part | Code |
|---|---|
| Tables | `backend/app/models/behaviour.py` |
| Services | `backend/app/services/feedback.py` |
| Data access | `backend/app/repositories/behaviour.py` |
| API | `backend/app/api/routes/feedback.py` |
| Browser queue | `frontend/src/lib/events.ts` |
| Card controls | `frontend/src/components/feedback/` |

## 1. The event log (`behaviour_events`)

- **Append-only.** A database trigger rejects any `UPDATE`, except a referenced
  game, feature or recommendation run becoming `NULL` when that row is deleted.
  Changes and undos are new events. Deleting an account deletes its events
  (`ON DELETE CASCADE`).
- **Every event records**:
  - the user, game (or feature), type, `occurred_at` and `received_at`;
  - the **exposure context**: recommendation run, category, visible position, model
    version (the run's `algorithm`, e.g. `content-v2` or `content-v2+cf-…`) and the
    surface (dashboard, play, buy, trending, game page, profile, library);
  - free-form `context` and `metadata`, limited to small, whitelisted keys.
- **Duplicates.** Browser events carry an idempotency key; `(user_id, idempotency_key)`
  is unique, and duplicates in a batch or across retries are counted and skipped.

| Type | Written by | When |
|---|---|---|
| `impression` | browser | A recommendation card was **at least 50% visible for 1 second**. Once per card per page view (the key contains a page-view id). Being generated is not an impression |
| `click` | browser | The card's title or artwork was clicked (opens the game page) |
| `detail_view` | browser | A game page was opened (once per page view) |
| `store_visit` | browser | The Steam Store link was followed |
| `like`, `dislike`, `favourite`, `save_for_later`, `not_interested`, `not_my_type`, `already_played` | server | The feedback action itself. `metadata.state` is `on` or `off` (undo); `cleared` lists contradicting feedback it switched off; `reason` holds the "not interested" reason |
| `satisfaction` | server | A rating was given, changed or cleared (`rating`, `previous`, `source`) |
| `satisfaction_prompt` | server | The post-play question was `shown`, `snooze`d or `decline`d |
| `playtime_change` | server | A library sync found more playtime than the previous sync. Records `delta_minutes`, `total_minutes`, the sync run, and the latest recommendation exposure of that game within 90 days (attribution) |
| `feature_preference` | server | A manual preference or tag exclusion changed (spec §21 "excluded tags") |

**Validation of browser events** (`record_client_events`):
- Only the four browser types are accepted; feedback cannot be forged as an event.
- Unknown games are rejected.
- A recommendation run that isn't the user's, or doesn't contain the game, is
  dropped from the event; the event is kept without exposure context.
- Category and model version always come from the stored run, never from the client.
- Timestamps outside the window from one day ago to five minutes ahead are replaced
  by the server time.
- Requests are limited to 100 events per request and 60 requests per minute per user.

The browser batches events every 4 seconds and flushes them with `keepalive` when the
page is hidden, so events survive navigation. Delivery is best effort: a lost batch
is never retried in a loop.

## 2. Feedback state (`user_game_reactions`)

Profiles, filters and training read the **current state**, never the log. Undoing an
action therefore fully reverts its effect, while the log keeps the history.

| Control | State | Effect on lists | Profile evidence (spec §22) | Training signal |
|---|---|---|---|---|
| Like | `reaction = like` | stays | +0.6, weight 0.7 | +2.5 interest |
| Dislike | `reaction = dislike` | **hidden** | −0.6, weight 0.7 | −4 negative |
| Favourite | `favourite` | stays; seeds "Similar to …" | +1.0, weight 1.0 | +4 interest |
| Save for later | `saved` | stays; listed on the dashboard | +0.3, weight 0.3 | +1.5 interest |
| Not interested | `dismissal`, `reason` | **hidden** | **none** | −1, **none** for price, timing or owned elsewhere |
| Not my type | `dismissal = not_my_type` | **hidden** | −1.0, weight 1.0 | −4 negative |
| Already played | `already_played` (+ optional rating) | **hidden** | only through the rating | only through the rating |

- **Contradictions** resolve in favour of the latest action. "Not my type" clears a
  like, a favourite and a save. "Favourite" clears a dislike and a dismissal. The
  event records what was cleared.
- **Explicit negatives are hard filters.** Disliked, dismissed, already played, and
  rated Disliked or Hated games:
  - are removed from candidates in every category;
  - are hidden at once from stored lists (`hidden_by_feedback`), before the
    background rebuild;
  - come back if the feedback is undone.
- **Undo**: every control toggles. A hidden card collapses into an "Undo" row. The
  Profile page lists every game with feedback, with filters and the same controls.
- **Rebuild**: each change queues a profile and recommendation rebuild after a 5 s
  debounce, without discovery.

## 3. Individual profile adaptation

Feedback is a **fourth signal** in the profile (`feedback`, `feedback_confidence` on
`user_feature_preferences`), kept separate from satisfaction (ratings), historical
behaviour and recent behaviour:

- `fb = Σ w·v / (Σ w + 1)` over games with feedback. `v` and `w` come from the table
  above, multiplied by the game's rolled-up feature share and metadata confidence.
  The +1 prior shrinks thin evidence.
- Confidence is `1 − exp(−Σw / 1.5)`.
- Combination weight **0.8**: weaker than ratings (1.0), stronger than playtime (0.5).
- When a game has several reactions, the strongest one decides:
  not my type > dislike > favourite > like > save.
- **Manual preferences stay authoritative.** A manual value replaces the inferred
  one at confidence 1, and feedback never writes manual preferences.

The parameters are in `EngineParams` (`feedback_values`, `feedback_weights`,
`feedback_weight`), so the engine version is now **`content-v2`**.

## 4. Post-play satisfaction question

"Did you enjoy X?" (Loved / Liked / Neutral / Disliked / Hated) is the primary
training label (spec §18). It is asked only when all of these hold:

1. The game appeared in one of your recommendation lists (any exposure event within
   180 days).
2. You own it and played **at least 2 hours after** that first exposure (summed
   `playtime_change` events), so games you already played before we recommended
   them never qualify.
3. You haven't rated it.

**Not interrupting:**
- At most one question is on screen at a time, as a dismissible card on the
  dashboard, never a modal.
- A shown question stays for 24 hours without counting again; after that, at most
  **one new question per 7 days**.
- "Not now" (×) snoozes that game for 14 days. "Don't ask about this game" stops it.
- A game is asked about at most twice.

"Already played" on a card asks the same question inline (optional, "Skip"
available).

## 5. Game page

`/games/{id}` shows the game, live Match and reasons computed from the current
profile, feedback controls and the Steam link. It records `detail_view` linked to the
latest recommendation run containing the game.
