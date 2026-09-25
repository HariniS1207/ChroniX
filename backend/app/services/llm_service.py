"""Optional structured narrative adapter with a deterministic fallback."""

import json
import os

import httpx

from app.models.incident import IncidentAnalysis


def _json_content(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(content)


def enrich_with_llm(analysis: IncidentAnalysis) -> IncidentAnalysis:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return analysis

    payload = {
        "incident_title": analysis.incident_title,
        "timeline": [event.model_dump(mode="json") for event in analysis.timeline],
        "instruction": "Return JSON with incident_title, summary, root_cause_status, facts, inferences, conflicts, unknowns, and missing_evidence. Do not add claims or events absent from the supplied timeline.",
    }
    try:
        response = httpx.post(
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You are an evidence-constrained incident analyst."},
                    {"role": "user", "content": json.dumps(payload)},
                ],
            },
            timeout=20,
        )
        response.raise_for_status()
        generated = _json_content(response.json()["choices"][0]["message"]["content"])
        allowed = {"incident_title", "summary", "root_cause_status", "facts", "inferences", "conflicts", "unknowns", "missing_evidence"}
        updates = {key: generated[key] for key in allowed if key in generated}
        return analysis.model_copy(update=updates)
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return analysis
