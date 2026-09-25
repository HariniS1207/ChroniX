import hashlib

from app.connectors.base import Connector
from app.models.incident import Evidence
from app.processors.evidence import extract_events


class FileConnector(Connector):
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.data = data

    def collect(self) -> list[Evidence]:
        events = extract_events(self.filename, self.data)
        if len(events) <= 1:
            return events
        content_hash = hashlib.sha256(self.data).hexdigest()[:16]
        for index, event in enumerate(events):
            event.source_id = f"{self.filename}:{content_hash}:{index}"
        return events
