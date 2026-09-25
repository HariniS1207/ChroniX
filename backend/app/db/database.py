import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def database_path() -> str:
    configured = os.getenv("CHRONIX_DB_PATH", "./data/chronix.db")
    if configured == ":memory:":
        return configured
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                root_cause_status TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS evidence (
                incident_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_id TEXT NOT NULL,
                timestamp TEXT,
                event TEXT NOT NULL,
                raw_evidence TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                classification TEXT NOT NULL DEFAULT 'FACT',
                PRIMARY KEY (incident_id, evidence_id),
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );

            CREATE TABLE IF NOT EXISTS relationships (
                relationship_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                source_evidence_id TEXT NOT NULL,
                target_evidence_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                confidence REAL,
                basis TEXT,
                status TEXT,
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );

            CREATE TABLE IF NOT EXISTS analyses (
                analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                deterministic_json TEXT NOT NULL,
                enrichment_json TEXT,
                llm_status TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );

            CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
            CREATE INDEX IF NOT EXISTS idx_analyses_latest ON analyses(incident_id, revision, analysis_id);
            """
        )