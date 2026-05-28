# MCPForge

A platform-agnostic MCP proxy that keeps your agent's tool pool lean and smart.

Sits between your agent and any pool of MCP servers. Intercepts every `tools/list` and `tools/call`, learns which tools are actually used, and filters the list the agent sees — so the model spends fewer tokens on dead weight and picks the right tool more accurately.

## How it works

1. **Proxy** — Agent connects to one SSE endpoint (`http://localhost:8765/sse`) instead of each server directly. The proxy fans out to all upstream servers, aggregates their tools, and returns a filtered list.

2. **Scoring** — Every tool call is logged to SQLite with timestamp and latency. A background optimizer scores each `(server, tool)` pair using:
   ```
   score = (call_count × recency_decay) / latency_penalty
   ```
   Tools that haven't been called recently, or are slow, score lower.

3. **Session classification** — On the first tool call in a session, Claude Haiku classifies the session as `incident`, `planning`, `code`, or `general`. Each type has its own score threshold — incident sessions get a wider tool surface, planning sessions get a stricter one.

4. **Filtering** — `tools/list` returns only tools above the session's threshold. An agent working an incident sees 8 tools. A planning session sees 3. The model never sees the other 43.

## Quickstart

```bash
pip install mcpforge
```

Create `mcpforge.yaml`:

```yaml
servers:
  - name: my-server
    url: http://localhost:9001/sse

proxy:
  port: 8765

optimizer:
  interval_minutes: 15
  default_threshold: 10.0
  thresholds:
    incident: 5.0
    planning: 15.0
    code: 10.0
    general: 10.0
```

Create `.env` (auto-loaded on start):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Start the proxy:

```bash
mcpforge start
# point your agent at http://localhost:8765/sse
```

## Config reference

| Field | Default | Description |
|---|---|---|
| `servers[].name` | — | Logical name for this upstream server |
| `servers[].url` | — | SSE endpoint URL of the upstream MCP server |
| `proxy.host` | `0.0.0.0` | Host to bind the proxy on |
| `proxy.port` | `8765` | Port to bind the proxy on |
| `optimizer.interval_minutes` | `15` | How often to re-score and update the tool pool |
| `optimizer.default_threshold` | `10.0` | Minimum score to keep a tool active globally |
| `optimizer.thresholds.incident` | `5.0` | Score threshold for incident sessions |
| `optimizer.thresholds.planning` | `15.0` | Score threshold for planning sessions |
| `optimizer.thresholds.code` | `10.0` | Score threshold for code sessions |
| `optimizer.thresholds.general` | `10.0` | Score threshold for general sessions |
| `database.path` | `mcpforge.db` | Path to the SQLite database file |

## Dashboard

A React dashboard is available at `http://localhost:5173` when running the dev server:

```bash
cd dashboard && npm install && npm run dev
```

Shows tool scores (bar chart), active/pruned pool, and an audit log with one-click rollback to any past pool state.

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Proxy status, pool size, cold-start flag |
| `GET` | `/api/scores` | All tools with scores and status, sorted by score |
| `GET` | `/api/pool` | Active and pruned tool lists |
| `GET` | `/api/audit` | Last 20 optimizer run records with pool snapshots |
| `POST` | `/api/optimize` | Trigger an optimizer run immediately |
| `POST` | `/api/rollback` | `{"run_id": N}` — revert pool to a past snapshot |
| `GET` | `/api/docs` | Swagger UI |

## CLI

```
mcpforge start [--config path.yaml] [--env-file .env]
mcpforge scores      print current scores table
mcpforge optimize    trigger one optimization run
mcpforge status      show pool size and DB stats
```

## Cold-start behavior

On first run (empty database), all upstream tools are active. The optimizer needs at least one cycle of real tool calls before it has enough signal to prune anything. Cold-start mode is indicated in `GET /api/health` as `"cold_start": true`.
