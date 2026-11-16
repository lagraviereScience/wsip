# ADR-0012: Canonical taxonomy defined in code, versioned mappings, raw tags kept

- Status: Accepted · Date: 2026-11-14

## Context
Spec §10 requires a hierarchical, extensible canonical taxonomy, provider-tag mappings with confidence and version, provenance, no double counting of parent and child features, and unknown kept distinct from absent.

## Decision
- The taxonomy and its mappings are reviewed source code in `app/taxonomy/seed.py`: 6 categories, 160 features, and 284 mappings from Steam tags and categories. `python -m app.cli sync-taxonomy` upserts it idempotently on every deploy, run by the `migrate` service.
- Categories are rows with a `scoring_group`. Genres and themes are separate categories but share the spec §16 weight group "genres and themes". Adding a category or feature never needs a schema change.
- Raw provider tags (`game_provider_tags`, with Steam vote weight and rank) are always stored. Canonical values (`game_feature_values`) are derived from them, one row per (game, feature, source), with confidence, mapping version and JSON evidence.
- Bumping `MAPPING_VERSION` keeps older mappings as `superseded`, and `sync-taxonomy` re-derives values for every game from the stored raw tags without calling any provider.
- A tag maps to its most specific feature. Parents are never filled in automatically. Subtree queries and scoring roll up with MAX, never SUM.
- No row means unknown. Absence is never stored as 0.
- Derivation heuristic, documented in `app/services/taxonomy.py`: value = 0.3 + 0.7 × weight/max_weight. Confidence = mapping confidence × rank factor × vote-volume factor. Developer-declared Steam categories give value 1.0 with the mapping's confidence. Synonyms combine with MAX.

## Consequences
- Taxonomy changes go through code review and are versioned in git.
- Later editing in an admin UI would need a different source of truth. Revisit if non-developers must curate the taxonomy.
