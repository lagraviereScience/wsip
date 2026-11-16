# ADR-0017: Append-only behaviour log, separate current feedback state

- Status: Accepted · Date: 2026-11-15 · Stage 4

## Context
Prompt 4 asks for an append-only event system covering impressions, clicks, game
page views, store visits, every kind of feedback, post-play satisfaction and playtime
changes. Duplicates must be handled, impressions must differ from clicks, feedback
must update the profile, and users must be able to undo or change feedback. Spec §22
says signals are not equivalent: a price rejection is not a gameplay dislike.

## Decision
1. **One append-only table, `behaviour_events`**, for every event type. A database
   trigger rejects updates, except references becoming NULL when the referenced row
   is deleted. Each event stores its exposure context: run, category, position,
   model version and surface.
2. **Current state in separate tables.** Reactions live in `user_game_reactions`,
   ratings in `user_feedback`, question state in `satisfaction_prompts`. Profiles,
   filters and training read the state, never the log, so undo fully reverts an
   effect while the log keeps the history.
3. **The browser can send only exposure and navigation events** (impression, click,
   detail_view, store_visit), with idempotency keys. Feedback events are written by
   the server in the same transaction as the state change, so the log and the state
   cannot disagree and feedback can't be forged as an event.
4. **An impression is real visibility**: at least 50% of the card on screen for 1
   second, counted once per page view. Being generated or rendered is not enough.
5. **Exposure context is validated server-side.** A run that isn't the user's, or
   doesn't contain the game, is dropped. Category and model version are copied from
   the stored run.
6. **"Not interested" carries a reason.** Price, timing and "own it elsewhere" hide the
   game but add no feature or training evidence. "Not my type" is the explicit
   negative feature signal.
7. **Feedback is a fourth profile signal** with its own weight (0.8): below ratings
   (1.0), above playtime (0.5). Manual preferences still override everything.
8. **Explicit negatives are hard filters**, applied at candidate generation and again
   when stored lists are read, so they take effect before the background rebuild.

## Alternatives considered
- **Event sourcing (state derived by replaying the log)**: rejected. Every read would
  replay events, and undo semantics would live in replay code instead of a simple
  current row.
- **A third-party analytics SDK**: rejected. It would send raw behaviour to an
  outside service (privacy) and couldn't link events to our recommendation runs.
- **Logging impressions when lists are generated**: rejected. Spec §21 asks for actual
  visibility.

## Consequences
- The event table grows with use. Partitioning by month and a retention policy are
  future work (OPEN_QUESTIONS #26).
- Browser events are best effort (lost batches are not retried). Metrics built on
  impressions must allow for some loss.
