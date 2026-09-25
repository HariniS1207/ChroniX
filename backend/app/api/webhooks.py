from fastapi import APIRouter

from app.connectors.webhook_connector import WebhookConnector
from app.models.incident import Evidence
from app.services.active_incident import active_incident

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/events")
def receive_event(payload: Evidence) -> dict[str, str | int]:
    evidence = WebhookConnector(payload.model_dump()).collect()[0]
    if not active_incident.add(evidence):
        return {"status": "duplicate", "source_id": evidence.source_id}
    return {"status": "accepted", "source_id": evidence.source_id, "incident_events": len(active_incident.snapshot())}
