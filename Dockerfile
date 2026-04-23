# syntax=docker/dockerfile:1.6

# --- Stage 1: UI builder ---
FROM node:20-slim AS ui-builder
# git is required because some npm deps resolve via git (e.g. Baileys optional deps).
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm install --no-audit --no-fund --loglevel=error
COPY ui/ ./
RUN npm run build

# --- Stage 2: WhatsApp bridge builder ---
FROM node:20-slim AS bridge-builder
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/bridge
COPY bridge/package*.json ./
RUN npm install --no-audit --no-fund --loglevel=error
COPY bridge/ ./
RUN npm run build

# --- Stage 3: Python runtime ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl ca-certificates git nodejs \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (layer-cached on pyproject/uv.lock)
# pyproject.toml force-includes `bridge/` into the wheel, so its source must
# be present when hatchling runs during `uv pip install -e .`.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY roboclaw/ roboclaw/
COPY bridge/   bridge/
RUN uv pip install --system --no-cache -e .

# Built artifacts from earlier stages (merged into the already-copied bridge/ dir)
COPY --from=ui-builder     /app/ui/dist              /app/ui/dist
COPY --from=bridge-builder /app/bridge/dist          /app/bridge/dist
COPY --from=bridge-builder /app/bridge/node_modules  /app/bridge/node_modules

RUN mkdir -p /root/.roboclaw /root/.cache/huggingface

EXPOSE 8765 18790 1455

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8765/api/health || exit 1

ENTRYPOINT ["roboclaw"]
CMD ["status"]
