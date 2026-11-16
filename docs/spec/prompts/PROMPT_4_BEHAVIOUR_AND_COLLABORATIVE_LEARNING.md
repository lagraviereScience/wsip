# PROMPT 4 — Behaviour tracking and collective recommendation learning

Implement the behavioural learning infrastructure.

The goal is to collect real evidence about the quality of recommendations.

## A. Event system

Implement an append-only event system.

Capture:
- Recommendation impressions.
- Visible position.
- Clicks.
- Game page views.
- Store visits.
- Favourites.
- Likes.
- Dislikes.
- Dismissals.
- "Already played".
- "Save for later".
- Post-play satisfaction.
- Subsequent playtime changes.

Store the associated recommendation and model identifiers.

## B. Feedback interface

Add user controls to recommendation cards:

- Like.
- Dislike.
- Favourite.
- Not interested.
- Not my type.
- Save for later.
- Already played.

After a user has had sufficient opportunity to play a recommended game, offer a simple satisfaction question.

Do not repeatedly interrupt users with feedback requests.

## C. Individual preference adaptation

Update the user's individual profile when relevant feedback arrives.

Manual preferences must remain authoritative.

A user must be able to undo or change previous feedback.

Maintain event history.

## D. Collaborative filtering

Implement and benchmark:

- LightFM.
- An alternative using implicit ALS or BPR.

Use a hybrid representation that incorporates user/game features where appropriate.

Distinguish:
- Ownership.
- Exposure.
- Clicks.
- Game engagement.
- Explicit satisfaction.

Do not treat every event as a positive interaction.

The model must be able to recommend games not present in a user's library.

## E. Cold-start behaviour

New users must receive content-based recommendations.

New games must use metadata-based similarity.

Do not fabricate collective knowledge.

## F. Privacy

Implement:
- Global training opt-out.
- User data isolation.
- Pseudonymised training datasets.
- Deletion handling.

## Acceptance criteria

- Events are stored reliably.
- Duplicate event submissions are handled.
- Impressions are distinct from clicks.
- Feedback affects individual profiles.
- Collaborative models train on valid data.
- New users still receive recommendations.
- Explicit negatives are respected.
- Global model training excludes users who opted out.
