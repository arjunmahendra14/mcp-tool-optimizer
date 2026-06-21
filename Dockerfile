FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy source needed for install
COPY pyproject.toml README.md ./
COPY mcpforge/ mcpforge/

# Install package (regular install, not editable) and fastmcp
RUN pip install --no-cache-dir ".[voyage]" && \
    pip install --no-cache-dir fastmcp

# Copy remaining application files
COPY mock-mcp-servers/ mock-mcp-servers/
COPY mcpforge.cloud.yaml mcpforge.yaml

# Copy startup helpers
COPY run_sse.py .
COPY start.sh .
RUN chmod +x start.sh

# SQLite DB lives on a mounted volume at /data
RUN mkdir -p /data

EXPOSE 8765

CMD ["./start.sh"]
