# ADR-0007: Mock data isolation

- Status: Accepted · Date: 2026-11-14

## Context
Prompt 1 requires placeholder data for visual development, clearly separated from real data. The product must never present invented numbers as real recommendations.

## Decision
- All placeholders live in `frontend/src/mocks/` and use **fictional** game titles with generated artwork (no real games, no hot-linked store art).
- Pages read data only through `src/lib/data/`. Every loader returns `{ source: "mock" | "api", data }`.
- `PreviewBanner` is shown on every page whose data has `source === "mock"`.
- ESLint `no-restricted-imports` fails the build if anything outside `src/lib/data` imports `@/mocks`.
- `src/lib/data` is `server-only`, so fixtures are never bundled for the browser.

## Consequences
- Replacing a mock means changing one loader. The banner disappears automatically when every source on a page is `api`.
