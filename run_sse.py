"""Launch a mock MCP server in SSE mode on a given port.

Usage: python run_sse.py <server_dir> <port>
Example: python run_sse.py datadog_mcp 9001
"""
import importlib.util
import sys

if len(sys.argv) != 3:
    print("Usage: run_sse.py <server_dir> <port>", file=sys.stderr)
    sys.exit(1)

server_dir = sys.argv[1]
port = int(sys.argv[2])

spec = importlib.util.spec_from_file_location(
    "server", f"mock-mcp-servers/{server_dir}/server.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.mcp.run(transport="sse", host="0.0.0.0", port=port)
