"""Evidence-grounded LLM enrichment with explicit failure states."""

import json
import os
import re

import httpx
from pydantic import ValidationError

from app.models.incident import IncidentAnalysis
from app.models.intelligence import EnrichmentClaim, LLMEnrichment

SYSTEM_PROMPT = """You are an evidence-constrained incident intelligence analyst.
Evidence supplied by ChroniX is authoritative. Return valid JSON only.
Do not invent events, timestamps, sources, evidence IDs, or causal certainty.
Use only evidence IDs present in the supplied context. Distinguish observations
from interpretations, preserve uncertainty, identify conflicts and missing
evidence, and never force a root cause. The deterministic root-cause status and
FACT classifications are authoritative and must not be rewritten.

Return an object with exactly these logical fields:
incident_summary, probable_causes, contributing_factors, causal_relationships,
evidence_interpretations, uncertainty, missing_evidence,
investigation_recommendations.
Each claim is an object with description, evidence_ids, and optional confidence
between 0 and 1. Return structured JSON, not markdown."""


def _json_content(content: str) -> dict:
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(content)


def _status(analysis: IncidentAnalysis, status: str, enrichment: LLMEnrichment | None = None) -> IncidentAnalysis:
    return analysis.model_copy(update={"llm_status": status, "llm_enrichment": enrichment})


def _context(analysis: IncidentAnalysis) -> dict:
    return {
        "incident_title": analysis.incident_title,
        "deterministic_root_cause_status": analysis.root_cause_status,
        "timeline": [
            {
                "evidence_id": event.source_id,
                "source_id": event.source_id,
                "source": event.source,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "event": event.event,
                "classification": event.classification,
                "raw_evidence": event.raw_evidence,
            }
            for event in analysis.timeline
        ],
        "deterministic_facts": analysis.facts,
        "deterministic_inferences": analysis.inferences,
        "deterministic_conflicts": analysis.conflicts,
        "deterministic_unknowns": analysis.unknowns,
        "deterministic_missing_evidence": analysis.missing_evidence,
    }


def _claim_references(enrichment: LLMEnrichment) -> list[EnrichmentClaim]:
    return [
        *enrichment.probable_causes,
        *enrichment.contributing_factors,
        *enrichment.causal_relationships,
        *enrichment.evidence_interpretations,
        *enrichment.uncertainty,
        *enrichment.missing_evidence,
    ]


def _references_are_valid(enrichment: LLMEnrichment, evidence_ids: set[str]) -> bool:
    return all(reference in evidence_ids for claim in _claim_references(enrichment) for reference in claim.evidence_ids)


def _accept_response(analysis: IncidentAnalysis, response: httpx.Response, status: str) -> IncidentAnalysis:
    try:
        generated = _json_content(response.json()["choices"][0]["message"]["content"])
        enrichment = LLMEnrichment.model_validate(generated)
        evidence_ids = {event.source_id for event in analysis.timeline}
        if not _references_are_valid(enrichment, evidence_ids):
            return _status(analysis, "invalid_response")
        return _status(analysis, status, enrichment)
    except (json.JSONDecodeError, KeyError, TypeError, ValidationError, ValueError, IndexError):
        return _status(analysis, "invalid_response")


def _ollama_response_content(response: httpx.Response) -> str:
    return response.json()["message"]["content"]


def enrich_with_llm(analysis: IncidentAnalysis) -> IncidentAnalysis:
    provider = os.getenv("CHRONIX_LLM_PROVIDER", "ollama").lower()
    if provider in {"", "disabled", "none"}:
        return _status(analysis, "unavailable")

    context = _context(analysis)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"incident_context": context})},
    ]

    if provider == "ollama":
        try:
            response = httpx.post(
                os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/chat",
                json={"model": os.getenv("OLLAMA_MODEL", "qwen3:4b"), "stream": False, "format": "json", "messages": messages},
                timeout=60,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return _status(analysis, "failed")
        try:
            generated = _json_content(_ollama_response_content(response))
            enrichment = LLMEnrichment.model_validate(generated)
            evidence_ids = {event.source_id for event in analysis.timeline}
            if not _references_are_valid(enrichment, evidence_ids):
                return _status(analysis, "invalid_response")
            return _status(analysis, "local", enrichment)
        except (json.JSONDecodeError, KeyError, TypeError, ValidationError, ValueError, IndexError):
            return _status(analysis, "invalid_response")

    if provider != "openai":
        return _status(analysis, "unavailable")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _status(analysis, "unavailable")

    try:
        response = httpx.post(
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": messages,
            },
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return _status(analysis, "failed")

    return _accept_response(analysis, response, "used")
