from app.connectors.base import Connector
from app.models.incident import Evidence
from app.processors.evidence import extract_events


class FileConnector(Connector):
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.data = data

    def collect(self) -> list[Evidence]:
        return extract_events(self.filename, self.data)
