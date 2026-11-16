# PROMPT 6 — Trending data, production hardening and release

Implement the final data integrations and prepare the application for public deployment.

## A. Trending information

Integrate an authorised player-statistics data source.

Evaluate available sources such as SteamCharts and SteamDB.

Do not assume scraping is permitted.

Implement:
- Player-count history.
- Recent average players.
- Historical comparison.
- Relative growth.
- Growth acceleration.
- Source reliability.
- Data freshness.

Implement the trending ranking formula from the master specification.

Trending recommendations must meet configurable eligibility requirements.

If a source becomes unavailable, continue serving the other recommendation categories.

## B. Additional metadata

Complete authorised integrations for:
- Game descriptions.
- Artwork.
- Genres.
- Tags.
- Reviews.
- Prices.
- Discounts.
- Completion times.

Store source attribution and timestamps.

## C. Application hardening

Complete:
- Authentication security.
- Session management.
- Rate limiting.
- Input validation.
- Logging.
- Monitoring.
- Database backups.
- Recovery procedures.
- Error handling.
- Security checks.
- Data deletion workflows.

## D. Deployment

Prepare a production Docker Compose configuration.

Support:
- Environment-specific configuration.
- Persistent volumes.
- Database migrations.
- Health checks.
- HTTPS through the reverse proxy.
- Secure secrets.
- Container restart policies.
- Controlled CPU and memory consumption.

Do not expose internal databases or inference services publicly.

## E. Performance

Test:
- 100 concurrent web users.
- Background synchronization.
- Recommendation generation.
- Database query performance.
- Model inference.
- Daily training.
- Queue behaviour.

The application should remain responsive during background training.

Document hardware consumption and performance bottlenecks.

## F. Final documentation

Produce:
- README.md.
- Architecture documentation.
- API documentation.
- Database schema.
- Machine-learning methodology.
- Data source documentation.
- Deployment guide.
- Backup and recovery guide.
- Security checklist.
- Testing report.
- Model evaluation reports.

## Final acceptance criteria

The application must:

1. Authenticate users through Steam.
2. Validate public game details.
3. Import actual gaming libraries.
4. Build individual gamer profiles.
5. Maintain a shared canonical game catalogue.
6. Analyse playtime by canonical feature.
7. Generate the three recommendation lists.
8. Learn from explicit and implicit behavioural information.
9. Use global and individual personalisation.
10. Prioritise actual satisfaction.
11. Retrain models daily.
12. Retain previous production models.
13. Respect user preferences and exclusions.
14. Run on the Linux server through Docker Compose.
15. Remain useful when external providers are unavailable.

---

# PART XII — GLOBAL DEVELOPMENT RULES

(Sections 37–43 as pasted: do not overengineer; do not fabricate information;
configuration over hardcoding; testing; development workflow; technical
documentation list (docs/architecture.md, database-schema.md, steam-integration.md,
game-taxonomy.md, player-profiling.md, recommendation-engine.md, machine-learning.md,
event-tracking.md, external-data-sources.md, privacy-and-security.md, deployment.md,
testing.md, decisions/); final instruction: build a system that gets better at
understanding what people actually enjoy playing.)
