# syntax=docker/dockerfile:1.6

# --- Stage 1: UI builder ---
FROM node:20-slim AS ui-builder
WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# --- Stage 2: WhatsApp bridge builder ---
FROM node:20-slim AS bridge-builder
WORKDIR /app/bridge
COPY bridge/package*.json ./
RUN npm ci
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
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY roboclaw/ roboclaw/
RUN uv pip install --system --no-cache -e .

# Built artifacts from earlier stages
COPY --from=ui-builder     /app/ui/dist              /app/ui/dist
COPY --from=bridge-builder /app/bridge/dist          /app/bridge/dist
COPY --from=bridge-builder /app/bridge/node_modules  /app/bridge/node_modules
COPY bridge/package.json   /app/bridge/package.json

RUN mkdir -p /root/.roboclaw /root/.cache/huggingface

EXPOSE 8765 18790 1455

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8765/api/health || exit 1

ENTRYPOINT ["roboclaw"]
CMD ["status"]
