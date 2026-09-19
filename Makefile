# Entry point for every check. CI runs `make verify` and nothing else, so a
# green local run and a green pipeline cannot diverge.
#
# The determinism envelope (D9) is exported here rather than set inside Python:
# BLAS and OpenMP read their thread counts when first imported, so a process that
# sets them late looks compliant and is not. trading.runtime.determinism holds
# the authoritative list and verifies it at runtime; a test asserts this file,
# the Dockerfile and the CI workflow all declare exactly that set.

export PYTHONHASHSEED := 0
export TZ := UTC
export OMP_NUM_THREADS := 1
export OPENBLAS_NUM_THREADS := 1
export MKL_NUM_THREADS := 1
export NUMEXPR_NUM_THREADS := 1
export VECLIB_MAXIMUM_THREADS := 1
export POLARS_MAX_THREADS := 1

UV ?= uv
RUN := $(UV) run
IMAGE ?= trading-system:dev

.DEFAULT_GOAL := verify
.PHONY: verify install lint format typecheck banned models spec schemas codegen test test-fast \
        image image-digest up down clean

## Full gate. Ordered cheapest-first so the fast checks fail fast.
verify: lint typecheck banned models spec schemas test

install:
	$(UV) sync --all-packages

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck:
	$(RUN) mypy packages apps tools tests

## D3, D5, D6, D9 — static rules ruff cannot express.
banned:
	$(RUN) python tools/banned_patterns.py

## D3 — the runtime half: contract fields that admit naive timestamps.
models:
	$(RUN) python tools/model_audit.py

## The committed specification text must still match the document it came from.
spec:
	$(RUN) python tools/extract_spec.py --check

## Contract shapes must match the checked-in lock, and the generated Pydantic
## models must match the declarations they come from.
schemas:
	$(RUN) python tools/schema_registry.py --check
	$(RUN) python tools/codegen.py --check

## Regenerate the contract models after changing a declaration.
codegen:
	$(RUN) python tools/codegen.py
	$(RUN) python tools/schema_registry.py --accept

test:
	$(RUN) pytest

## Everything except the layers that need a broker, a database or a daemon.
test-fast:
	$(RUN) pytest -m "unit or property or golden"

## Build the runtime from the digest-pinned base. Refuses an unpinned base:
## an image built from a moving tag cannot be rebuilt, which makes the
## environment fingerprint recorded on an experiment a false claim.
image:
	@BASE=$$(grep -v '^#' infra/docker/base-image.pin | grep -v '^$$' | head -1); \
	case "$$BASE" in \
	  *@sha256:PIN-REQUIRED) \
	    echo "infra/docker/base-image.pin is unpinned. Resolve and commit a digest:"; \
	    echo "  docker pull python:3.12-slim-bookworm"; \
	    echo "  docker image inspect -f '{{index .RepoDigests 0}}' python:3.12-slim-bookworm"; \
	    exit 1 ;; \
	  *@sha256:*) ;; \
	  *) echo "base-image.pin must reference a digest, got: $$BASE"; exit 1 ;; \
	esac; \
	docker build -f infra/docker/Dockerfile --build-arg BASE_IMAGE="$$BASE" -t $(IMAGE) .

## The digest the runtime must inject as TRADING_CONTAINER_DIGEST.
image-digest:
	@docker image inspect -f '{{.Id}}' $(IMAGE)

up:
	docker compose -f infra/docker/compose.yaml up -d

down:
	docker compose -f infra/docker/compose.yaml down -v

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .hypothesis
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
