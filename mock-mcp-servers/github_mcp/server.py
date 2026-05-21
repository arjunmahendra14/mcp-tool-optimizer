from fastmcp import FastMCP
import random
from datetime import datetime, timedelta

mcp = FastMCP("github")


@mcp.tool()
def list_repos(org: str) -> list:  # COLD
    """List repositories for a GitHub organization. Returns name, star count, and last updated time."""
    repos = ["api-service", "frontend", "data-pipeline", "infra-terraform", "ml-models"]
    return [
        {
            "name": f"{org}/{r}",
            "stars": random.randint(0, 5000),
            "updated_at": (datetime.utcnow() - timedelta(days=random.randint(0, 90))).isoformat(),
        }
        for r in repos
    ]


@mcp.tool()
def create_pr(repo: str, title: str, head: str, base: str = "main") -> dict:  # COLD
    """Create a pull request in a GitHub repository. Returns the PR number and URL."""
    pr_id = random.randint(100, 9999)
    return {"pr_id": pr_id, "repo": repo, "title": title, "url": f"https://github.com/{repo}/pull/{pr_id}"}


@mcp.tool()
def review_pr(pr_id: int, event: str, body: str) -> dict:  # COLD
    """Submit a review on a GitHub pull request. Event is APPROVE, REQUEST_CHANGES, or COMMENT."""
    return {"pr_id": pr_id, "event": event, "status": "submitted"}


@mcp.tool()
def merge_pr(pr_id: int, merge_method: str = "squash") -> dict:  # COLD
    """Merge a GitHub pull request using the specified merge method (merge, squash, rebase)."""
    sha = "".join(random.choices("0123456789abcdef", k=40))
    return {"pr_id": pr_id, "merged": True, "sha": sha, "merge_method": merge_method}


@mcp.tool()
def create_issue(repo: str, title: str, body: str) -> dict:  # COLD
    """Create a new issue in a GitHub repository. Returns the issue number and URL."""
    issue_id = random.randint(100, 9999)
    return {"issue_id": issue_id, "repo": repo, "title": title, "url": f"https://github.com/{repo}/issues/{issue_id}"}


@mcp.tool()
def close_issue(repo: str, issue_id: int) -> dict:  # COLD
    """Close an existing GitHub issue. Returns the updated status."""
    return {"repo": repo, "issue_id": issue_id, "status": "closed"}


@mcp.tool()
def list_commits(repo: str, branch: str = "main", limit: int = 10) -> list:  # COLD
    """List recent commits on a GitHub branch. Returns SHA, message, and author for each commit."""
    messages = [
        "fix: resolve race condition in auth middleware",
        "feat: add retry logic to payment client",
        "chore: bump dependency versions",
        "fix: correct off-by-one in pagination",
        "refactor: extract DB connection pool config",
    ]
    return [
        {
            "sha": "".join(random.choices("0123456789abcdef", k=7)),
            "message": random.choice(messages),
            "author": random.choice(["alice", "bob", "carol"]),
        }
        for _ in range(min(limit, 20))
    ]


@mcp.tool()
def search_code(query: str, repo: str) -> list:  # COLD
    """Search code in a GitHub repository by query string. Returns matching file paths, URLs, and snippets."""
    return [
        {
            "path": f"src/services/{random.choice(['auth', 'payment', 'api'])}.py",
            "url": f"https://github.com/{repo}/blob/main/src/services/auth.py#L{random.randint(1, 200)}",
            "snippet": f"# match for {query!r}\ndef handle_request(): ...",
        }
        for _ in range(3)
    ]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
