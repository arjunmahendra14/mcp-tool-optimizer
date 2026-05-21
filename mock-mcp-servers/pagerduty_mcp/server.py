from fastmcp import FastMCP
import random
from datetime import datetime

mcp = FastMCP("pagerduty")


@mcp.tool()
def escalate_incident(incident_id: str, escalation_policy_id: str) -> dict:  # HOT
    """Escalate a PagerDuty incident to the next level using an escalation policy. Returns escalation status and notified users."""
    users = ["alice@company.com", "bob@company.com", "oncall-lead@company.com"]
    return {
        "incident_id": incident_id,
        "escalated": True,
        "policy": escalation_policy_id,
        "notified": random.sample(users, k=2),
        "escalated_at": datetime.utcnow().isoformat(),
    }


@mcp.tool()
def acknowledge_alert(alert_id: str) -> dict:  # HOT
    """Acknowledge a PagerDuty alert to stop further notifications. Returns updated status and acknowledger."""
    return {
        "alert_id": alert_id,
        "status": "acknowledged",
        "acknowledged_by": "oncall-bot",
        "acknowledged_at": datetime.utcnow().isoformat(),
    }


@mcp.tool()
def resolve_incident(incident_id: str) -> dict:  # COLD
    """Resolve a PagerDuty incident. Returns updated status."""
    return {"incident_id": incident_id, "status": "resolved", "resolved_at": datetime.utcnow().isoformat()}


@mcp.tool()
def get_oncall_schedule(schedule_id: str) -> dict:  # COLD
    """Retrieve the current on-call schedule for a given schedule ID. Returns the list of on-call users with start/end times."""
    return {
        "schedule_id": schedule_id,
        "oncall": [
            {"user": "alice@company.com", "start": "2026-05-20T00:00:00Z", "end": "2026-05-21T00:00:00Z"},
            {"user": "bob@company.com", "start": "2026-05-21T00:00:00Z", "end": "2026-05-22T00:00:00Z"},
        ],
    }


@mcp.tool()
def create_incident(title: str, service_id: str, urgency: str = "high") -> dict:  # COLD
    """Create a new PagerDuty incident for a service. Returns the incident ID and URL."""
    incident_id = f"P{random.randint(100000, 999999)}"
    return {
        "incident_id": incident_id,
        "title": title,
        "service_id": service_id,
        "urgency": urgency,
        "url": f"https://company.pagerduty.com/incidents/{incident_id}",
    }


@mcp.tool()
def list_services() -> list:  # COLD
    """List all PagerDuty services. Returns service id, name, and current status."""
    services = ["api-gateway", "auth-service", "payment-service", "data-pipeline", "notification-service"]
    return [
        {"id": f"SVC{i:03d}", "name": svc, "status": random.choice(["active", "warning", "critical"])}
        for i, svc in enumerate(services, 1)
    ]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
