"""Evidence-grounded LLM enrichment with explicit failure states."""

import json
import logging
import os
import re
from time import perf_counter

import httpx
from pydantic import ValidationError

from app.models.incident import IncidentAnalysis, Relationship
from app.models.intelligence import EnrichmentClaim, LLMEnrichment

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ChroniX's evidence-constrained incident analyst.
Return only one concise JSON object with exactly these fields:
incident_summary, probable_causes, contributing_factors, causal_relationships,
evidence_interpretations, uncertainty, missing_evidence,
investigation_recommendations.
Use only supplied evidence IDs. Never invent events, IDs, timestamps, causes, or
certainty. Preserve uncertainty and the deterministic root-cause status.
Claims have description, evidence_ids, and optional confidence from 0 to 1.
incident_summary must describe observations and their order only; do not use
causal language there. Put tentative causal ideas only in probable_causes and
label them as unconfirmed when the deterministic assessment is NOT CONFIRMED or
PROBABLE. When status is NOT CONFIRMED, describe candidate explanations as
possible contributors supported by correlation; never state that one event
caused another, and explicitly say direct causal evidence is missing where
relevant. When status is PROBABLE, state that the explanation is probable but
not directly confirmed. Use causal wording only when status is CONFIRMED and
the supplied evidence supports that wording. Never set or override the
deterministic root-cause status. Do not attach numeric confidence percentages
unless the evidence itself supplies a measured probability.
Do not return markdown, explanations, or reasoning."""


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
        "root_cause_status": analysis.root_cause_status,
        "evidence": [
            {
                "evidence_id": event.source_id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "event": event.event,
                "classification": event.classification,
                "source": event.source,
                "evidence": event.raw_evidence,
            }
            for event in analysis.timeline
        ],
        "known_conflicts": analysis.conflicts,
        "missing_evidence": analysis.missing_evidence,
    }


def _messages(analysis: IncidentAnalysis) -> tuple[list[dict[str, str]], int, int]:
    context = json.dumps({"incident": _context(analysis)}, separators=(",", ":"))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]
    input_chars = len(SYSTEM_PROMPT) + len(context)
    return messages, input_chars, max(1, round(input_chars / 4))


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


def _integrate_inferred_relationships(analysis: IncidentAnalysis, enrichment: LLMEnrichment) -> IncidentAnalysis:
    existing_relationships = list(analysis.relationships)
    evidence_ids = {event.source_id for event in analysis.timeline}
    for claim in enrichment.causal_relationships:
        if len(claim.evidence_ids) >= 2:
            src = claim.evidence_ids[0]
            tgt = claim.evidence_ids[1]
            if src in evidence_ids and tgt in evidence_ids and src != tgt:
                existing_relationships.append(
                    Relationship(
                        source_evidence_id=src,
                        target_evidence_id=tgt,
                        relationship_type="CAUSED_BY",
                        confidence=claim.confidence if claim.confidence is not None else 0.65,
                        basis=f"Inferred causal hypothesis: {claim.description}",
                        status="inferred",
                    )
                )
    return analysis.model_copy(update={"relationships": existing_relationships})


def _accept_response(analysis: IncidentAnalysis, response: httpx.Response, status: str) -> IncidentAnalysis:
    try:
        generated = _json_content(response.json()["choices"][0]["message"]["content"])
        enrichment = LLMEnrichment.model_validate(generated)
        evidence_ids = {event.source_id for event in analysis.timeline}
        if not _references_are_valid(enrichment, evidence_ids):
            return _status(analysis, "invalid_response")
        updated_analysis = _integrate_inferred_relationships(analysis, enrichment)
        return _status(updated_analysis, status, enrichment)
    except (json.JSONDecodeError, KeyError, TypeError, ValidationError, ValueError, IndexError):
        return _status(analysis, "invalid_response")



def _ollama_response_content(response: httpx.Response) -> str:
    return response.json()["message"]["content"]


def enrich_with_llm(analysis: IncidentAnalysis) -> IncidentAnalysis:
    provider = os.getenv("CHRONIX_LLM_PROVIDER", "ollama").lower()
    if provider in {"", "disabled", "none"}:
        return _status(analysis, "unavailable")

    messages, input_chars, approx_input_tokens = _messages(analysis)

    if provider == "ollama":
        ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
        max_output_tokens = int(os.getenv("OLLAMA_NUM_PREDICT", "768"))
        logger.info(
            "Ollama enrichment request: events=%d input_chars=%d approx_input_tokens=%d max_output_tokens=%d",
            len(analysis.timeline),
            input_chars,
            approx_input_tokens,
            max_output_tokens,
        )
        started = perf_counter()
        try:
            response = httpx.post(
                os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/chat",
                json={
                    "model": os.getenv("OLLAMA_MODEL", "qwen3:4b"),
                    "stream": False,
                    "format": LLMEnrichment.model_json_schema(),
                    "think": False,
                    "options": {"temperature": 0, "num_predict": max_output_tokens},
                    "messages": messages,
                },
                timeout=ollama_timeout,
            )
            response.raise_for_status()
        except httpx.ConnectError:
            logger.warning("Ollama enrichment unavailable after %.2fs", perf_counter() - started)
            return _status(analysis, "local_unavailable")
        except httpx.HTTPError:
            logger.warning("Ollama enrichment failed after %.2fs", perf_counter() - started)
            return _status(analysis, "local_failed")
        logger.info("Ollama enrichment response received in %.2fs", perf_counter() - started)
        try:
            generated = _json_content(_ollama_response_content(response))
            enrichment = LLMEnrichment.model_validate(generated)
            evidence_ids = {event.source_id for event in analysis.timeline}
            if not _references_are_valid(enrichment, evidence_ids):
                return _status(analysis, "invalid_response")
            updated_analysis = _integrate_inferred_relationships(analysis, enrichment)
            return _status(updated_analysis, "local", enrichment)
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
