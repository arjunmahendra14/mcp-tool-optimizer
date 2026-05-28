"""Session-type classifier using Claude Haiku — never raises, always returns a valid type."""

import logging

import anthropic

logger = logging.getLogger(__name__)

VALID_TYPES = frozenset({"incident", "planning", "code", "general"})

_SYSTEM_PROMPT = """\
Classify the AI agent session below into exactly one category. Reply with only the lowercase word.

Categories:
- incident: urgent operational issues, outages, alerts, pod restarts, latency spikes, on-call response, PagerDuty, monitors
- planning: roadmap, sprint planning, architecture decisions, design discussions, backlog grooming
- code: writing, reviewing, debugging, or refactoring source code
- general: anything else

Reply with the single category name only."""

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


async def classify_session(context: str) -> str:
    """Classify a session context string into: incident, planning, code, or general.

    Always returns a valid type string. Falls back to 'general' on any error.
    """
    try:
        client = _get_client()
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context[:500]}],
        )
        raw = response.content[0].text.strip().lower()
        result = raw if raw in VALID_TYPES else "general"
        logger.debug(f"Classified as '{result}': {context[:80]}")
        return result
    except Exception as exc:
        logger.warning(f"Classification failed, defaulting to 'general': {exc}")
        return "general"
