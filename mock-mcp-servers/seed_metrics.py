"""
Fire 80 realistic incident-response prompts at the oncall-tools-bloated Virtual MCP agent
to seed tool-call metrics on Truefoundry. HOT tools should dominate; COLD tools stay silent.

Usage:
    TF_CONTROL_PLANE_URL=https://... TF_API_KEY=... python seed_metrics.py
"""

import os
import time
import anthropic

TF_CONTROL_PLANE_URL = os.environ["TF_CONTROL_PLANE_URL"].rstrip("/")
TF_API_KEY = os.environ["TF_API_KEY"]
VIRTUAL_MCP_NAME = "oncall-tools-bloated"
AGENT_ENDPOINT = f"{TF_CONTROL_PLANE_URL}/api/svc/v1/agent/completions"

INCIDENT_PROMPTS = [
    # Datadog — query_metrics
    "Our payment service p99 latency spiked in the last 15 minutes. Pull the latency metrics for payment-service.",
    "Check request rate metrics for the auth-service over the last 30 minutes.",
    "Query error rate metrics for data-pipeline over the last 10 minutes.",
    "Get CPU utilisation metrics for the api-gateway service for the last 20 minutes.",
    "Pull memory usage metrics for notification-service over the last 5 minutes.",
    "What does the request throughput look like for auth-service in the last 60 minutes?",
    "Query metrics for payment-service: check the connection pool saturation for the last 15 minutes.",
    "Grab latency p99 for ml-models service over the last 45 minutes.",
    # Datadog — list_monitors
    "List all monitors currently in Alert status.",
    "Show me monitors in Warn state right now.",
    "What monitors are currently alerting for the production environment?",
    "List triggered monitors so I can triage what's firing.",
    "Show all monitors that are not OK — I need to see what's broken.",
    # Datadog — get_dashboard
    "Pull up the service health dashboard for the main production view.",
    "Get dashboard dash-prod-001 so I can see the current widget state.",
    "Open the engineering dashboard for the API layer.",
    # Datadog — search_logs
    "Search logs for 'ConnectionError' in the payment-service for the last hour.",
    "Find ERROR logs for auth-service from the past 30 minutes.",
    "Search for 'OOMKill' in Kubernetes pod logs for data-pipeline.",
    "Look up 'timeout' log entries for api-gateway in the last 20 minutes.",
    "Search for 'circuit breaker' errors in notification-service logs.",
    "Find 'retry' log messages in payment-service in the last 15 minutes.",
    # Datadog — silence_monitor
    "Silence monitor mon_1001 for 30 minutes while we investigate.",
    "Mute the high-latency alert for auth-service for 60 minutes.",
    "Silence the memory pressure monitor for 45 minutes — we're doing a rolling restart.",
    # Slack — send_message
    "Post to #incidents: 'P1 incident declared — payment service latency degraded. Bridge open.'",
    "Send a message to #oncall-alerts that we are investigating a latency spike.",
    "Notify #engineering that payment-service is experiencing elevated error rates.",
    "Message #incidents: 'All hands — data-pipeline is processing 3x slower than baseline.'",
    "Send to #oncall: 'Auth service pod restarted. Monitoring for recovery.'",
    "Notify #incidents that the issue has been identified and a fix is being deployed.",
    "Post to #incidents: 'Incident resolved. RCA to follow in 24h.'",
    # Slack — post_to_channel
    "Post a rich incident card to #incidents with the current status and impacted services.",
    "Post an update block to #oncall-alerts with the latest metrics.",
    "Send a formatted incident summary block to #engineering.",
    # Slack — create_thread
    "Start an incident thread in #incidents for the current payment-service outage.",
    "Open a new thread in #oncall for the Kubernetes pod crash investigation.",
    "Create a thread in #incidents to coordinate the auth-service response.",
    # Kubernetes — restart_pod
    "Restart the payment-processor pod in the production namespace.",
    "The auth-worker pod is hanging — restart it in the production namespace.",
    "Restart data-pipeline-worker-0 in the production namespace.",
    "The api-gateway pod is stuck — restart it now.",
    "Restart ml-inference-server-0 in the production namespace.",
    # Kubernetes — get_pod_logs
    "Get the last 200 lines of logs from payment-processor in production.",
    "Fetch logs from auth-worker pod in production — tail 100 lines.",
    "Pull the last 50 log lines from data-pipeline-worker in production.",
    "Get logs from api-gateway pod in production namespace.",
    "Fetch the last 150 lines from notification-worker pod in production.",
    # Kubernetes — scale_deployment
    "Scale payment-service deployment to 8 replicas in production.",
    "We need to scale up auth-service to 6 replicas to handle the load.",
    "Scale api-gateway to 10 replicas in production immediately.",
    "Increase data-pipeline deployment to 4 replicas in production.",
    # PagerDuty — escalate_incident
    "Escalate incident INC-4521 to the platform engineering escalation policy.",
    "This is a P0 — escalate incident INC-7890 to senior on-call immediately.",
    "Escalate the current payment-service incident to the database team escalation policy.",
    # PagerDuty — acknowledge_alert
    "Acknowledge PagerDuty alert ALT-001 — I'm taking this.",
    "Ack alert ALT-334 so notifications stop while I investigate.",
    "Acknowledge the high-latency alert in PagerDuty.",
    # Combined workflows
    "The payment service is down. Check latency metrics, look at triggered monitors, and search for ERROR logs.",
    "Auth service is alerting. Get pod logs, check metrics for the last 10 minutes, and notify #incidents.",
    "We have a P1. Acknowledge the PagerDuty alert, post to #incidents, and restart the failing pod.",
    "Latency spike detected. Query metrics for auth-service, search logs for timeout errors, silence the monitor.",
    "Pod crash loop in production. Get the pod logs, scale the deployment up, post update to #incidents.",
    "Database connection errors spiking. Search logs for ConnectionError, check monitors in Alert, notify #oncall.",
    "P0 incident: restart the crashing pod, escalate in PagerDuty, and send incident bridge message to Slack.",
    "Memory pressure on api-gateway. Check pod logs, query memory metrics, scale the deployment.",
    "Error rate jumped 10x. Pull Datadog metrics, list alerting monitors, search for ERROR logs.",
    "Investigate: search logs for 'timeout', query p99 latency metrics, and get the health dashboard.",
    "On-call handoff: list currently alerting monitors and send a summary to #oncall.",
    "Restart the stuck worker pod, then notify Slack that we are investigating.",
    "Query metrics for every service over last 15 minutes and summarize what is anomalous.",
    "Scale up the affected deployment and confirm the replica count is correct.",
    "Post a status update to #incidents and create a Slack thread for coordination.",
]

assert len(INCIDENT_PROMPTS) == 80, f"Expected 80 prompts, got {len(INCIDENT_PROMPTS)}"


def main():
    client = anthropic.Anthropic(api_key=TF_API_KEY, base_url=TF_CONTROL_PLANE_URL)

    print(f"Seeding {len(INCIDENT_PROMPTS)} incident prompts → {VIRTUAL_MCP_NAME}")
    print(f"Endpoint: {AGENT_ENDPOINT}\n")

    for i, prompt in enumerate(INCIDENT_PROMPTS, 1):
        print(f"[{i:02d}/{len(INCIDENT_PROMPTS)}] {prompt[:80]}...")
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
                # The Virtual MCP tools are injected server-side by Truefoundry
            )
            print(f"         → stop_reason={response.stop_reason}\n")
        except Exception as exc:
            print(f"         ERROR: {exc}\n")

        if i < len(INCIDENT_PROMPTS):
            time.sleep(1)

    print("Done. Check Truefoundry analytics for tool-call distribution.")


if __name__ == "__main__":
    main()
