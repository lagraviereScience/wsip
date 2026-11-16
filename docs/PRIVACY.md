# Privacy (spec §23, §34; Prompt 4 F)

What the app stores about players, how it is used, and what players control.
Decisions: [ADR-0018](adr/0018-training-data-privacy-and-model-lifecycle.md).

> **Not legal advice.** The items under "Before public launch" need review by
> someone qualified in data-protection law (for example GDPR/UK GDPR, CCPA) and
> against Valve's Steam Web API terms (OPEN_QUESTIONS #15, #25).

## What is stored

| Data | Purpose |
|---|---|
| SteamID, public profile name, avatar | Sign-in and display |
| Library, playtime and its history, achievements | Gamer profile, recommendations |
| Ratings, feedback on games, manual preferences | Profile, recommendations, training labels |
| Behaviour events (impressions, clicks, game page views, store visits, feedback changes, playtime changes) | Measuring recommendation quality, training |
| Recommendation runs and items | Showing lists, auditing explanations |
| Sessions (hashed tokens only) | Signing in |

No passwords: sign-in is through Steam. No payment data.

## Controls (Settings → Privacy)

| Control | Effect |
|---|---|
| **Help improve recommendations for everyone** | On by default. When off, your data is never read into a training dataset, from the next training run on. Your own recommendations keep working: collaborative scores, once a model exists, are computed from your own data at serving time |
| **Keep my library synced daily** | Turns scheduled re-imports on or off (Steam terms: data on the user's request) |
| **Export my data** | `GET /api/me/export`: a JSON file with every section stored about you (17 sections, including all your events). Limited to 5 exports per hour |
| **Delete my account** | `DELETE /api/me` with `{"confirm": "DELETE"}` (the UI asks you to type DELETE). Deletes everything below and signs you out |

## Isolation

- Every `/api/me/*` endpoint acts on the signed-in user only.
- There is no endpoint that returns another player's profile, events or feedback.
- A recommendation run id sent by the browser is ignored unless it belongs to the
  signed-in user (tested).
- Raw events are visible only to their owner (`GET /api/me/events`) and in their
  export.

## Training data

- **Who**: active accounts that allow training. A missing settings row counts as
  opted out.
- **Pseudonyms**:
  - Each build replaces account ids with `HMAC-SHA256(salt, id)` using a random
    32-byte salt.
  - The salt is discarded when the build ends.
  - Datasets are never written to disk.
  - Pseudonyms can't be linked back to accounts afterwards, even by the operator.
- **What a dataset contains**: pseudonym, game id, signal channel, value and
  timestamp. No names, SteamIDs or free text.
- **What a model keeps**: item (game) factors and parameters only, with **no
  per-user rows**. Users are folded in at serving time from their own data.

## Account deletion

1. One transaction deletes the account and every row tied to it. All foreign keys
   to `users` cascade: profile, library, playtime history, achievements, ratings,
   feedback, satisfaction questions, preferences, events, recommendation runs,
   sessions and settings.
2. Pending background jobs for the account stop: the rebuild task checks that the
   account still exists. Its Redis cooldown keys are removed.
3. An `account_deletions` row records **only a timestamp**. The next scheduled
   training run then retrains even without new data, so the deployed model stops
   reflecting the deleted account as soon as a new model passes its gates.

**What deletion cannot do (no claim of machine unlearning):**
- Models trained before the deletion may still reflect that player's past
  interactions in their item factors. No individual can be recovered from them, but
  their influence isn't removed instantly.
- That influence ends when those versions are replaced and their artifacts pruned:
  - at most 5 artifacts are kept;
  - retired ones are deleted after 30 days.
- If retraining keeps failing its gates, the previous model stays deployed. The
  operator can retire it.
- Database backups (`scripts/backup-db.sh`) keep deleted data until they rotate out.
  The backup retention period must be stated in the privacy policy.

## Before public launch (needs review)

1. **Legal basis and default** for using behaviour in global training. It is
   opt-out today; some jurisdictions may require opt-in consent (OPEN_QUESTIONS #25).
2. Privacy policy:
   - data categories, purposes and retention (events are currently kept until
     account deletion);
   - backup retention;
   - processors (hosting).
3. Steam Web API terms for storing and processing library data (OPEN_QUESTIONS #15).
4. Data subject requests beyond self-service, such as a contact route and identity
   checks for players who lost access.
5. Children's data: Steam accounts can belong to minors.
6. Event retention: a time limit, or aggregation after N months.
