from datetime import datetime
from fastapi.testclient import TestClient

from app.main import app
from app.models.incident import Evidence, Event
from app.models.intelligence import EnrichmentClaim, LLMEnrichment
from app.services.active_incident import active_incident
from app.services.analysis_service import analyze, build_deterministic_relationships
from app.services.llm_service import _integrate_inferred_relationships

client = TestClient(app)


def setup_function():
    active_incident.clear()


def test_deterministic_relationships_generation():
    events = [
        Event(
            source_type="file",
            source_name="monitoring.csv",
            source_id="mon:1",
            timestamp=datetime(2026, 9, 25, 10, 2, 0),
            event="Database connection pool timeout",
            raw_evidence="timeout count 45",
            classification="FACT",
        ),
        Event(
            source_type="file",
            source_name="logs.txt",
            source_id="log:1",
            timestamp=datetime(2026, 9, 25, 10, 5, 0),
            event="Payment API returned 504 gateway timeout",
            raw_evidence="504 gateway timeout",
            classification="FACT",
        ),
        Event(
            source_type="file",
            source_name="chat.txt",
            source_id="chat:1",
            timestamp=datetime(2026, 9, 25, 10, 8, 0),
            event="Engineers suspect database server failure",
            raw_evidence="database seems down",
            classification="INFERENCE",
        ),
        Event(
            source_type="file",
            source_name="metrics.csv",
            source_id="met:1",
            timestamp=datetime(2026, 9, 25, 10, 10, 0),
            event="Database CPU and memory metrics reported normal healthy status",
            raw_evidence="cpu 12% normal",
            classification="FACT",
        ),
        Event(
            source_type="file",
            source_name="deploy.log",
            source_id="dep:1",
            timestamp=datetime(2026, 9, 25, 10, 12, 0),
            event="Payment service restarted successfully",
            raw_evidence="service restarted",
            classification="FACT",
        ),
    ]

    relationships = build_deterministic_relationships(events)
    assert len(relationships) >= 3

    # Check PRECEDED relationship
    preceded = [r for r in relationships if r.relationship_type == "PRECEDED"]
    assert len(preceded) >= 1
    assert preceded[0].confidence == 1.0
    assert preceded[0].status == "deterministic"
    assert "preceded" in preceded[0].basis.lower()

    # Check CONFLICTS_WITH relationship between inference of failure and fact of health
    conflicts = [r for r in relationships if r.relationship_type == "CONFLICTS_WITH"]
    assert len(conflicts) >= 1
    assert conflicts[0].source_evidence_id == "chat:1"
    assert conflicts[0].target_evidence_id == "met:1"
    assert conflicts[0].status == "deterministic"

    # Check CORRELATED_WITH
    correlated = [r for r in relationships if r.relationship_type == "CORRELATED_WITH"]
    assert len(correlated) >= 1
    assert correlated[0].status == "deterministic"


def test_inferred_relationship_validation():
    raw_evidence = [
        Evidence(
            source_type="file",
            source_name="app.log",
            source_id="app:1",
            timestamp=datetime(2026, 9, 25, 10, 0),
            event="Payment timeout",
            raw_evidence="err",
        ),
        Evidence(
            source_type="file",
            source_name="db.log",
            source_id="db:1",
            timestamp=datetime(2026, 9, 25, 10, 1),
            event="Database lock",
            raw_evidence="lock",
        ),
    ]
    analysis = analyze(raw_evidence, [])

    # LLM claim referencing valid IDs
    valid_enrichment = LLMEnrichment(
        incident_summary="Test incident",
        causal_relationships=[
            EnrichmentClaim(
                description="Database lock caused payment timeout",
                evidence_ids=["db:1", "app:1"],
                confidence=0.8,
            )
        ],
    )
    enriched = _integrate_inferred_relationships(analysis, valid_enrichment)
    inferred = [r for r in enriched.relationships if r.status == "inferred"]
    assert len(inferred) == 1
    assert inferred[0].source_evidence_id == "db:1"
    assert inferred[0].target_evidence_id == "app:1"
    assert inferred[0].relationship_type == "CAUSED_BY"
    assert inferred[0].confidence == 0.8
    assert "Inferred causal hypothesis" in inferred[0].basis

    # LLM claim referencing hallucinated ID must NOT produce an inferred relationship
    invalid_enrichment = LLMEnrichment(
        incident_summary="Test incident",
        causal_relationships=[
            EnrichmentClaim(
                description="Hallucinated connection",
                evidence_ids=["fake:999", "app:1"],
                confidence=0.9,
            )
        ],
    )
    enriched_invalid = _integrate_inferred_relationships(analysis, invalid_enrichment)
    inferred_invalid = [r for r in enriched_invalid.relationships if r.status == "inferred"]
    assert len(inferred_invalid) == 0


def test_graph_endpoints_and_persistence():
    # Upload evidence to active incident
    client.post(
        "/api/v1/evidence/upload",
        files={"file": ("events.log", b"2026-09-25 10:00:00 Payment gateway timeout\n2026-09-25 10:01:00 Database connection failed\n", "text/plain")},
    )


    graph_res = client.get("/api/v1/incidents/active/graph")
    assert graph_res.status_code == 200
    graph_data = graph_res.json()
    assert len(graph_data["nodes"]) == 2
    assert len(graph_data["edges"]) >= 1

    edge = graph_data["edges"][0]
    assert "source" in edge
    assert "target" in edge
    assert "relationship_type" in edge
    assert "confidence" in edge
    assert "basis" in edge
    assert "status" in edge

    # Query historical incident graph
    incident_id = graph_data["incident_id"]
    detail_graph = client.get(f"/api/v1/incidents/{incident_id}/graph")
    assert detail_graph.status_code == 200
    assert len(detail_graph.json()["nodes"]) == 2
