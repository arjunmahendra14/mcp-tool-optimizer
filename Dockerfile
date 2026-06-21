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

# Install Python deps first (layer cache)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e ".[voyage]" && \
    pip install --no-cache-dir fastmcp

# Copy application code
COPY mcpforge/ mcpforge/
COPY mock-mcp-servers/ mock-mcp-servers/
COPY mcpforge.cloud.yaml mcpforge.yaml

# Copy built dashboard from stage 1
COPY --from=dashboard-builder /dashboard/dist dashboard/dist

# Copy startup helpers
COPY run_sse.py .
COPY start.sh .
RUN chmod +x start.sh

RUN mkdir -p /data

EXPOSE 8765

CMD ["./start.sh"]
