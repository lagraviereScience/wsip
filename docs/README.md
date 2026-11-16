# Documentation index

Every document the specification asks for (spec §42, Prompt 6 F) and where it lives.
Documents describe the code as implemented; where design and code differ, the code
and these documents win over the original specification.

Stage reports ([stages/](stages/)), the specification and its prompts ([spec/](spec/))
are historical records and are not updated. Where they disagree with the current
documents (for example on Traefik routing, ADR-0023), the current documents win.

**Not in this repository:** the backend and frontend test suites, the workstation
overlay `docker/dev/compose.dev.yaml`, `scripts/smoke-test.sh`,
`scripts/browser-check.py` and `scripts/generate-api-docs.py`. Test results in
[TESTING.md](TESTING.md) and [PERFORMANCE.md](PERFORMANCE.md) were recorded on the
original working tree and cannot be re-run from this checkout as is.

## Start here

| Need | Document |
|---|---|
| What the app is, how to run it | [../README.md](../README.md) |
| How it fits together | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| Install and deploy (step by step) | [../tutorial.md](../tutorial.md) |
| Deployment design | [../DEPLOYMENT.md](../DEPLOYMENT.md) |
| Scoring mode (AI_GRADE) | [SCORING_MODES.md](SCORING_MODES.md) |
| Back up, restore, recover | [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md) |
| Is it secure? | [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) |
| Is it tested? How fast is it? | [TESTING.md](TESTING.md), [PERFORMANCE.md](PERFORMANCE.md) |
| Final acceptance | [stages/STAGE_6_REPORT.md](stages/STAGE_6_REPORT.md) |

## Specification §42 document list → files

| Spec name | File |
|---|---|
| `architecture.md` | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| `database-schema.md` | [../DATABASE.md](../DATABASE.md) |
| `steam-integration.md` | [PROVIDERS.md](PROVIDERS.md) (Steam rows), ADR [0008](adr/0008-steam-openid-verification.md), [0013](adr/0013-steam-store-metadata-source.md), [0015](adr/0015-automatic-steam-import-primary.md) |
| `game-taxonomy.md` | ADR [0012](adr/0012-taxonomy-as-code.md); taxonomy in `backend/app/taxonomy/seed.py`; served at `GET /api/catalogue/taxonomy` |
| `player-profiling.md` | [RECOMMENDATIONS.md](RECOMMENDATIONS.md) §2 |
| `recommendation-engine.md` | [RECOMMENDATIONS.md](RECOMMENDATIONS.md) |
| `machine-learning.md` | [MACHINE_LEARNING.md](MACHINE_LEARNING.md) → [COLLABORATIVE.md](COLLABORATIVE.md), [SATISFACTION.md](SATISFACTION.md) |
| `event-tracking.md` | [BEHAVIOUR.md](BEHAVIOUR.md) |
| `external-data-sources.md` | [PROVIDERS.md](PROVIDERS.md) |
| `privacy-and-security.md` | [PRIVACY.md](PRIVACY.md), [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) |
| `deployment.md` | [../DEPLOYMENT.md](../DEPLOYMENT.md), [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md) |
| `testing.md` | [TESTING.md](TESTING.md), [PERFORMANCE.md](PERFORMANCE.md) |
| `decisions/` | [adr/](adr/README.md) (23 decision records) |

## Prompt 6 F list → files

| Required | File |
|---|---|
| README | [../README.md](../README.md) |
| Architecture documentation | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| API documentation | [API.md](API.md) (generated), [api/openapi.json](api/openapi.json) |
| Database schema | [../DATABASE.md](../DATABASE.md) |
| Machine-learning methodology | [MACHINE_LEARNING.md](MACHINE_LEARNING.md) |
| Data source documentation | [PROVIDERS.md](PROVIDERS.md) |
| Deployment guide | [../DEPLOYMENT.md](../DEPLOYMENT.md) |
| Backup and recovery guide | [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md) |
| Security checklist | [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) |
| Testing report | [TESTING.md](TESTING.md) |
| Model evaluation reports | [benchmarks/](benchmarks/) (synthetic) and every real training run's report in `training_runs.report` / `<models>/reports/` (`app.cli report`) |

## Other references

- Stage reports: [stages/](stages/) (one per implementation stage)
- Behaviour events and feedback: [BEHAVIOUR.md](BEHAVIOUR.md)
- Open questions and decisions still pending: [spec/OPEN_QUESTIONS.md](spec/OPEN_QUESTIONS.md)
- Original specification and stage prompts: [spec/](spec/)
