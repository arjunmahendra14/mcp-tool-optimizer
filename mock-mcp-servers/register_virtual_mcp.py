"""
Register all 10 mock MCP servers as a single Virtual MCP called oncall-tools-bloated
on Truefoundry.

Usage:
    TF_CONTROL_PLANE_URL=https://... TF_API_KEY=... REPO_URL=https://github.com/your-org/mcp-tool-optimizer python register_virtual_mcp.py
"""

import os
import json
import urllib.request
import urllib.error

TF_CONTROL_PLANE_URL = os.environ["TF_CONTROL_PLANE_URL"].rstrip("/")
TF_API_KEY = os.environ["TF_API_KEY"]
REPO_URL = os.environ.get("REPO_URL", "https://github.com/your-org/mcp-tool-optimizer")

VIRTUAL_MCP_NAME = "oncall-tools-bloated"

SERVERS = [
    {"name": "datadog",     "module": "datadog_mcp",     "path": "mock-mcp-servers/datadog_mcp"},
    {"name": "slack",       "module": "slack_mcp",       "path": "mock-mcp-servers/slack_mcp"},
    {"name": "kubernetes",  "module": "kubernetes_mcp",  "path": "mock-mcp-servers/kubernetes_mcp"},
    {"name": "pagerduty",   "module": "pagerduty_mcp",   "path": "mock-mcp-servers/pagerduty_mcp"},
    {"name": "github",      "module": "github_mcp",      "path": "mock-mcp-servers/github_mcp"},
    {"name": "sentry",      "module": "sentry_mcp",      "path": "mock-mcp-servers/sentry_mcp"},
    {"name": "confluence",  "module": "confluence_mcp",  "path": "mock-mcp-servers/confluence_mcp"},
    {"name": "jira",        "module": "jira_mcp",        "path": "mock-mcp-servers/jira_mcp"},
    {"name": "linear",      "module": "linear_mcp",      "path": "mock-mcp-servers/linear_mcp"},
    {"name": "notion",      "module": "notion_mcp",      "path": "mock-mcp-servers/notion_mcp"},
]


def build_server_configs():
    configs = []
    for s in SERVERS:
        configs.append({
            "name": f"mock-{s['name']}-mcp",
            "transport": "stdio",
            "command": "uvx",
            "args": [
                "--from",
                f"git+{REPO_URL}#subdirectory={s['path']}",
                s["module"],
            ],
        })
    return configs


def register_virtual_mcp(server_configs):
    url = f"{TF_CONTROL_PLANE_URL}/api/svc/v1/virtual-mcp"
    payload = {
        "name": VIRTUAL_MCP_NAME,
        "description": "Bloated on-call tool set — 10 servers, 55 tools. Before state for MCPForge demo.",
        "servers": server_configs,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {TF_API_KEY}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(f"SUCCESS: Virtual MCP '{VIRTUAL_MCP_NAME}' registered.")
            print(json.dumps(body, indent=2))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"ERROR {e.code}: {body}")
        raise


def main():
    print(f"Registering Virtual MCP: {VIRTUAL_MCP_NAME}")
    print(f"Control plane: {TF_CONTROL_PLANE_URL}")
    print(f"Repo: {REPO_URL}\n")

    configs = build_server_configs()
    print("Server configs to register:")
    for c in configs:
        print(f"  - {c['name']}: {' '.join(c['args'])}")
    print()

    register_virtual_mcp(configs)


if __name__ == "__main__":
    main()
