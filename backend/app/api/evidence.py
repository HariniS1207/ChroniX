import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.connectors.file_connector import FileConnector
from app.services.active_incident import active_incident

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])
SUPPORTED_EXTENSIONS = {".txt", ".log", ".csv", ".json", ".pdf"}
MIME_TYPES = {"text/plain", "text/csv", "application/csv", "application/json", "application/pdf", "application/octet-stream"}


def _max_upload_bytes() -> int:
    return int(float(os.getenv("CHRONIX_MAX_UPLOAD_MB", "10")) * 1024 * 1024)


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "upload").name
    if name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="filename is invalid")
    return name


@router.post("/upload")
async def upload_evidence(file: UploadFile = File(...), incident_id: str | None = Form(default=None)) -> dict[str, object]:
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="supported file types are TXT, LOG, CSV, JSON, and PDF")
    if file.content_type and file.content_type not in MIME_TYPES:
        raise HTTPException(status_code=415, detail="file MIME type is not supported")
    data = await file.read(_max_upload_bytes() + 1)
    if not data:
        raise HTTPException(status_code=400, detail="file is empty")
    if len(data) > _max_upload_bytes():
        raise HTTPException(status_code=413, detail="file exceeds the configured upload size limit")
    try:
        items = FileConnector(filename, data).collect()
    except (UnicodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not items:
        raise HTTPException(status_code=400, detail="file contains no usable evidence")

    content_hash = hashlib.sha256(data).hexdigest()[:16]
    for index, item in enumerate(items):
        item.source_id = f"{filename}:{content_hash}:{index}"

    if incident_id:
        try:
            created_count, duplicate_count = active_incident.add_to_historical_incident(incident_id, items)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="incident not found") from exc
        processing_status = "local_pending" if created_count else "unchanged"
    else:
        created_count = 0
        duplicate_count = 0
        for item in items:
            if active_incident.add(item):
                created_count += 1
            else:
                duplicate_count += 1
        current = active_incident.latest_analysis()
        processing_status = current.llm_status if current else "local_pending"

    return {
        "incident_id": incident_id or active_incident.incident_id,
        "created_count": created_count,
        "duplicate_count": duplicate_count,
        "rejected_count": 0,
        "sources": [filename],
        "processing_status": processing_status,
    }