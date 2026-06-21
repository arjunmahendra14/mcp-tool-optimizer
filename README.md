# MCPForge

Other MCP filters make you write a list of tools to keep.  
MCPForge watches which tools you actually call and keeps those — automatically.

Static filters need maintenance. MCPForge learns.

MCPForge is a platform-agnostic MCP proxy that sits between any agent and any MCP server pool. It intercepts every tool call, builds a usage model over time, and dynamically filters the `tools/list` response so agents only see the tools that actually matter — saving context, reducing latency, and improving model focus without any manual configuration.

---

## The problem

Connecting multiple MCP servers dumps every tool schema into the model's context window whether or not those tools get called. With 10 servers this can exceed 50k tokens of dead weight per request. Every existing solution requires manually curating an allowlist or deny list — which means upfront work, ongoing maintenance, and configs that go stale as usage patterns change.

---

## How MCPForge is different

| | MCPForge | mcp-filter | tool-filter-mcp | MCP Funnel |
|---|---|---|---|---|
| Configuration required | None | Manual allowlist | Manual regex list | Manual filter rules |
| Learns from usage | ✓ | ✗ | ✗ | ✗ |
| Session-type awareness | ✓ | ✗ | ✗ | ✗ |
| Latency-aware scoring | ✓ | ✗ | ✗ | ✗ |
| Auto-updates over time | ✓ | ✗ | ✗ | ✗ |
| Platform agnostic | ✓ | ✓ | ✓ | ✓ |

---

## How it works

- MCPForge proxies all tool calls between your agent and your MCP servers — your agent connects to MCPForge instead of directly to servers, zero other changes needed.
- Every tool call is logged. The optimizer scores each tool by call frequency, recency, and latency — tools that never get called get pruned from the pool automatically.
- Session type is detected from your opening message (incident / planning / code / general) and the active tool pool adjusts accordingly — an incident session keeps ops tools, a planning session keeps project tools.

---

## Quickstart

```bash
pip install mcpforge
```

Create `mcpforge.yaml` with your server URLs (see the example below), then:

```bash
mcpforge start
# point your agent at http://localhost:8765/sse
# MCPForge handles the rest
```

No other configuration is required. On first run, all tools are active. The optimizer starts pruning once it has enough signal from real tool calls.

---

## mcpforge.yaml

```yaml
servers:
  # Any MCP server with an SSE endpoint
  - name: github-mcp
    url: http://localhost:9001/sse

  - name: slack-mcp
    url: http://localhost:9002/sse

  - name: datadog-mcp
    url: http://localhost:9003/sse

  - name: pagerduty-mcp
    url: http://localhost:9004/sse

  # Servers that run via a local command (e.g. mcp-remote for hosted MCP servers)
  - name: cloudflare
    command: npx
    args: ["mcp-remote", "https://mcp.cloudflare.com/mcp"]

proxy:
  host: 0.0.0.0
  port: 8765            # your agent connects to http://localhost:8765/sse

optimizer:
  interval_minutes: 15  # how often to re-score and update the tool pool
  default_threshold: 10.0  # tools below this score get pruned

  # Per-session-type thresholds — higher means stricter (fewer tools shown)
  thresholds:
    incident: 5.0   # incident sessions get a wider tool surface
    planning: 15.0  # planning sessions get a stricter one
    code: 10.0
    general: 10.0

database:
  path: mcpforge.db   # SQLite file; created automatically on first run
```

An `ANTHROPIC_API_KEY` is required for session classification. Put it in a `.env` file — MCPForge loads it automatically on start:

```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## CLI reference

| Command | Description |
|---|---|
| `mcpforge start` | Start the proxy, API, and optimizer. Begins learning immediately. |
| `mcpforge scores` | Print current tool scores — higher means more recently and frequently used. |
| `mcpforge optimize` | Trigger one optimization run manually. Normally runs on a schedule. |
| `mcpforge status` | Show active vs. pruned tool count and when the last optimization ran. |
| `mcpforge rollback` | Revert the tool pool to the state from a previous optimizer run. |

---

## Scoring algorithm

Each `(server, tool)` pair is scored by:

```
score = (call_count × recency_decay) / latency_penalty

recency_decay  = 1 / log(hours_since_last_call + e)
latency_penalty = log(p99_ms + 1)
```

In plain terms: tools called recently and frequently score highest. Slow tools score lower. Tools that have never been called score 0 and get pruned. Session type adjusts the pruning threshold — high-stakes sessions like incident keep more tools active, planning sessions apply a stricter cutoff.

---

## How it compares to manual filters

Tools like mcp-filter work well if you know exactly which tools you need upfront and your usage never changes. MCPForge is for everyone else — teams where usage patterns evolve, agents that get pointed at new servers, or anyone who doesn't want to maintain a config file by hand.

---

## Dashboard

A React dashboard is available at `http://localhost:5173` when running the dev server:

```bash
cd dashboard && npm install && npm run dev
```

Shows tool scores, the active/pruned pool, and an audit log with one-click rollback to any past pool state.

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Proxy status, pool size, cold-start flag |
| `GET` | `/api/scores` | All tools with scores and status, sorted by score |
| `GET` | `/api/pool` | Active and pruned tool lists |
| `GET` | `/api/audit` | Last 20 optimizer run records with pool snapshots |
| `POST` | `/api/optimize` | Trigger an optimizer run immediately |
| `POST` | `/api/rollback` | `{"run_id": N}` — revert pool to a past snapshot |
| `GET` | `/api/docs` | Swagger UI |

---

## Contributing

Pull requests welcome. Open an issue first for anything beyond a bug fix.

## License

MIT
