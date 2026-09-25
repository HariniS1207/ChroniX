from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    start_time: datetime | None
    end_time: datetime | None
    root_cause_status: str
    revision: int