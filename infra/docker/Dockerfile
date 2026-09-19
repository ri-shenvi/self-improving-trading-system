# syntax=docker/dockerfile:1.7
#
# The research runtime. Built from a digest-pinned base (see base-image.pin) so
# that the environment fingerprint recorded on an experiment identifies
# something rebuildable.
#
# The image cannot contain its own digest — the digest is computed over the
# finished image — so the runtime injects it as TRADING_CONTAINER_DIGEST at
# `docker run`. trading.runtime.fingerprint refuses to start containerized
# without it, which is what stops an experiment recording a null provenance.

ARG BASE_IMAGE
FROM ${BASE_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer: resolved from the lockfile alone, so it is cached until a
# dependency actually changes. --frozen fails rather than silently re-resolving,
# which would break the fingerprint's claim to describe this environment.
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/
COPY apps/ ./apps/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-packages --frozen --no-dev


FROM ${BASE_IMAGE} AS runtime

# The determinism envelope (D9). Set here rather than in Python because BLAS and
# OpenMP read their thread counts on first import; a late assignment produces a
# process that passes inspection and still reduces floats in a machine-dependent
# order. trading.runtime.determinism verifies this set at startup, and a test
# asserts the Makefile, this file and the CI workflow declare exactly the same
# variables.
ENV PYTHONHASHSEED=0 \
    TZ=UTC \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    POLARS_MAX_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Research code runs without privileges and without a broker route (§33).
RUN groupadd --system --gid 1001 research \
    && useradd --system --uid 1001 --gid research --create-home research

WORKDIR /app
COPY --from=builder --chown=research:research /app /app
COPY --chown=research:research configs/ ./configs/
COPY --chown=research:research tools/ ./tools/

USER research

# Fail immediately if the envelope was overridden at `docker run`.
RUN python -c "from trading.runtime import require_deterministic_environment as r; r()"

ENTRYPOINT ["python"]
