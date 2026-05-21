from fastmcp import FastMCP
import random
from datetime import datetime, timedelta

mcp = FastMCP("kubernetes")


@mcp.tool()
def restart_pod(namespace: str, pod_name: str) -> dict:  # HOT
    """Restart a Kubernetes pod in the given namespace. Returns new status and restart timestamp."""
    return {
        "namespace": namespace,
        "pod_name": pod_name,
        "status": "Running",
        "restarted_at": datetime.utcnow().isoformat(),
    }


@mcp.tool()
def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 100) -> dict:  # HOT
    """Fetch tail logs from a Kubernetes pod. Returns a list of recent log lines."""
    sample_lines = [
        "INFO  Starting HTTP server on :8080",
        "WARN  Upstream connection pool at 90% capacity",
        "ERROR Timeout after 30s waiting for dependency",
        "INFO  Retry attempt 3 of 5",
        "ERROR OOMKill signal received",
        "WARN  GC pause >200ms detected",
        "INFO  Pod ready check passed",
    ]
    logs = [f"{datetime.utcnow().isoformat()} {random.choice(sample_lines)}" for _ in range(min(tail_lines, 50))]
    return {"namespace": namespace, "pod": pod_name, "logs": logs}


@mcp.tool()
def scale_deployment(namespace: str, deployment: str, replicas: int) -> dict:  # HOT
    """Scale a Kubernetes deployment to the specified number of replicas. Returns current and desired replica counts."""
    current = random.randint(1, replicas + 2)
    return {"namespace": namespace, "deployment": deployment, "current": current, "desired": replicas}


@mcp.tool()
def list_namespaces() -> list:  # COLD
    """List all Kubernetes namespaces. Returns name, status, and age in days."""
    namespaces = ["default", "production", "staging", "monitoring", "kube-system"]
    return [
        {"name": ns, "status": "Active", "age_days": random.randint(1, 365)}
        for ns in namespaces
    ]


@mcp.tool()
def describe_node(node_name: str) -> dict:  # COLD
    """Describe a Kubernetes node including CPU, memory, and conditions."""
    return {
        "node": node_name,
        "cpu": f"{random.randint(20, 95)}%",
        "memory": f"{random.randint(30, 90)}%",
        "conditions": [
            {"type": "Ready", "status": "True"},
            {"type": "MemoryPressure", "status": "False"},
            {"type": "DiskPressure", "status": "False"},
        ],
    }


def main():
    mcp.run()


if __name__ == "__main__":
    main()
