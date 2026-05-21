from fastmcp import FastMCP
import random
from datetime import datetime, timedelta

mcp = FastMCP("sentry")


@mcp.tool()
def list_issues(project: str, status: str = "unresolved") -> list:  # COLD
    """List Sentry issues for a project filtered by status. Returns issue id, title, occurrence count, and last seen time."""
    titles = [
        "ValueError: NoneType object is not subscriptable",
        "ConnectionError: Failed to connect to database",
        "TimeoutError: Request exceeded 30s limit",
        "KeyError: 'user_id' missing from session",
        "AssertionError in payment gateway callback",
    ]
    return [
        {
            "id": f"PROJ-{random.randint(1000, 9999)}",
            "title": random.choice(titles),
            "occurrences": random.randint(1, 5000),
            "last_seen": (datetime.utcnow() - timedelta(minutes=random.randint(1, 1440))).isoformat(),
            "status": status,
        }
        for _ in range(5)
    ]


@mcp.tool()
def get_issue_detail(issue_id: str) -> dict:  # COLD
    """Get full details for a Sentry issue including stacktrace, tags, and occurrence count."""
    return {
        "id": issue_id,
        "title": "ConnectionError: Failed to connect to database",
        "count": random.randint(50, 10000),
        "stacktrace": [
            "File 'app/db.py', line 42, in connect\n    conn = pool.get_connection()",
            "File 'app/services/auth.py', line 88, in verify_user\n    db.query(user_id)",
        ],
        "tags": {"environment": "production", "release": "v2.4.1", "server": "web-01"},
    }


@mcp.tool()
def resolve_issue(issue_id: str) -> dict:  # COLD
    """Mark a Sentry issue as resolved. Returns updated status."""
    return {"issue_id": issue_id, "status": "resolved", "resolved_at": datetime.utcnow().isoformat()}


@mcp.tool()
def assign_issue(issue_id: str, user: str) -> dict:  # COLD
    """Assign a Sentry issue to a team member. Returns the assignee."""
    return {"issue_id": issue_id, "assignee": user, "assigned_at": datetime.utcnow().isoformat()}


@mcp.tool()
def search_events(query: str, project: str) -> list:  # COLD
    """Search Sentry events by query string within a project. Returns event id, timestamp, and level."""
    levels = ["error", "warning", "info", "fatal"]
    return [
        {
            "event_id": "".join(random.choices("0123456789abcdef", k=32)),
            "timestamp": (datetime.utcnow() - timedelta(seconds=random.randint(0, 86400))).isoformat(),
            "level": random.choice(levels),
            "project": project,
        }
        for _ in range(5)
    ]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
