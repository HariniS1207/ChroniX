from fastapi import APIRouter, File, HTTPException, UploadFile

from app.connectors.file_connector import FileConnector
from app.db.repositories import IncidentRepository
from app.models.incident import IncidentAnalysis
from app.services.analysis_service import analyze
from app.services.active_incident import active_incident
from app.services.llm_service import enrich_with_llm

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])
repository = IncidentRepository()


@router.post("/analyze", response_model=IncidentAnalysis)
async def analyze_incident(files: list[UploadFile] = File(...)) -> IncidentAnalysis:
    events = []
    file_errors = []
    for upload in files:
        try:
            connector = FileConnector(upload.filename or "unknown", await upload.read())
            events.extend(connector.collect())
        except ValueError as exc:
            file_errors.append(f"{upload.filename or 'unknown'}: {exc}")
        except Exception as exc:
            file_errors.append(f"{upload.filename or 'unknown'}: could not process file ({exc})")
    return enrich_with_llm(analyze(events, file_errors))


@router.get("/active")
def get_active_incident() -> dict[str, object]:
    events = active_incident.snapshot()
    return {"events": events, "count": len(events)}


@router.get("")
def list_incidents() -> list[dict]:
    return repository.list_incidents()


@router.get("/{incident_id}")
def get_incident_detail(incident_id: str) -> dict:
    detail = repository.get_incident_detail(incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return detail


@router.post("/active/reset")
def reset_active_incident() -> dict[str, object]:
    active_incident.clear()
    return {"status": "reset", "count": 0}


@router.get("/active/intelligence")
def get_active_intelligence() -> dict[str, object]:
    analysis = active_incident.latest_analysis()
    if analysis is None:
        return {"status": "not_ready", "analysis": None}
    return {"status": "ready", "analysis": analysis}


@router.post("/analyze-active", response_model=IncidentAnalysis)
def analyze_active_incident() -> IncidentAnalysis:
    return active_incident.refresh()


@router.get("/active/graph")
def get_active_graph() -> dict[str, object]:
    analysis = active_incident.latest_analysis()
    if not analysis:
        return {"incident_id": active_incident.incident_id, "nodes": [], "edges": []}
    nodes = [
        {
            "id": event.source_id,
            "label": event.event,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "source": event.source,
            "classification": event.classification,
            "raw_evidence": event.raw_evidence,
        }
        for event in analysis.timeline
    ]
    edges = [
        {
            "id": rel.relationship_id,
            "source": rel.source_evidence_id,
            "target": rel.target_evidence_id,
            "relationship_type": rel.relationship_type,
            "confidence": rel.confidence,
            "basis": rel.basis,
            "status": rel.status,
        }
        for rel in analysis.relationships
    ]
    return {"incident_id": active_incident.incident_id, "nodes": nodes, "edges": edges}


@router.get("/{incident_id}/graph")
def get_incident_graph(incident_id: str) -> dict[str, object]:
    detail = repository.get_incident_detail(incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    analysis = detail.get("analysis")
    nodes = [
        {
            "id": item["evidence_id"],
            "label": item["event"],
            "timestamp": item.get("timestamp"),
            "source": item["source_name"],
            "classification": item.get("classification", "FACT"),
            "raw_evidence": item["raw_evidence"],
        }
        for item in detail.get("evidence", [])
    ]
    edges = detail.get("relationships", [])
    if analysis and "relationships" in analysis and not edges:
        edges = analysis["relationships"]
    return {"incident_id": incident_id, "nodes": nodes, "edges": edges}

