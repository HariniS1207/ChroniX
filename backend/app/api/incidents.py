from fastapi import APIRouter, File, UploadFile

from app.connectors.file_connector import FileConnector
from app.models.incident import IncidentAnalysis
from app.services.analysis_service import analyze
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
