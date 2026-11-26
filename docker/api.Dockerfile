ARG UV_VERSION=0.11
# llama-server-build compiles the smart search runtime; llama-server-none skips it (faster dev images,
# smart search then reports a runtime error and search falls back to text).
ARG LLAMA_SERVER_STAGE=llama-server-build

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# llama-server (smart search, D4) from the pinned, digest-checked llama.cpp source, with the same script
# as the installers. It is built on the runtime's own Debian base: the official
# ghcr.io/ggml-org/llama.cpp:server-b12777 image is Ubuntu 26.04, whose glibc is newer than this one's.
FROM python:3.12-slim AS llama-server-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates cmake curl \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/build-llama-server.sh /build/build-llama-server.sh
RUN bash /build/build-llama-server.sh --out /opt/llama-server --cache /tmp/llama-cache \
    && rm -rf /tmp/llama-cache

FROM python:3.12-slim AS llama-server-none
RUN mkdir -p /opt/llama-server

FROM ${LLAMA_SERVER_STAGE} AS llama-server

FROM python:3.12-slim AS base

COPY --from=uv /uv /uvx /bin/
COPY --from=llama-server /opt/llama-server /opt/llama-server

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/apps/api/.venv/bin:$PATH" \
    BENTO_LLAMA_SERVER_PATH=/opt/llama-server/llama-server

WORKDIR /app

COPY apps/api/pyproject.toml ./apps/api/pyproject.toml
COPY apps/api/uv.lock ./apps/api/uv.lock
COPY apps/api/alembic.ini ./apps/api/alembic.ini
COPY apps/api/migrations ./apps/api/migrations
COPY apps/api/src ./apps/api/src

RUN cd /app/apps/api && uv sync --locked --no-dev --extra media

EXPOSE 8000

CMD ["python", "-m", "bento.interfaces.http.main"]
