import json
import uuid
from datetime import datetime, timezone

from app.db.database import connect, initialize_database
from app.models.incident import Evidence, IncidentAnalysis


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class IncidentRepository:
    def __init__(self) -> None:
        initialize_database()

    def create_incident(self, title: str = "Reconstructed Incident") -> str:
        incident_id = str(uuid.uuid4())
        now = _now()
        with connect() as connection:
            connection.execute(
                "INSERT INTO incidents (incident_id, title, status, created_at, updated_at, root_cause_status, revision) VALUES (?, ?, 'active', ?, ?, 'NOT CONFIRMED', 0)",
                (incident_id, title, now, now),
            )
        return incident_id

    def get_incident(self, incident_id: str) -> dict | None:
        with connect() as connection:
            row = connection.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        return dict(row) if row else None

    def get_active_incident(self) -> dict | None:
        with connect() as connection:
            row = connection.execute("SELECT * FROM incidents WHERE status = 'active' ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def update_incident(self, incident_id: str, **fields: object) -> None:
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with connect() as connection:
            connection.execute(f"UPDATE incidents SET {assignments} WHERE incident_id = ?", (*fields.values(), incident_id))

    def list_incidents(self) -> list[dict]:
        with connect() as connection:
            rows = connection.execute(
                """SELECT i.*, COUNT(e.evidence_id) AS evidence_count,
                (SELECT a.llm_status FROM analyses a WHERE a.incident_id = i.incident_id ORDER BY a.revision DESC, a.analysis_id DESC LIMIT 1) AS llm_status
                FROM incidents i LEFT JOIN evidence e ON e.incident_id = i.incident_id
                GROUP BY i.incident_id ORDER BY i.created_at DESC"""
            ).fetchall()
        return [self._incident_list_item(dict(row)) for row in rows]

    @staticmethod
    def _incident_list_item(record: dict) -> dict:
        record["incident_title"] = record.pop("title")
        record["evidence_count"] = record.get("evidence_count", 0)
        record["llm_status"] = record.get("llm_status") or "unavailable"
        return record

    def get_incident_detail(self, incident_id: str) -> dict | None:
        incident = self.get_incident(incident_id)
        if incident is None:
            return None
        evidence = []
        with connect() as connection:
            rows = connection.execute("SELECT * FROM evidence WHERE incident_id = ? ORDER BY timestamp, rowid", (incident_id,)).fetchall()
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            item["evidence_id"] = item.pop("evidence_id")
            evidence.append(item)
        latest = self.get_latest_analysis(incident_id)
        analysis = latest[1].model_dump(mode="json") if latest else None
        relationships = self.get_relationships(incident_id)
        result = self._incident_list_item(incident)
        result.update({
            "evidence_count": len(evidence),
            "evidence": evidence,
            "timeline": analysis["timeline"] if analysis else [],
            "analysis": analysis,
            "relationships": relationships,
        })
        return result

    def add_evidence(self, incident_id: str, evidence: Evidence) -> bool:
        with connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO evidence
                (incident_id, evidence_id, source_type, source_name, source_id, timestamp, event, raw_evidence, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (incident_id, evidence.source_id, evidence.source_type, evidence.source_name, evidence.source_id, evidence.timestamp.isoformat() if evidence.timestamp else None, evidence.event, evidence.raw_evidence, json.dumps(evidence.metadata)),
            )
        return cursor.rowcount == 1

    def add_evidence_batch(self, incident_id: str, items: list[Evidence]) -> tuple[list[Evidence], int]:
        created = []
        with connect() as connection:
            for evidence in items:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO evidence
                    (incident_id, evidence_id, source_type, source_name, source_id, timestamp, event, raw_evidence, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (incident_id, evidence.source_id, evidence.source_type, evidence.source_name, evidence.source_id, evidence.timestamp.isoformat() if evidence.timestamp else None, evidence.event, evidence.raw_evidence, json.dumps(evidence.metadata)),
                )
                if cursor.rowcount == 1:
                    created.append(evidence)
        return created, len(items) - len(created)

    def get_evidence(self, incident_id: str, evidence_id: str) -> Evidence | None:
        with connect() as connection:
            row = connection.execute("SELECT * FROM evidence WHERE incident_id = ? AND evidence_id = ?", (incident_id, evidence_id)).fetchone()
        return self._evidence_from_row(row) if row else None

    def get_incident_evidence(self, incident_id: str) -> list[Evidence]:
        with connect() as connection:
            rows = connection.execute("SELECT * FROM evidence WHERE incident_id = ? ORDER BY timestamp, rowid", (incident_id,)).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    @staticmethod
    def _evidence_from_row(row) -> Evidence:
        return Evidence(source_type=row["source_type"], source_name=row["source_name"], source_id=row["source_id"], timestamp=_parse_datetime(row["timestamp"]), event=row["event"], raw_evidence=row["raw_evidence"], metadata=json.loads(row["metadata_json"]))

    def update_evidence_classifications(self, incident_id: str, analysis: IncidentAnalysis) -> None:
        with connect() as connection:
            for event in analysis.timeline:
                connection.execute("UPDATE evidence SET classification = ? WHERE incident_id = ? AND evidence_id = ?", (event.classification, incident_id, event.source_id))

    def save_relationship(self, incident_id: str, relationship: dict) -> str:
        relationship_id = relationship.get("relationship_id", str(uuid.uuid4()))
        with connect() as connection:
            connection.execute(
                "INSERT INTO relationships (relationship_id, incident_id, source_evidence_id, target_evidence_id, relationship_type, confidence, basis, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (relationship_id, incident_id, relationship["source_evidence_id"], relationship["target_evidence_id"], relationship["relationship_type"], relationship.get("confidence"), relationship.get("basis"), relationship.get("status")),
            )
        return relationship_id

    def get_relationships(self, incident_id: str) -> list[dict]:
        with connect() as connection:
            rows = connection.execute("SELECT * FROM relationships WHERE incident_id = ?", (incident_id,)).fetchall()
        return [dict(row) for row in rows]

    def save_analysis(self, incident_id: str, revision: int, analysis: IncidentAnalysis) -> None:
        data = analysis.model_dump(mode="json")
        enrichment = data.pop("llm_enrichment", None)
        llm_status = data.pop("llm_status", "unavailable")
        with connect() as connection:
            connection.execute("INSERT INTO analyses (incident_id, revision, deterministic_json, enrichment_json, llm_status, generated_at) VALUES (?, ?, ?, ?, ?, ?)", (incident_id, revision, json.dumps(data), json.dumps(enrichment) if enrichment is not None else None, llm_status, _now()))
            connection.execute("UPDATE incidents SET title = ?, updated_at = ?, start_time = ?, root_cause_status = ?, revision = ? WHERE incident_id = ?", (analysis.incident_title, _now(), analysis.timeline[0].timestamp.isoformat() if analysis.timeline and analysis.timeline[0].timestamp else None, analysis.root_cause_status, revision, incident_id))

    def get_latest_analysis(self, incident_id: str) -> tuple[int, IncidentAnalysis] | None:
        with connect() as connection:
            row = connection.execute("SELECT * FROM analyses WHERE incident_id = ? ORDER BY revision DESC, analysis_id DESC LIMIT 1", (incident_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row["deterministic_json"])
        data["llm_status"] = row["llm_status"]
        data["llm_enrichment"] = json.loads(row["enrichment_json"]) if row["enrichment_json"] else None
        return row["revision"], IncidentAnalysis.model_validate(data)

    def archive_incident(self, incident_id: str) -> None:
        self.update_incident(incident_id, status="reset", end_time=_now())