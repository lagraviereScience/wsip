# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Backend image: FastAPI API, Alembic migrations and (later) Celery workers
# share one image so code and schema versions can never drift apart.
#   target "runtime" (default) — production image, no test tooling
#   target "test"              — runtime + dev dependencies + tests
# ---------------------------------------------------------------------------
ARG PYTHON_VERSION=3.12.16

FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:${PYTHON_VERSION}-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM builder AS builder-dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    # Numerical libraries must not grab every core on a shared server.
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
# libgomp1: OpenMP runtime required by the collaborative-filtering library (implicit).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /var/lib/wdywtp/models && chown app:app /var/lib/wdywtp/models
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini pyproject.toml ./
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=2).status == 200 else 1)"]
# --proxy-headers trusts X-Forwarded-* only from FORWARDED_ALLOW_IPS (set in compose).
# Keep-alive above Traefik's 90 s idle timeout, so the proxy never reuses a connection
# uvicorn has just closed (sporadic "connection closed" errors in the Stage 6 load test).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers --no-server-header --timeout-keep-alive ${UVICORN_KEEPALIVE_S:-95}"]

FROM runtime AS test
COPY --from=builder-dev /opt/venv /opt/venv
COPY --chown=app:app tests ./tests
ENV PYTHONDONTWRITEBYTECODE=1
HEALTHCHECK NONE
CMD ["pytest", "-p", "no:cacheprovider"]
