from fastmcp import FastMCP
import random
import time

mcp = FastMCP("slack")


@mcp.tool()
def send_message(channel: str, text: str) -> dict:  # HOT
    """Send a plain-text message to a Slack channel. Returns the message timestamp and channel name."""
    return {"ts": str(time.time()), "channel": channel, "ok": True}


@mcp.tool()
def post_to_channel(channel: str, blocks: list) -> dict:  # HOT
    """Post a rich Block Kit message to a Slack channel. Returns the message timestamp and ok status."""
    return {"ts": str(time.time()), "channel": channel, "ok": True}


@mcp.tool()
def create_thread(channel: str, text: str) -> dict:  # HOT
    """Start a new thread in a Slack channel with an initial message. Returns the thread timestamp."""
    ts = str(time.time())
    return {"thread_ts": ts, "channel": channel, "ok": True}


@mcp.tool()
def list_channels(limit: int = 20) -> list:  # COLD
    """List public Slack channels up to the given limit. Returns channel id, name, and member count."""
    return [
        {"id": f"C{random.randint(10000000, 99999999)}", "name": f"channel-{i}", "members": random.randint(2, 200)}
        for i in range(1, min(limit, 20) + 1)
    ]


@mcp.tool()
def invite_user(channel: str, user_id: str) -> dict:  # COLD
    """Invite a user to a Slack channel by user ID. Returns ok status."""
    return {"channel": channel, "user_id": user_id, "ok": True}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
