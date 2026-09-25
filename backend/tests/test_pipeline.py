import time
from threading import Event

import httpx

from fastapi.testclient import TestClient

from app.connectors.file_connector import FileConnector
from app.connectors.webhook_connector import WebhookConnector
from app.main import app
from app.models.incident import Evidence
from app.processors.evidence import extract_csv, extract_lines, extract_pdf, parse_timestamp
from app.services.active_incident import ActiveIncidentStore, active_incident
from app.services.analysis_service import analyze
from app.services.llm_service import _messages, enrich_with_llm

client = TestClient(app)


def test_health_endpoint():
    assert client.get("/health").json() == {"status": "ok"}


def test_backend_allows_vite_fallback_origin():
    response = client.options(
        "/api/v1/incidents/analyze-active",
        headers={
            "Origin": "http://localhost:5177",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5177"


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


def webhook_payload(source_id: str = "webhook-test-001") -> dict:
    return {
        "source_type": "application",
        "source_name": "Payment API",
        "source_id": source_id,
        "timestamp": "2026-09-25T15:00:00",
        "event": "Payment API error rate increased",
        "raw_evidence": "HTTP 500 error rate exceeded threshold",
        "metadata": {"severity": "critical", "service": "payment-api"},
    }


def test_valid_webhook_is_accepted_and_normalized():
    response = client.post("/api/v1/webhooks/events", json=webhook_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["incident_events"] >= 1
    intelligence = client.get("/api/v1/incidents/active/intelligence").json()
    assert intelligence["status"] == "ready"
    assert intelligence["analysis"]["timeline"][0]["source_id"] == "webhook-test-001"


def test_invalid_webhook_returns_validation_error():
    response = client.post("/api/v1/webhooks/events", json={"source_id": "missing-fields"})
    assert response.status_code == 422


def test_duplicate_webhook_source_id_is_reported():
    payload = webhook_payload("webhook-duplicate-001")
    assert client.post("/api/v1/webhooks/events", json=payload).json()["status"] == "accepted"
    before = client.get("/api/v1/incidents/active/intelligence").json()["analysis"]["timeline"]
    duplicate = client.post("/api/v1/webhooks/events", json=payload)
    assert duplicate.json() == {"status": "duplicate", "source_id": "webhook-duplicate-001"}
    after = client.get("/api/v1/incidents/active/intelligence").json()["analysis"]["timeline"]
    assert len(after) == len(before)


def test_active_incident_retrieval_and_analysis_use_webhook_evidence():
    client.post("/api/v1/webhooks/events", json=webhook_payload("webhook-active-001"))
    active = client.get("/api/v1/incidents/active")
    assert active.status_code == 200
    assert any(item["source_id"] == "webhook-active-001" for item in active.json()["events"])
    analysis = client.post("/api/v1/incidents/analyze-active")
    assert analysis.status_code == 200
    assert any(item["source_name"] == "Payment API" and item["event"] == "Payment API error rate increased" for item in analysis.json()["timeline"])


def test_active_incident_reset_clears_in_memory_state():
    response = client.post("/api/v1/incidents/active/reset")
    assert response.json() == {"status": "reset", "count": 0}
    assert client.get("/api/v1/incidents/active").json() == {"events": [], "count": 0}
    assert client.get("/api/v1/incidents/active/intelligence").json() == {"status": "not_ready", "analysis": None}


def test_multiple_webhook_events_are_kept_as_separate_evidence():
    first = webhook_payload("webhook-multiple-001")
    second = webhook_payload("webhook-multiple-002")
    second["event"] = "Payment service restarted"
    assert client.post("/api/v1/webhooks/events", json=first).json()["status"] == "accepted"
    assert client.post("/api/v1/webhooks/events", json=second).json()["status"] == "accepted"
    active_ids = {item["source_id"] for item in client.get("/api/v1/incidents/active").json()["events"]}
    assert {first["source_id"], second["source_id"]}.issubset(active_ids)


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_webhook_returns_without_waiting_for_llm(monkeypatch):
    active_incident.clear()
    started = Event()
    release = Event()

    def blocked_enrichment(analysis):
        started.set()
        release.wait(5)
        return analysis.model_copy(update={"llm_status": "local", "llm_enrichment": None})

    monkeypatch.setattr("app.services.llm_service.enrich_with_llm", blocked_enrichment)
    began = time.monotonic()
    response = client.post("/api/v1/webhooks/events", json=webhook_payload("fast-webhook-001"))
    elapsed = time.monotonic() - began
    release.set()

    assert response.json()["status"] == "accepted"
    assert elapsed < 0.2
    assert wait_for(started.is_set)


def test_seven_webhooks_are_accepted_without_waiting_for_enrichment():
    active_incident.clear()
    responses = [client.post("/api/v1/webhooks/events", json=webhook_payload(f"rapid-http-{index:03d}")).json() for index in range(7)]
    assert [response["status"] for response in responses] == ["accepted"] * 7
    assert len(active_incident.snapshot()) == 7


def test_rapid_webhooks_coalesce_to_one_llm_call(monkeypatch):
    active_incident.clear()
    calls = []
    completed = Event()

    def count_enrichment(analysis):
        calls.append(len(analysis.timeline))
        completed.set()
        return analysis.model_copy(update={"llm_status": "local", "llm_enrichment": None})

    store = ActiveIncidentStore(enrichment=count_enrichment)
    store.clear()
    for index in range(7):
        payload = webhook_payload(f"coalesced-{index:03d}")
        payload["timestamp"] = f"2026-09-25T15:{index:02d}:00"
        payload["event"] = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"][index]
        payload["raw_evidence"] = f"Payment evidence {index}"
        assert store.add(WebhookConnector(payload).collect()[0])

    assert completed.wait(5)
    assert calls == [7]
    assert len(store.snapshot()) == 7


def test_llm_failure_keeps_deterministic_analysis_available(monkeypatch):
    active_incident.clear()

    def failed_enrichment(analysis):
        return analysis.model_copy(update={"llm_status": "local_failed", "llm_enrichment": None})

    monkeypatch.setattr("app.services.llm_service.enrich_with_llm", failed_enrichment)
    response = client.post("/api/v1/webhooks/events", json=webhook_payload("failed-llm-001"))
    assert response.json()["status"] == "accepted"
    assert wait_for(lambda: active_incident.latest_analysis() is not None and active_incident.latest_analysis().llm_status == "local_failed")
    analysis = active_incident.latest_analysis()
    assert analysis is not None
    assert len(analysis.timeline) == 1
    assert analysis.root_cause_status == "NOT CONFIRMED"


def test_stale_llm_result_cannot_overwrite_newer_evidence(monkeypatch):
    active_incident.clear()
    first_started = Event()
    release_first = Event()
    calls = []

    def stale_enrichment(analysis):
        calls.append(len(analysis.timeline))
        if len(calls) == 1:
            first_started.set()
            release_first.wait(5)
        return analysis.model_copy(update={"llm_status": "local", "llm_enrichment": None})

    store = ActiveIncidentStore(enrichment=stale_enrichment)
    store.clear()
    first_payload = webhook_payload("stale-001")
    first_payload["event"] = "alpha"
    first_payload["raw_evidence"] = "First payment evidence"
    assert store.add(WebhookConnector(first_payload).collect()[0])
    assert first_started.wait(5)
    second_payload = webhook_payload("stale-002")
    second_payload["timestamp"] = "2026-09-25T15:01:00"
    second_payload["event"] = "bravo"
    second_payload["raw_evidence"] = "Second payment evidence"
    assert store.add(WebhookConnector(second_payload).collect()[0])
    release_first.set()

    assert wait_for(lambda: len(calls) == 2)
    analysis = store.latest_analysis()
    assert analysis is not None
    assert calls == [1, 2]
    assert len(analysis.timeline) == 2
    assert analysis.root_cause_status == "NOT CONFIRMED"


class FakeLLMResponse:
    def __init__(self, content: str):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class FakeOllamaResponse:
    def __init__(self, content: str):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": self.content}}


def llm_analysis():
    return analyze(extract_lines(b"2026-09-25 10:02 API error rate increased\n", "monitoring.csv"), [])


def test_llm_unavailable_keeps_deterministic_analysis(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    analysis = llm_analysis()
    enriched = enrich_with_llm(analysis)
    assert enriched.llm_status == "unavailable"
    assert enriched.llm_enrichment is None
    assert enriched.root_cause_status == "NOT CONFIRMED"
    assert enriched.timeline[0].raw_evidence == analysis.timeline[0].raw_evidence


def test_valid_structured_llm_response_is_accepted(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("app.services.llm_service.httpx.post", lambda *args, **kwargs: FakeLLMResponse('{"incident_summary":"Errors rose after a payment change.","probable_causes":[{"description":"A payment component may be involved.","evidence_ids":["monitoring.csv"],"confidence":0.72}],"contributing_factors":[],"causal_relationships":[],"evidence_interpretations":[],"uncertainty":[{"description":"The root cause is not confirmed.","evidence_ids":["monitoring.csv"]}],"missing_evidence":[],"investigation_recommendations":["Collect deployment impact data."]}'))
    analysis = llm_analysis()
    enriched = enrich_with_llm(analysis)
    assert enriched.llm_status == "used"
    assert enriched.llm_enrichment is not None
    assert enriched.llm_enrichment.probable_causes[0].evidence_ids == ["monitoring.csv"]
    assert enriched.root_cause_status == "NOT CONFIRMED"
    assert enriched.timeline[0].raw_evidence == analysis.timeline[0].raw_evidence


def test_malformed_llm_response_is_rejected(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("app.services.llm_service.httpx.post", lambda *args, **kwargs: FakeLLMResponse("not json"))
    enriched = enrich_with_llm(llm_analysis())
    assert enriched.llm_status == "invalid_response"
    assert enriched.llm_enrichment is None


def test_missing_evidence_reference_is_rejected(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    content = '{"incident_summary":"Uncertain.","probable_causes":[{"description":"Unsupported cause.","evidence_ids":["missing-id"]}]}'
    monkeypatch.setattr("app.services.llm_service.httpx.post", lambda *args, **kwargs: FakeLLMResponse(content))
    enriched = enrich_with_llm(llm_analysis())
    assert enriched.llm_status == "invalid_response"
    assert enriched.llm_enrichment is None


def test_llm_api_failure_preserves_deterministic_result(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def failing_post(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.services.llm_service.httpx.post", failing_post)
    analysis = llm_analysis()
    enriched = enrich_with_llm(analysis)
    assert enriched.llm_status == "failed"
    assert enriched.llm_enrichment is None
    assert enriched.facts == analysis.facts


def test_ollama_success_returns_local_status(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "ollama")
    content = '{"incident_summary":"The payment API experienced elevated errors.","probable_causes":[],"contributing_factors":[],"causal_relationships":[],"evidence_interpretations":[{"description":"The error increase is directly observed.","evidence_ids":["monitoring.csv"]}],"uncertainty":[{"description":"Root cause remains unconfirmed.","evidence_ids":["monitoring.csv"]}],"missing_evidence":[],"investigation_recommendations":[]}'
    monkeypatch.setattr("app.services.llm_service.httpx.post", lambda *args, **kwargs: FakeOllamaResponse(content))
    analysis = llm_analysis()
    enriched = enrich_with_llm(analysis)
    assert enriched.llm_status == "local"
    assert enriched.llm_enrichment is not None
    assert enriched.root_cause_status == "NOT CONFIRMED"
    assert enriched.timeline[0].raw_evidence == analysis.timeline[0].raw_evidence


def test_ollama_prompt_is_compact_and_output_is_bounded(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "ollama")
    captured = {}
    content = '{"incident_summary":"Observed errors.","probable_causes":[],"contributing_factors":[],"causal_relationships":[],"evidence_interpretations":[],"uncertainty":[],"missing_evidence":[],"investigation_recommendations":[]}'

    def capture_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeOllamaResponse(content)

    monkeypatch.setattr("app.services.llm_service.httpx.post", capture_post)
    analysis = llm_analysis()
    messages, input_chars, approx_tokens = _messages(analysis)
    enriched = enrich_with_llm(analysis)

    assert enriched.llm_status == "local"
    assert input_chars == sum(len(message["content"]) for message in messages)
    assert approx_tokens > 0
    assert "deterministic_facts" not in messages[1]["content"]
    assert "raw_evidence" not in messages[1]["content"]
    assert isinstance(captured["json"]["format"], dict)
    assert captured["json"]["think"] is False
    assert captured["json"]["options"]["num_predict"] == 768


def test_ollama_timeout_returns_local_failed(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "ollama")

    def timed_out_post(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.services.llm_service.httpx.post", timed_out_post)
    enriched = enrich_with_llm(llm_analysis())
    assert enriched.llm_status == "local_failed"
    assert enriched.llm_enrichment is None
    assert enriched.root_cause_status == "NOT CONFIRMED"


def test_ollama_unavailable_preserves_deterministic_result(monkeypatch):
    monkeypatch.setenv("CHRONIX_LLM_PROVIDER", "ollama")

    def unavailable_post(*args, **kwargs):
        raise httpx.ConnectError("Ollama is unavailable")

    monkeypatch.setattr("app.services.llm_service.httpx.post", unavailable_post)
    enriched = enrich_with_llm(llm_analysis())
    assert enriched.llm_status == "local_unavailable"
    assert enriched.llm_enrichment is None
    assert enriched.root_cause_status == "NOT CONFIRMED"
