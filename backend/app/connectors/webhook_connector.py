from datetime import datetime
from typing import Any

from app.connectors.base import Connector
from app.models.incident import Evidence


class WebhookConnector(Connector):
    """Normalize a generic webhook payload without binding ChroniX to a vendor."""

    def __init__(self, payload: dict[str, Any], source_name: str, source_id: str | None = None):
        self.payload = payload
        self.source_name = source_name
        self.source_id = source_id or source_name

    def collect(self) -> list[Evidence]:
        event = str(self.payload.get("event") or self.payload.get("message") or "Webhook event")
        raw_evidence = str(self.payload.get("raw_evidence") or self.payload.get("evidence") or event)
        timestamp = self.payload.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        metadata = self.payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {"payload_metadata": str(metadata)}
        return [Evidence(source_type="webhook", source_name=self.source_name, source_id=self.source_id, timestamp=timestamp, event=event, raw_evidence=raw_evidence, metadata={str(key): str(value) for key, value in metadata.items()})]
