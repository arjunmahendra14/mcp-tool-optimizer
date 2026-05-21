# mock-mcp-servers

This folder contains 10 mock [fastmcp](https://github.com/jlowin/fastmcp) Python servers that simulate an on-call incident response agent's bloated tool set. They are the **"before" state** for an MCPForge optimization demo.

All tools return realistic fake data — no real API calls are made.

## Why this exists

The goal is to show that a typical on-call agent is given far too many tools. Most tools ("COLD" tools) are never called during real incidents. MCPForge analyses tool-call telemetry from Truefoundry and produces a trimmed Virtual MCP containing only the "HOT" tools actually needed.

| Step | What happens |
|------|--------------|
| 1 | Register all 10 servers on Truefoundry as hosted stdio MCP servers |
| 2 | Bundle them into a single Virtual MCP called `oncall-tools-bloated` |
| 3 | Run `seed_metrics.py` to fire 80 incident prompts at the agent |
| 4 | Use MCPForge to analyse the call distribution and produce an optimised Virtual MCP |

---

## Tool inventory

| Server | HOT tools | COLD tools | Total | Expected calls after seeding |
|--------|-----------|------------|-------|------------------------------|
| datadog_mcp | query_metrics, list_monitors, get_dashboard, search_logs, silence_monitor | export_dashboard_pdf, create_slo, list_hosts | 8 | ~120 |
| slack_mcp | send_message, post_to_channel, create_thread | list_channels, invite_user | 5 | ~60 |
| kubernetes_mcp | restart_pod, get_pod_logs, scale_deployment | list_namespaces, describe_node | 5 | ~55 |
| pagerduty_mcp | escalate_incident, acknowledge_alert | resolve_incident, get_oncall_schedule, create_incident, list_services | 6 | ~25 |
| github_mcp | — | list_repos, create_pr, review_pr, merge_pr, create_issue, close_issue, list_commits, search_code | 8 | ~0 |
| sentry_mcp | — | list_issues, get_issue_detail, resolve_issue, assign_issue, search_events | 5 | ~0 |
| confluence_mcp | — | search_pages, get_page, create_page, update_page | 4 | ~0 |
| jira_mcp | — | create_ticket, update_ticket, search_tickets, assign_ticket, close_ticket, get_sprint | 6 | ~0 |
| linear_mcp | — | create_issue, update_issue, list_projects | 3 | ~0 |
| notion_mcp | — | search_pages, create_page, update_page, list_databases, query_database | 5 | ~0 |
| **Total** | **13** | **42** | **55** | **~260 calls, 0 COLD** |

---

## Test a server locally

```bash
# Install fastmcp if you don't have it
pip install fastmcp

# Run a server in dev mode (opens the MCP inspector UI)
fastmcp dev mock-mcp-servers/datadog_mcp/server.py

# Or run it directly
cd mock-mcp-servers/datadog_mcp
python server.py
```

---

## Register on Truefoundry

Each server is registered as a **hosted stdio MCP server** using `uvx` to install it from this repo.

Example JSON config for the Truefoundry UI (repeat for each server, replacing `datadog` → other names):

```json
{
  "name": "mock-datadog-mcp",
  "transport": "stdio",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/your-org/mcp-tool-optimizer#subdirectory=mock-mcp-servers/datadog_mcp",
    "datadog_mcp"
  ]
}
```

Or use the registration script to do it all at once:

```bash
export TF_CONTROL_PLANE_URL=https://your-workspace.truefoundry.com
export TF_API_KEY=your-api-key
export REPO_URL=https://github.com/your-org/mcp-tool-optimizer

python mock-mcp-servers/register_virtual_mcp.py
```

This creates a Virtual MCP called **`oncall-tools-bloated`** with all 10 servers bundled.

---

## Seed tool-call metrics

Once the Virtual MCP is registered and the agent is deployed on Truefoundry:

```bash
export TF_CONTROL_PLANE_URL=https://your-workspace.truefoundry.com
export TF_API_KEY=your-api-key

python mock-mcp-servers/seed_metrics.py
```

The script fires 80 incident-response prompts at the agent with a 1-second delay between each. After it completes, Truefoundry analytics will show that only the 13 HOT tools were ever called.
