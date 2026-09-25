from fastapi import APIRouter, File, UploadFile

from app.connectors.file_connector import FileConnector
from app.models.incident import IncidentAnalysis
from app.services.analysis_service import analyze
from app.services.active_incident import active_incident
from app.services.llm_service import enrich_with_llm

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


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
