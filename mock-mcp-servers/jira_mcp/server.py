from fastmcp import FastMCP
import random
from datetime import datetime

mcp = FastMCP("jira")


@mcp.tool()
def create_ticket(project: str, summary: str, type: str = "Bug", priority: str = "High") -> dict:  # COLD
    """Create a new Jira ticket in a project. Returns the ticket ID and URL."""
    ticket_id = f"{project}-{random.randint(1000, 9999)}"
    return {
        "ticket_id": ticket_id,
        "project": project,
        "summary": summary,
        "type": type,
        "priority": priority,
        "url": f"https://company.atlassian.net/browse/{ticket_id}",
    }


@mcp.tool()
def update_ticket(ticket_id: str, fields: dict) -> dict:  # COLD
    """Update fields on an existing Jira ticket (e.g. status, assignee, priority). Returns update status."""
    return {"ticket_id": ticket_id, "updated_fields": list(fields.keys()), "status": "updated"}


@mcp.tool()
def search_tickets(jql: str) -> list:  # COLD
    """Search Jira tickets using JQL (Jira Query Language). Returns id, summary, status, and assignee."""
    statuses = ["Open", "In Progress", "Done", "Blocked"]
    users = ["alice", "bob", "carol", None]
    return [
        {
            "id": f"PROJ-{random.randint(1000, 9999)}",
            "summary": f"Ticket matching: {jql[:40]}",
            "status": random.choice(statuses),
            "assignee": random.choice(users),
        }
        for _ in range(5)
    ]


@mcp.tool()
def assign_ticket(ticket_id: str, user: str) -> dict:  # COLD
    """Assign a Jira ticket to a user. Returns the new assignee."""
    return {"ticket_id": ticket_id, "assignee": user, "assigned_at": datetime.utcnow().isoformat()}


@mcp.tool()
def close_ticket(ticket_id: str, resolution: str = "Done") -> dict:  # COLD
    """Close a Jira ticket with a given resolution. Returns updated status."""
    return {"ticket_id": ticket_id, "status": "closed", "resolution": resolution, "closed_at": datetime.utcnow().isoformat()}


@mcp.tool()
def get_sprint(board_id: str) -> dict:  # COLD
    """Get the current active sprint for a Jira board. Returns sprint ID, name, and list of issue IDs."""
    sprint_id = random.randint(100, 999)
    return {
        "board_id": board_id,
        "sprint_id": sprint_id,
        "name": f"Sprint {sprint_id}",
        "issues": [f"PROJ-{random.randint(1000, 9999)}" for _ in range(random.randint(5, 20))],
    }


def main():
    mcp.run()


if __name__ == "__main__":
    main()
