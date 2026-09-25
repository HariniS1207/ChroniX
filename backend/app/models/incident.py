from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.intelligence import LLMEnrichment, LLMStatus

Classification = Literal["FACT", "INFERENCE", "CONFLICT", "UNKNOWN"]


class Evidence(BaseModel):
    source_type: str
    source_name: str
    source_id: str
    timestamp: datetime | None = None
    event: str
    raw_evidence: str
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def source(self) -> str:
        return self.source_name

    @property
    def evidence(self) -> str:
        return self.raw_evidence


class Event(Evidence):
    classification: Classification = "FACT"
    sources: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    related_event_ids: list[int] = Field(default_factory=list)
    order: int = 0

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_source_fields(cls, values: object) -> object:
        if isinstance(values, dict):
            values = dict(values)
            source = values.pop("source", None)
            evidence = values.pop("evidence", None)
            if source is not None:
                values.setdefault("source_name", source)
            if evidence is not None:
                values.setdefault("raw_evidence", evidence)
            values.setdefault("source_type", "file")
            values.setdefault("source_id", values.get("source_name", "unknown"))
            values.setdefault("sources", [values.get("source_name", "unknown")])
            values.setdefault("supporting_evidence", [values.get("raw_evidence", "")])
        return values

    @computed_field
    @property
    def source(self) -> str:
        return ", ".join(self.sources or [self.source_name])

    @computed_field
    @property
    def evidence(self) -> str:
        return self.raw_evidence


class IncidentAnalysis(BaseModel):
    incident_title: str
    summary: str
    root_cause_status: str
    timeline: list[Event]
    facts: list[str]
    inferences: list[str]
    conflicts: list[str]
    unknowns: list[str]
    missing_evidence: list[str]
    file_errors: list[str] = Field(default_factory=list)
    llm_status: LLMStatus = "unavailable"
    llm_enrichment: LLMEnrichment | None = None
