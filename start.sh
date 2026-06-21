#!/bin/bash
set -e

echo "Starting mock MCP servers..."
python run_sse.py datadog_mcp    9001 &
python run_sse.py slack_mcp      9002 &
python run_sse.py kubernetes_mcp 9003 &
python run_sse.py pagerduty_mcp  9004 &
python run_sse.py github_mcp     9005 &
python run_sse.py sentry_mcp     9006 &
python run_sse.py confluence_mcp 9007 &
python run_sse.py jira_mcp       9008 &
python run_sse.py linear_mcp     9009 &
python run_sse.py notion_mcp     9010 &

# Wait for mock servers to be ready
echo "Waiting for mock servers to start..."
sleep 3

echo "Starting MCPForge proxy..."
exec mcpforge start --config mcpforge.yaml
