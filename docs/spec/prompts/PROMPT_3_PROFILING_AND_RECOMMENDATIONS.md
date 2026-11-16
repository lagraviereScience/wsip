# PROMPT 3 — Gamer profiling and initial recommendation engine

Implement the mathematical player and game models.

This is the first major recommendation milestone.

The application must start generating real recommendations using content-based filtering.

## A. Game feature vectors

Implement canonical numerical game representations.

Normalise feature values and metadata confidence.

Handle unknown values correctly.

Prevent parent/child taxonomy double-counting.

## B. Player preference vectors

Implement:
- Historical preference calculations.
- Recent preference calculations.
- Playtime by canonical feature.
- Manual preference overrides.
- Explicit tag exclusions.
- Feature-level confidence.
- Preference update history.

Use the formulas in the master specification as initial configurable baselines.

Do not assume that playtime equals satisfaction.

## C. Content-based compatibility

Implement the initial weighted feature compatibility calculation.

Provide:
- Overall score.
- Category-level scores.
- Contributing features.
- Metadata confidence.
- Explanation of the match.

Write unit tests using synthetic users and synthetic games.

Examples must include:
- Strong genre compatibility.
- Strong mechanic compatibility.
- Contradictory preferences.
- Excluded tags.
- Incomplete metadata.
- Unknown player preferences.

## D. Recommendation generation

Implement the three required recommendation categories.

Owned:
- Games from the user's library.
- Backlog prioritisation.
- Predicted compatibility.

Unowned:
- Games missing from the user's library.
- Similarity-based discovery.
- Purchase metadata where available.

Trending:
- Initially support an unavailable/incomplete data state.
- Implement trend scoring only when reliable permitted historical player data exists.

Do not fabricate trending information.

## E. Recommendation explanations

Generate explanations directly from underlying score contributions.

Do not use an LLM.

Examples:
- Matches preferred survival mechanics.
- Similar to games with high player satisfaction.
- Strong compatibility with current RPG preferences.
- Owned but never played.

## F. Interface

Implement:
- Dashboard.
- Gamer profile page.
- Owned games page.
- Unowned recommendations page.
- Trending page.
- User preference controls.

## Acceptance criteria

- Real Steam data generates a gamer profile.
- The profile contains numerical preferences and confidence.
- Users can manually change preferences.
- Excluded tags are respected.
- All three recommendation categories exist.
- Owned and unowned filtering is correct.
- Content scoring is deterministic and tested.
- Recommendation explanations are traceable to actual features.
- No fabricated game data is shown as real data.
