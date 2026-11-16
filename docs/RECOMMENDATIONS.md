# Recommendation engine: content-based baseline (`content-v2`)

> **Stage 4 changes (`content-v1` → `content-v2`).**
> - The profile has a fourth signal, explicit **feedback** (§2).
> - Explicitly rejected games are hard filters (§4).
> - When a collaborative model is deployed, its percentile is blended into Match
>   ([COLLABORATIVE.md](COLLABORATIVE.md) §4).
>
> - **Stage 5**: when a calibrated satisfaction model is deployed, "satisfaction" in
>   the category formulas below is predicted P(satisfied) × 100 instead of Match. The
>   unowned weight is configurable (`unowned_satisfaction_weight`), and satisfaction must
>   carry at least half of every category's weight ([SATISFACTION.md](SATISFACTION.md) §4).
>
> Everything else below is unchanged from Stage 3.

This document specifies the Stage 3 engine: what it computes, the formulas, and
every tunable parameter. The code follows it one-to-one:

| Part | Code |
|---|---|
| Parameters | `backend/app/recommendations/params.py` (`EngineParams`, `PARAMS_VERSION`) |
| Game vectors | `backend/app/recommendations/features/vectors.py` |
| Player profile | `backend/app/recommendations/profiling/preferences.py` |
| Compatibility | `backend/app/recommendations/ranking/compatibility.py` |
| Category formulas | `backend/app/recommendations/ranking/scores.py` |
| Explanations | `backend/app/recommendations/ranking/explain.py` |
| Candidates and runs | `backend/app/services/recommendations.py` |
| Discovery and player counts | `backend/app/services/discovery.py` |

The engine code is pure Python with no database, network or clock access, so
every number can be checked with synthetic data
(`backend/tests/unit/test_recommendation_engine.py`). No language model is used
anywhere.

