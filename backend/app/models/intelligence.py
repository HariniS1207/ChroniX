from typing import Literal

from pydantic import BaseModel, Field

LLMStatus = Literal[
    "local_pending",
    "local_processing",
    "local",
    "local_unavailable",
    "local_failed",
    "invalid_response",
    "used",
    "unavailable",
    "failed",
]


class EnrichmentClaim(BaseModel):
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class LLMEnrichment(BaseModel):
    incident_summary: str
    probable_causes: list[EnrichmentClaim] = Field(default_factory=list)
    contributing_factors: list[EnrichmentClaim] = Field(default_factory=list)
    causal_relationships: list[EnrichmentClaim] = Field(default_factory=list)
    evidence_interpretations: list[EnrichmentClaim] = Field(default_factory=list)
    uncertainty: list[EnrichmentClaim] = Field(default_factory=list)
    missing_evidence: list[EnrichmentClaim] = Field(default_factory=list)
    investigation_recommendations: list[str] = Field(default_factory=list)
