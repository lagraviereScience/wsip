# ADR-0005: Python 3.12 and uv

- Status: Accepted · Date: 2026-11-14

## Context
The ML libraries planned for later stages (implicit, LightGBM, scikit-learn) need dependable binary wheels. The development machine ships Python 3.10.

## Decision
- Pin the backend to **Python 3.12** (`requires-python = ">=3.12,<3.13"`). It is a mature release with broad wheel coverage for the ML stack. Upgrading is a deliberate later decision.
- Use **uv** for dependency resolution and locking (`uv.lock`, committed) and for installing into the image (`uv sync --frozen`).
- Quality gates: `ruff` (lint and format), `mypy --strict`, `pytest`.

## Consequences
- Reproducible installs locally and in Docker.
- Upgrading Python means changing `requires-python`, the Dockerfile `PYTHON_VERSION` and re-locking.
