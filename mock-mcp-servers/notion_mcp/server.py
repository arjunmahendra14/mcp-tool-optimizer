from fastmcp import FastMCP
import random
from datetime import datetime

mcp = FastMCP("notion")


@mcp.tool()
def search_pages(query: str) -> list:  # COLD
    """Search Notion pages by query string. Returns page id, title, and URL."""
    titles = [
        "Engineering Wiki Home",
        "Incident Post-Mortem Log",
        "Team OKRs Q2 2026",
        "Architecture Decision Records",
        "Runbook Index",
    ]
    return [
        {
            "id": "".join(random.choices("0123456789abcdef", k=32)),
            "title": t,
            "url": f"https://notion.so/{t.lower().replace(' ', '-')}-{''.join(random.choices('0123456789abcdef', k=8))}",
        }
        for t in random.sample(titles, k=3)
    ]


@mcp.tool()
def create_page(parent_id: str, title: str, content: str) -> dict:  # COLD
    """Create a new Notion page under a parent. Returns the new page ID and URL."""
    page_id = "".join(random.choices("0123456789abcdef", k=32))
    return {
        "page_id": page_id,
        "parent_id": parent_id,
        "title": title,
        "url": f"https://notion.so/{title.lower().replace(' ', '-')}-{page_id[:8]}",
    }


@mcp.tool()
def update_page(page_id: str, content: str) -> dict:  # COLD
    """Update the content of an existing Notion page. Returns update status."""
    return {"page_id": page_id, "status": "updated", "updated_at": datetime.utcnow().isoformat()}


@mcp.tool()
def list_databases(parent_id: str) -> list:  # COLD
    """List Notion databases under a parent page. Returns database id and name."""
    dbs = ["Incident Tracker", "Runbook Registry", "Team Directory", "Project Board"]
    return [
        {"id": "".join(random.choices("0123456789abcdef", k=32)), "name": db}
        for db in dbs
    ]


@mcp.tool()
def query_database(database_id: str, filter: dict) -> list:  # COLD
    """Query a Notion database with a filter. Returns matching page entries with id and properties."""
    return [
        {
            "id": "".join(random.choices("0123456789abcdef", k=32)),
            "properties": {
                "Name": f"Entry {i}",
                "Status": random.choice(["Open", "Closed", "In Review"]),
                "Priority": random.choice(["P0", "P1", "P2"]),
            },
        }
        for i in range(1, 6)
    ]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
