from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.active_incident import active_incident
from app.processors.evidence import extract_json

client = TestClient(app)


def setup_function():
    active_incident.clear()


def upload(name: str, content: bytes, content_type: str = "text/plain", incident_id: str | None = None):
    data = {"incident_id": incident_id} if incident_id else {}
    return client.post("/api/v1/evidence/upload", files={"file": (name, content, content_type)}, data=data)


def test_upload_txt_and_log_creates_normalized_evidence():
    response = upload("events.log", b"2026-09-25 10:02:13 ERROR Payment API timeout\nUn-timestamped operator note")
    assert response.status_code == 200, response.json()
    assert response.json()["created_count"] == 2
    assert client.get("/api/v1/incidents/active").json()["count"] == 2


def test_upload_csv_preserves_unknown_columns():
    response = upload("events.csv", b"timestamp,event,service,region\n10:02,API error,payment,eu-west\n", "text/csv")
    assert response.status_code == 200
    incident_id = response.json()["incident_id"]
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["evidence"][0]["metadata"]["region"] == "eu-west"


def test_json_object_and_array_normalize():
    assert len(extract_json(b'{"timestamp":"10:02","event":"API error","service":"payments"}', "one.json")) == 1
    assert len(extract_json(b'[{"event":"first"},{"event":"second"}]', "many.json")) == 2


def test_upload_json_and_pdf():
    json_response = upload("events.json", b'[{"timestamp":"10:02","event":"API error"},{"event":"service recovered"}]', "application/json")
    assert json_response.status_code == 200
    pdf_path = Path(__file__).parents[2] / "sample_data" / "incident_report.pdf"
    pdf_response = upload("incident.pdf", pdf_path.read_bytes(), "application/pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.json()["created_count"] >= 1


def test_malformed_and_unsupported_uploads_are_rejected():
    assert upload("bad.json", b"{not json", "application/json").status_code == 400
    assert upload("script.py", b"print('no')", "text/plain").status_code == 415
    assert upload("empty.txt", b"").status_code == 400


def test_duplicate_upload_reports_duplicates():
    content = b"2026-09-25 10:02 API error\n"
    first = upload("same.log", content)
    second = upload("same.log", content)
    assert first.json()["created_count"] == 1
    assert second.json()["created_count"] == 0
    assert second.json()["duplicate_count"] == 1


def test_oversized_upload_is_rejected(monkeypatch):
    monkeypatch.setenv("CHRONIX_MAX_UPLOAD_MB", "0.00001")
    assert upload("large.txt", b"2026-09-25 10:02 API error\n").status_code == 413


def test_historical_upload_targets_requested_incident():
    initial = upload("historical.txt", b"2026-09-25 10:02 historical evidence\n")
    incident_id = initial.json()["incident_id"]
    active_incident.clear()
    response = upload("more.txt", b"2026-09-25 10:03 historical follow-up\n", incident_id=incident_id)
    assert response.status_code == 200, response.json()
    assert response.json()["incident_id"] == incident_id
    assert client.get(f"/api/v1/incidents/{incident_id}").json()["evidence_count"] == 2
    assert client.get("/api/v1/incidents/active").json()["count"] == 0