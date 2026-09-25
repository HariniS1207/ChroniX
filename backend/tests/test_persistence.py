from threading import Event
import time

import pytest
from fastapi.testclient import TestClient

from app.api.incidents import repository as api_repository
from app.db.database import connect
from app.db.repositories import IncidentRepository
from app.main import app
from app.models.incident import Evidence
from app.services.active_incident import ActiveIncidentStore, active_incident
from app.services.analysis_service import analyze

client = TestClient(app)


def evidence(source_id: str, event: str = "Payment API error rate increased") -> Evidence:
    return Evidence(source_type="application", source_name="Payment API", source_id=source_id, timestamp="2026-09-25T10:02:00", event=event, raw_evidence=f"evidence-{source_id}", metadata={"service": "payment-api"})


@pytest.fixture
def repository(tmp_path, monkeypatch) -> IncidentRepository:
    monkeypatch.setenv("CHRONIX_DB_PATH", str(tmp_path / "chronix.db"))
    return IncidentRepository()


def test_database_initialization_creates_tables(repository):
    with connect() as connection:
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"incidents", "evidence", "relationships", "analyses"}.issubset(tables)


def test_create_incident_and_persist_evidence(repository):
    incident_id = repository.create_incident("Payment Incident")
    assert repository.add_evidence(incident_id, evidence("evidence-001"))
    assert repository.get_incident(incident_id)["title"] == "Payment Incident"
    assert repository.get_evidence(incident_id, "evidence-001").event == "Payment API error rate increased"
    assert len(repository.get_incident_evidence(incident_id)) == 1


def test_duplicate_evidence_is_rejected(repository):
    incident_id = repository.create_incident()
    item = evidence("duplicate-001")
    assert repository.add_evidence(incident_id, item)
    assert not repository.add_evidence(incident_id, item)


def test_persist_and_retrieve_analysis(repository):
    incident_id = repository.create_incident()
    item = evidence("analysis-001")
    repository.add_evidence(incident_id, item)
    analysis = analyze([item], [])
    repository.save_analysis(incident_id, 1, analysis)
    revision, recovered = repository.get_latest_analysis(incident_id)
    assert revision == 1
    assert recovered.root_cause_status == "NOT CONFIRMED"
    assert recovered.timeline[0].source_id == "analysis-001"


def test_incident_survives_store_restart(repository):
    first = ActiveIncidentStore(repository=repository)
    first.clear()
    assert first.add(evidence("restart-001"))
    assert first.add(evidence("restart-002", "Database connection timeout"))

    restarted = ActiveIncidentStore(repository=IncidentRepository())
    assert len(restarted.snapshot()) == 2
    assert restarted.latest_analysis() is not None
    assert len(restarted.latest_analysis().timeline) == 2


def test_multiple_incidents_are_listed(repository):
    first = repository.create_incident("First")
    second = repository.create_incident("Second")
    repository.add_evidence(first, evidence("first-001"))
    repository.add_evidence(second, evidence("second-001"))
    assert {item["incident_id"] for item in repository.list_incidents()} == {first, second}


def test_revision_increments_when_evidence_changes(repository):
    store = ActiveIncidentStore(repository=repository)
    store.clear()
    store.add(evidence("revision-001"))
    first_revision = repository.get_active_incident()["revision"]
    store.add(evidence("revision-002", "Database connection timeout"))
    second_revision = repository.get_active_incident()["revision"]
    assert (first_revision, second_revision) == (1, 2)


def test_stale_llm_result_does_not_persist_over_newer_revision(repository):
    first_started = Event()
    release_first = Event()
    calls = []

    def enrichment(analysis):
        calls.append(len(analysis.timeline))
        if len(calls) == 1:
            first_started.set()
            release_first.wait(5)
        return analysis.model_copy(update={"llm_status": "local", "llm_enrichment": None})

    store = ActiveIncidentStore(repository=repository, enrichment=enrichment)
    store.clear()
    assert store.add(evidence("stale-persist-001", "alpha"))
    assert first_started.wait(5)
    assert store.add(evidence("stale-persist-002", "bravo"))
    release_first.set()
    deadline = time.monotonic() + 5
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert calls[:2] == [1, 2]
    assert repository.get_active_incident()["revision"] == 2
    assert len(repository.get_incident_evidence(repository.get_active_incident()["incident_id"])) == 2


def test_get_incidents_endpoint_returns_persisted_records():
    active_incident.clear()
    payload = {
        "source_type": "application",
        "source_name": "Payment API",
        "source_id": "api-persisted-001",
        "timestamp": "2026-09-25T15:00:00",
        "event": "Payment API error rate increased",
        "raw_evidence": "HTTP 500 threshold exceeded",
        "metadata": {"service": "payment-api"},
    }
    assert client.post("/api/v1/webhooks/events", json=payload).json()["status"] == "accepted"
    records = client.get("/api/v1/incidents").json()
    assert isinstance(records, list)
    assert any(record["status"] == "active" for record in records)
    active_incident.clear()


def test_history_list_contains_compact_metadata_and_newest_first(repository):
    older = repository.create_incident("Older incident")
    newer = repository.create_incident("Newer incident")
    repository.add_evidence(older, evidence("older-001"))
    repository.add_evidence(newer, evidence("newer-001"))
    records = repository.list_incidents()
    assert records[0]["incident_title"] == "Newer incident"
    assert records[0]["evidence_count"] == 1
    assert "raw_evidence" not in records[0]
    assert "llm_status" in records[0]


def test_incident_detail_contains_evidence_and_analysis(repository):
    incident_id = repository.create_incident("Detailed incident")
    item = evidence("detail-001")
    repository.add_evidence(incident_id, item)
    repository.save_analysis(incident_id, 1, analyze([item], []))
    detail = repository.get_incident_detail(incident_id)
    assert detail["evidence"][0]["source_id"] == "detail-001"
    assert detail["analysis"]["root_cause_status"] == "NOT CONFIRMED"
    assert detail["timeline"][0]["source_id"] == "detail-001"


def test_unknown_incident_returns_404():
    response = client.get("/api/v1/incidents/does-not-exist")
    assert response.status_code == 404


def test_empty_history_returns_empty_list(monkeypatch):
    monkeypatch.setattr(api_repository, "list_incidents", lambda: [])
    assert client.get("/api/v1/incidents").json() == []