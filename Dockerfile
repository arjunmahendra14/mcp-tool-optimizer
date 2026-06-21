# ── Stage 1: build the React dashboard ──────────────────────────────────────
FROM node:20-slim AS dashboard-builder
WORKDIR /dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy source + metadata, then install
COPY pyproject.toml README.md ./
COPY mcpforge/ mcpforge/
RUN pip install --no-cache-dir ".[voyage]" && \
    pip install --no-cache-dir fastmcp

# Copy remaining application code
COPY mock-mcp-servers/ mock-mcp-servers/
COPY mcpforge.cloud.yaml mcpforge.yaml

# Copy built dashboard from stage 1 — lands at /app/dashboard/dist
COPY --from=dashboard-builder /dashboard/dist /app/dashboard/dist

# Copy startup helpers
COPY run_sse.py .
COPY start.sh .
RUN chmod +x start.sh

RUN mkdir -p /data

EXPOSE 8765

CMD ["./start.sh"]
