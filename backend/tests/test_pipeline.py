from fastapi.testclient import TestClient

from app.connectors.file_connector import FileConnector
from app.connectors.webhook_connector import WebhookConnector
from app.main import app
from app.models.incident import Evidence
from app.processors.evidence import extract_csv, extract_lines, extract_pdf, parse_timestamp
from app.services.analysis_service import analyze

client = TestClient(app)


def test_health_endpoint():
    assert client.get("/health").json() == {"status": "ok"}


def test_csv_extraction():
    events = extract_csv(b"timestamp,event\n2026-09-25T10:02:00,API errors increased\n", "monitoring.csv")
    assert events[0].event == "API errors increased"
    assert events[0].source == "monitoring.csv"
    assert events[0].timestamp is not None


def test_txt_extraction():
    events = extract_lines(b"[2026-09-25 10:08] Database failure suspected\n", "chat.txt")
    assert events[0].timestamp is not None
    assert "Database failure" in events[0].event


def test_file_connector_returns_normalized_evidence():
    evidence = FileConnector("monitoring.csv", b"timestamp,event\n2026-09-25T10:02:00,API errors increased\n").collect()[0]
    assert isinstance(evidence, Evidence)
    assert evidence.source_type == "file"
    assert evidence.source_name == "monitoring.csv"
    assert evidence.source_id == "monitoring.csv"
    assert evidence.raw_evidence.startswith("timestamp:")
    assert evidence.metadata["format"] == "csv"


def test_webhook_connector_returns_normalized_evidence():
    evidence = WebhookConnector({"timestamp": "2026-09-25T10:08:00", "event": "Database failure suspected", "metadata": {"service": "payments"}}, "monitoring-webhook", "evt-123").collect()[0]
    assert evidence.source_type == "webhook"
    assert evidence.source_id == "evt-123"
    assert evidence.timestamp is not None
    assert evidence.metadata == {"service": "payments"}


def test_pdf_extraction_keeps_meaningful_sentences_together():
    data = b"ChroniX incident report\n2026-09-25 10:02 API error rate increased significantly.\nIncident window: to\nAt , monitoring detected a significant increase..."
    events = extract_pdf(data, "incident_report.pdf")
    assert len(events) == 1
    assert events[0].event == "API error rate increased significantly."
    assert events[0].timestamp.hour == 10


def test_duplicate_events_merge_and_preserve_sources():
    evidence = extract_csv(b"timestamp,event\n2026-09-25T10:02:00,API error rate increased significantly\n", "monitoring.csv")
    evidence.extend(extract_lines(b"2026-09-25 10:02 API error rate increased significantly.\n", "incident_report.pdf"))
    result = analyze(evidence, [])
    assert len(result.timeline) == 1
    assert result.timeline[0].sources == ["monitoring.csv", "incident_report.pdf"]


def test_conflict_is_a_relationship_between_two_events():
    evidence = extract_lines(b"2026-09-25 10:08 DB seems to be failing.\n", "engineer_chat.txt")
    evidence.extend(extract_lines(b"2026-09-25 10:12 Database CPU returned to normal range.\n", "monitoring.csv"))
    result = analyze(evidence, [])
    assert [event.classification for event in result.timeline] == ["INFERENCE", "FACT"]
    assert len(result.conflicts) == 1
    assert "engineer_chat.txt" in result.conflicts[0]
    assert "monitoring.csv" in result.conflicts[0]


def test_short_timestamp_is_normalized_to_demo_date():
    timestamp = parse_timestamp("10:02")
    assert timestamp.isoformat() == "2026-09-25T10:02:00"


def test_normalization_sorting_and_classification():
    events = extract_lines(b"2026-09-25 10:08 Database failure suspected\n2026-09-25 10:02 API errors increased\n", "incident.txt")
    result = analyze(events, [])
    assert result.timeline[0].timestamp.hour == 10
    assert result.timeline[0].timestamp.minute == 2
    assert result.timeline[1].classification == "INFERENCE"
    assert result.root_cause_status == "NOT CONFIRMED"


def test_analyze_endpoint():
    response = client.post("/api/v1/incidents/analyze", files=[("files", ("monitoring.csv", b"timestamp,event\n2026-09-25T10:02:00,API errors increased\n", "text/csv"))])
    assert response.status_code == 200
    assert response.json()["timeline"][0]["source"] == "monitoring.csv"
