from datetime import datetime

from app.models.incident import Event
from app.services.semantic_service import SemanticCorrelator


def test_semantic_similarity_detects_related_operational_events():
    correlator = SemanticCorrelator(threshold=0.35)
    # Different wording, same operational domain
    sim = correlator.compute_similarity("DB connection timeout", "database pool exhausted")
    assert sim > 0.35, f"Expected similarity > 0.35, got {sim}"

    # Dissimilar events
    unrelated_sim = correlator.compute_similarity("DB connection timeout", "User updated billing address in profile")
    assert unrelated_sim < sim, f"Expected unrelated similarity {unrelated_sim} < {sim}"


def test_semantic_correlator_produces_traceable_relationships():
    events = [
        Event(
            source_type="file",
            source_name="db.log",
            source_id="db:1",
            timestamp=datetime(2026, 9, 25, 10, 0),
            event="DB connection timeout on pool 1",
            raw_evidence="timeout",
        ),
        Event(
            source_type="file",
            source_name="metrics.csv",
            source_id="met:1",
            timestamp=datetime(2026, 9, 25, 10, 1),
            event="database pool exhausted with 0 available connections",
            raw_evidence="connections 0",
        ),
        Event(
            source_type="file",
            source_name="ui.log",
            source_id="ui:1",
            timestamp=datetime(2026, 9, 25, 10, 2),
            event="User changed account profile theme",
            raw_evidence="theme changed",
        ),
    ]

    correlator = SemanticCorrelator(threshold=0.30)
    relationships = correlator.find_semantic_correlations(events)

    # Should correlate db:1 and met:1, but not ui:1
    correlated_ids = {(r.source_evidence_id, r.target_evidence_id) for r in relationships}
    assert ("db:1", "met:1") in correlated_ids or ("met:1", "db:1") in correlated_ids
    assert not any("ui:1" in pair for pair in correlated_ids)

    rel = next(r for r in relationships if r.source_evidence_id in {"db:1", "met:1"} and r.target_evidence_id in {"db:1", "met:1"})
    assert rel.relationship_type == "CORRELATED_WITH"
    assert rel.status == "deterministic"
    assert "Semantic correlation" in rel.basis
    assert rel.confidence >= 0.60