All values below are **starting baselines** (spec §16: "configurable and
subsequently evaluated against observed satisfaction"). Each profile and
recommendation run stores `PARAMS_VERSION` and the full parameter set it used.

## 1. Game vectors (spec §10, §14)

A game is a sparse map `G = {feature: (x, m)}`:
- `x` is the strength or presence of the feature, from 0 to 1.
- `m` is metadata confidence, from 0 to 1.

A feature that is absent from the map is **unknown**, never zero.

- **Sources** are merged per feature:
  - `x` is the confidence-weighted mean of the source values.
  - `m = 1 − Π(1 − m_s)`, so independent sources reinforce each other.
- **Within-category shares** (spec §13) stop a game with five genres from counting five times:
  - `share(f) = x_f·m_f / Σ_{f' in same category} x_f'·m_f'`
  - A game's shares within one category sum to 1.
- **Roll-up**: a feature's share is added to each of its ancestors. Because shares partition 1, a parent's rolled-up share is at most 1. A parent and its children are therefore never independent evidence.

## 2. Player profile (spec §11–§13, §15)

The inputs are:
- the owned library;
- explicit ratings, including games played elsewhere;
- the game vectors;
- catalogue prevalence `P(f)`: the mean rolled-up share of `f` across catalogue games that have any feature in `f`'s category.

### Playtime transforms (spec §12)

| Name | Formula | Parameter |
|---|---|---|
| Lifetime | `H_total = ln(1 + min(h, 1000)) / ln(1001)` | `lifetime_cap_hours` |
| Recent | `H_recent = 1 − exp(−h_recent / 8)` | `recent_scale_hours` |
| Recency | `R = 2^(−days_since_last_play / 90)` | `recency_half_life_days` |
| Recent activity | `max(H_recent(2-week minutes), R · H_total)` | — |

Unknown playtime (manual entries) is **never** treated as 0 hours; such games add no behavioural signal.

Steam reports only a two-week window. Until snapshots span 30 days, "recent" uses that window plus decayed recency. No history is invented (spec §12).

### Three separate signals per feature

The three signals are kept apart (spec §13: playtime is not satisfaction).

1. **Behaviour, historical**:
   - `timeShare(f) = Σ_g rolled_g(f) · H_total(g) / Σ_g H_total(g)`, over owned games with any feature in `f`'s category.
   - `lift = timeShare / P(f)`, then `b_hist = clamp(log2(lift) / 2, −0.5, 1)`.
   - A feature 4× over-represented in your playtime scores +1.
   - Negatives are capped at −0.5, because playing little of something is weak evidence of dislike (`behaviour_min_value`).
   - Confidence is `0.6 · (1 − exp(−n / 3))`, where `n` is the confidence-weighted number of owned games carrying `f` (`behaviour_max_confidence`, `behaviour_evidence_k`).
2. **Behaviour, recent**: the same lift, computed on recent activity.
3. **Satisfaction** (explicit ratings, primary label):
   - `s = Σ w·r / (Σ w + 1)`, where `r = rating / 2` and `w = rolled share · m`. The `+1` prior shrinks thin evidence towards 0.
   - Confidence is `1 − exp(−Σw / 1.5)`.

Behaviour is `0.7 · b_hist + 0.3 · b_recent`, weighted by confidence (`recent_blend`).

4. **Feedback** (Stage 4: reactions on recommendation cards):
   - `fb = Σ w·v / (Σ w + 1)` over games with feedback, with `w` = rolled share × metadata confidence × reaction weight.
   - Values and weights:

     | Reaction | Value | Weight |
     |---|---:|---:|
     | Favourite | +1 | 1.0 |
     | Like | +0.6 | 0.7 |
     | Save for later | +0.3 | 0.3 |
     | Dislike | −0.6 | 0.7 |
     | Not my type | −1 | 1.0 |

   - "Not interested" and "already played" carry no feature evidence.
   - When a game has several reactions, the strongest decides: not my type > dislike > favourite > like > save.
   - Confidence is `1 − exp(−Σw / 1.5)`.
   - Parameters: `feedback_values`, `feedback_weights`, `feedback_prior_weight`, `feedback_evidence_k`.

The inferred preference combines satisfaction (weight 1.0), feedback (weight 0.8, `feedback_weight`) and behaviour (weight 0.5), each weighted by its confidence:
- `value = Σ v·c·W / Σ c·W`, in −1…1
- `confidence = 1 − Π(1 − c)`, in 0…1

Strength and confidence are stored separately (spec §15).

### Manual preferences and exclusions

- A manual value (−1…1) **replaces** the inferred value at confidence 1 (spec §11).
- An exclusion is a **hard filter**, applied before ranking in every category (spec §11, §19).
- Excluding a parent ("Horror") excludes games tagged with any descendant ("Psychological horror"). Excluding a child does not exclude its parent.
- A game is excluded when it carries the feature with `x ≥ 0.3`, which means any Steam-tag evidence at all (`exclusion_min_value`).

### History

- Every profile computation is a `profile_runs` row with its parameters.
- `user_feature_preference_history` records only values that changed (by at least 0.01), including features that disappeared.
- Manual changes are appended to `user_preference_events`.

## 3. Compatibility (spec §16)

For a game and the player's effective preferences:

1. **Resolve** each known game feature to the most specific node on its lineage (feature → parent → … → root) where the player has a usable preference: a manual one, or one with confidence ≥ 0.1. Features with no usable preference anywhere on the lineage don't move the score.
2. **Group** features that resolve to the same node and keep the strongest `x`. Then **drop** any resolved node that is an ancestor of another resolved node, so the most specific match wins within a lineage.
3. **Contribution** of node `r` in scoring group `g`:
   - `t = p · x · w` and `d = x · w`
   - `w = c · m`: preference confidence (1 for manual preferences) times metadata confidence.
4. **Group score** `S_g = Σt / Σd`, in −1…1.
   - Reliability `ρ_g = D_g / (D_g + 0.5)`, with `D_g = Σd` (`evidence_shrink_k`).
5. **Raw score** `S = Σ_g W_g · ρ_g · S_g / Σ_{g with metadata} W_g`.
   - Groups with no known game metadata are left out and the weights renormalised. Missing metadata is never a penalty.
6. **Match** `= 50 + 50 · S`, on 0…100. 50 means neutral or unknown.

Spec §16 weights (`group_weights`):

| Group | Weight |
|---|---:|
| Genres and themes | 0.25 |
| Gameplay mechanics | 0.30 |
| Game modes | 0.20 |
| Game structure | 0.15 |
| Pace and complexity | 0.10 |

**Exact decomposition.** Each contribution's points are `50 · (W_g / ΣW) · ρ_g · t / D_g`. The points add up to Match − 50, and the UI's "Why this score" panel shows them.

**Reported alongside the score:**
- **Metadata confidence**: the weight-averaged reliability per group, where unknown groups count as 0.
- **Preference coverage**: the share of the game's feature salience that has a known preference.
- **Recommendation confidence**: `√(metadata confidence × coverage)`, labelled high (≥ 0.6), medium (≥ 0.35) or low.

The score is an uncalibrated compatibility value. The UI calls it **"Match"** and never shows it as a percentage or probability (spec §18, §33).

## 4. Categories (spec §19, §20)

Candidate generation and ranking are separate steps.

**Explicit negatives** (Stage 4) are removed from candidates in every category:
disliked, "not interested", "not my type", already played, and rated Disliked or
Hated. Stored lists also hide them as soon as the feedback is given, before the
rebuild ([BEHAVIOUR.md](BEHAVIOUR.md) §2).

| Category | Candidates | Ranking |
|---|---|---|
| **Owned** (Games I Should Play) | Owned games of type `game` that have metadata. Excluded: games with 100 h or more, and games played in the last 14 days (`owned_exclude_*`) | `0.85 · Match + 0.15 · Backlog` |
| **Unowned** (Games I Should Buy) | Catalogue games neither owned nor rated, with at least 200 reviews (`unowned_min_reviews`) | `Match`. Price and reviews are shown separately |
| **Trending** | Games with trend metrics, not owned | `0.80 · Match + 0.20 · Trend` |

**Backlog** (spec §20.1):
- `U = exp(−hours / 20)`, `D = 1 − exp(−days / 90)`, `Backlog = 100 · (0.65·U + 0.35·D)`.
- Never played gives 100. An unknown last-played date gives `D = 0`.

**Similar to a favourite.** Favourites are the games you marked as favourite, then the games you loved (rating ≥ 1), then your most-played games (10 h or more).
- The unowned list adds "Similar to X" when the cosine similarity of rolled-up shares is at least 0.6 (`similar_min_cosine`).
- The similarity also counts as a candidate source.

**Filters** (spec §20.2) are applied when the list is read, not when it is ranked: maximum price, free-to-play only, minimum positive reviews, release period, and multiplayer or singleplayer.

## 5. Trending (spec §20.3)

- **Input**: concurrent players sampled from `ISteamUserStats/GetNumberOfCurrentPlayers` every 2 hours for up to 400 tracked games, aggregated to daily averages. Tracked games are those with 1,000+ reviews or on Steam's charts. Nothing is scraped.
- **Metrics**:
  - `growth_7 = ln((avg_last_7 + 10) / (avg_prev_28 + 10))`
  - `acceleration = growth_7 − growth_7 measured 7 days earlier`
- **Data needed**: 7 + 7 + 28 = **42 days**.
- **Quality checks**: each window needs at least 80% of its days present (days with 4+ samples), and at least 100 average players.
- **Score**: `Trend = 0.70 · pct(growth_7) + 0.30 · pct(acceleration)`, using percentile ranks among eligible games.
- **Until there is enough data**, the trending run is stored with `data_state = 'unavailable'` and an explanatory note. **No trend score is fabricated.**
  - The page shows collection progress, plus a separate "Popular right now" list.
  - That list ranks by player count and is labelled as absolute popularity, **not** a trend.

## 6. Explanations (spec §33)

Every sentence is built from data that moved the score.

| Code | Built from |
|---|---|
| `feature_match` | A positive contribution of at least 1 point; the template depends on its group |
| `recent_interest` | Same, when that feature is a *rising* interest: recent ≥ 0.6, at least 0.25 above lifetime, recent confidence ≥ 0.3 |
| `manual_preference` | A contribution from your own setting |
| `feature_conflict` | A negative contribution of 1 point or more (shown as a caution) |
| `broad_match` | No single feature reaches 1 point, but the positive points add up to at least 1; names the two largest |
| `similar_to_favourite` | Cosine similarity of at least 0.6 to a favourite |
| `never_played`, `barely_played`, `dormant` | Library facts (owned category) |
| `trend_growth` | Measured growth versus the previous four weeks |
| `unknown_preferences` | No contribution at all |

## 7. Overriding parameters

Set `RECOMMENDER_OVERRIDES` in `.env` to a JSON object of `EngineParams` fields, for example:

```
RECOMMENDER_OVERRIDES={"owned_backlog_weight": 0.25, "owned_satisfaction_weight": 0.75, "group_weights": {"game_modes": 0.3}}
```

Unknown keys or wrong types stop the app at startup. A changed parameter set takes effect on each user's next rebuild, and every run records the parameters it used.

## 8. Known limitations (to evaluate in later stages)

- **Prevalence is computed on the shared catalogue**, which for now is mostly early users' libraries plus discovered games. A feature common in your own library therefore looks less distinctive than it would against all of Steam.
- **Matches cluster between about 50 and 65**, because preferences are confidence-weighted and many features are mildly positive or negative. Ranking is what matters. Scores are not calibrated, so they are labelled "Match", not percentages.
- **Behavioural dislikes cluster at −0.5**, the cap, for features you own but rarely play.
- **Weights are the spec's starting values.** Evaluating them against post-play satisfaction (spec §25) needs the feedback collection planned for later stages.
