# Mock data — visual development only

Everything in this folder is **fictional placeholder data** used to build and
review the interface before Steam sign-in, catalogue ingestion and the
recommendation engine exist.

Rules:

- Game titles, scores and playtimes here are invented. None of them refer to
  real games, real players or real model output.
- Only `src/lib/data/` may import from this folder. Pages and components must go
  through the data layer, which tags every result with `source: "mock"` so the
  UI shows a preview banner.
- A lint rule (`no-restricted-imports` in `eslint.config.mjs`) blocks imports
  of `@/mocks/*` from anywhere else.
- When a real API endpoint lands, switch the matching loader in `src/lib/data/`
  to it and delete the mock it replaced.
