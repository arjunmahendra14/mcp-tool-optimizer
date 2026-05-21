from fastmcp import FastMCP
import random
import time
from datetime import datetime, timedelta

mcp = FastMCP("datadog")


@mcp.tool()
def query_metrics(service: str, metric: str, window_minutes: int) -> dict:  # HOT
    """Query Datadog metrics for a service over a time window. Returns raw values, timestamps, avg, and p99."""
    now = time.time()
    values = [round(random.uniform(10, 500), 2) for _ in range(window_minutes)]
    timestamps = [now - (window_minutes - i) * 60 for i in range(window_minutes)]
    sorted_values = sorted(values)
    p99_idx = int(len(sorted_values) * 0.99)
    return {
        "service": service,
        "metric": metric,
        "values": values,
        "timestamps": timestamps,
        "avg": round(sum(values) / len(values), 2),
        "p99": sorted_values[p99_idx],
    }


@mcp.tool()
def list_monitors(status_filter: str) -> list:  # HOT
    """List Datadog monitors filtered by status (e.g. 'Alert', 'Warn', 'OK'). Returns monitor id, name, status, and trigger time."""
    statuses = ["Alert", "Warn", "OK", "No Data"]
    monitors = []
    for i in range(1, 6):
        status = status_filter if status_filter in statuses else random.choice(statuses)
        monitors.append({
            "id": f"mon_{1000 + i}",
            "name": f"[{status}] Service latency p99 check #{i}",
            "status": status,
            "triggered_at": (datetime.utcnow() - timedelta(minutes=random.randint(1, 120))).isoformat(),
        })
    return monitors


@mcp.tool()
def get_dashboard(dashboard_id: str) -> dict:  # HOT
    """Retrieve a Datadog dashboard by ID. Returns widget list and shareable URL."""
    return {
        "id": dashboard_id,
        "title": f"Service Health Overview ({dashboard_id})",
        "widgets": [
            {"type": "timeseries", "title": "Request Rate"},
            {"type": "heatmap", "title": "Latency Distribution"},
            {"type": "toplist", "title": "Error Rate by Service"},
        ],
        "url": f"https://app.datadoghq.com/dashboard/{dashboard_id}",
    }


@mcp.tool()
def search_logs(query: str, service: str, limit: int) -> list:  # HOT
    """Search Datadog logs by query string and service name. Returns timestamped log entries with level and message."""
    levels = ["ERROR", "WARN", "INFO", "DEBUG"]
    messages = [
        "Connection pool exhausted",
        "Timeout waiting for upstream",
        "Retrying request after 500ms",
        "Circuit breaker opened",
        "Health check failed",
        "Pod OOMKilled",
        "Database query exceeded SLA",
    ]
    return [
        {
            "timestamp": (datetime.utcnow() - timedelta(seconds=random.randint(0, 3600))).isoformat(),
            "level": random.choice(levels),
            "message": f"[{service}] {random.choice(messages)} — query={query!r}",
        }
        for _ in range(min(limit, 50))
    ]


@mcp.tool()
def silence_monitor(monitor_id: str, duration_minutes: int) -> dict:  # HOT
    """Silence a Datadog monitor for a given number of minutes. Returns confirmation and silence-until timestamp."""
    until = (datetime.utcnow() + timedelta(minutes=duration_minutes)).isoformat()
    return {"monitor_id": monitor_id, "silenced": True, "until": until}


@mcp.tool()
def export_dashboard_pdf(dashboard_id: str) -> dict:  # COLD
    """Export a Datadog dashboard as a PDF. Returns a temporary download URL."""
    return {"dashboard_id": dashboard_id, "url": f"https://app.datadoghq.com/pdf/{dashboard_id}.pdf"}


@mcp.tool()
def create_slo(name: str, target: float, metric: str) -> dict:  # COLD
    """Create a new Datadog SLO with a name, target percentage, and backing metric."""
    return {"slo_id": f"slo_{random.randint(10000, 99999)}", "name": name, "target": target, "status": "created"}


@mcp.tool()
def list_hosts(env: str) -> list:  # COLD
    """List all hosts in a Datadog environment. Returns hostname, status, and associated tags."""
    hostnames = [f"host-{env}-{i:03d}" for i in range(1, 6)]
    return [
        {"hostname": h, "status": random.choice(["UP", "DOWN"]), "tags": [f"env:{env}", "role:worker"]}
        for h in hostnames
    ]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
