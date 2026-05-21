from fastmcp import FastMCP
import random
from datetime import datetime, timedelta

mcp = FastMCP("confluence")


@mcp.tool()
def search_pages(query: str, space: str) -> list:  # COLD
    """Search Confluence pages by query string within a space. Returns page id, title, and URL."""
    titles = [
        "Incident Response Runbook",
        "On-Call Escalation Policy",
        "Database Failover Procedure",
        "Service Dependency Map",
        "Post-Mortem Template",
    ]
    return [
        {
            "id": f"PAGE-{random.randint(10000, 99999)}",
            "title": t,
            "space": space,
            "url": f"https://company.atlassian.net/wiki/spaces/{space}/pages/{random.randint(10000, 99999)}",
        }
        for t in random.sample(titles, k=3)
        if query.lower() in t.lower() or True
    ]


@mcp.tool()
def get_page(page_id: str) -> dict:  # COLD
    """Retrieve a Confluence page by ID. Returns title, body content, and last modified time."""
    return {
        "id": page_id,
        "title": "Incident Response Runbook",
        "body": "## Steps\n1. Acknowledge the alert\n2. Join the incident Slack channel\n3. Assess impact\n4. Escalate if P1",
        "last_modified": (datetime.utcnow() - timedelta(days=random.randint(1, 30))).isoformat(),
    }


@mcp.tool()
def create_page(space: str, title: str, body: str) -> dict:  # COLD
    """Create a new Confluence page in a space. Returns the new page ID and URL."""
    page_id = str(random.randint(100000, 999999))
    return {
        "page_id": page_id,
        "space": space,
        "title": title,
        "url": f"https://company.atlassian.net/wiki/spaces/{space}/pages/{page_id}",
    }


@mcp.tool()
def update_page(page_id: str, body: str) -> dict:  # COLD
    """Update the body content of an existing Confluence page. Returns update status."""
    return {"page_id": page_id, "status": "updated", "updated_at": datetime.utcnow().isoformat()}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
