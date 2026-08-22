# Veriquill in one container: the API, the CLI, and the built interface behind a
# single origin.
#
# Git is a runtime dependency, not a build one. The provenance engine reads real
# commit history out of a clone, so an image without git can start and then fail
# on the first candidate.

FROM node:22-alpine AS interface

WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

# git: cloning candidate repositories. No compilers: every dependency ships wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The package metadata and sources are copied before the install so the layer
# caches on dependency changes rather than on every edit.
COPY pyproject.toml README.md ./
COPY veriquill/ ./veriquill/

# The two optional model passes need the anthropic SDK, which is an optional
# dependency. The default image does not carry it, so those passes stay off no
# matter what the environment says, and the container is fully deterministic.
#
# Build with --build-arg INSTALL_LLM=true to include it. Even then both passes
# stay off until switched on: the extra makes them possible, not active.
ARG INSTALL_LLM=false
RUN if [ "$INSTALL_LLM" = "true" ]; then \
        pip install --no-cache-dir ".[llm]"; \
    else \
        pip install --no-cache-dir .; \
    fi

COPY --from=interface /ui/dist/ ./ui/dist/

# Analysis writes clones, caches, and the SQLite database here. Mount a volume on
# it: a container that loses this directory loses every stored dossier.
ENV VERIQUILL_DATA_DIR=/data \
    VERIQUILL_UI_DIST=/app/ui/dist \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data

EXPOSE 8000
CMD ["uvicorn", "veriquill.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
