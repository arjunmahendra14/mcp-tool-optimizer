from fastmcp import FastMCP
import random
from datetime import datetime

mcp = FastMCP("linear")


@mcp.tool()
def create_issue(team: str, title: str, priority: str = "medium") -> dict:  # COLD
    """Create a new Linear issue for a team. Returns the issue ID and URL."""
    issue_id = f"LIN-{random.randint(100, 9999)}"
    return {
        "issue_id": issue_id,
        "team": team,
        "title": title,
        "priority": priority,
        "url": f"https://linear.app/company/issue/{issue_id}",
    }


@mcp.tool()
def update_issue(issue_id: str, fields: dict) -> dict:  # COLD
    """Update an existing Linear issue with new field values. Returns updated status."""
    return {"issue_id": issue_id, "updated_fields": list(fields.keys()), "status": "updated"}


@mcp.tool()
def list_projects(team: str) -> list:  # COLD
    """List all Linear projects for a team. Returns project id, name, and state."""
    projects = ["Platform Reliability", "Growth", "Data Infrastructure", "Auth & Security", "Developer Experience"]
    return [
        {"id": f"PROJ-{i}", "name": p, "state": random.choice(["started", "planned", "completed", "paused"])}
        for i, p in enumerate(projects, 1)
    ]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
