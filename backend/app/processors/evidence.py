import csv
import io
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from app.models.incident import Evidence

TIMESTAMP_RE = re.compile(
    r"(?P<stamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?|\b\d{2}:\d{2}(?::\d{2})?)"
)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt.startswith("%H"):
                return datetime(2026, 9, 25, parsed.hour, parsed.minute, parsed.second)
            return parsed
        except ValueError:
            continue
    return None


def timestamp_from_text(text: str) -> datetime | None:
    match = TIMESTAMP_RE.search(text)
    return parse_timestamp(match.group("stamp")) if match else None


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t\r\n-|")


def _clean_statement(statement: str) -> str:
    cleaned = normalize_text(TIMESTAMP_RE.sub(" ", statement))
    cleaned = re.sub(r"^(?:at|by|around|on)\s*[,;:]?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    return normalize_text(cleaned).strip(" []")


def _pdf_raw_statements(text: str) -> list[str]:
    text = "\n".join(normalize_text(line) for line in text.splitlines() if normalize_text(line))
    if not text:
        return []
    parts = re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z\[])", text)
    statements = []
    for part in parts:
        statement = _clean_statement(part)
        lowered = statement.lower()
        if lowered.startswith("chronix incident report") or lowered.startswith("incident window") or lowered.startswith("root cause remains"):
            continue
        if len(statement.split()) >= 3 and not statement.endswith((":", ";")) and "..." not in statement:
            statements.append(part)
    return statements


def extract_csv(data: bytes, source: str) -> list[Evidence]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    events = []
    for row in reader:
        values = {str(k).lower().strip(): (v or "").strip() for k, v in row.items()}
        stamp = next((values[k] for k in ("timestamp", "time", "datetime", "date") if values.get(k)), None)
        message = next((values[k] for k in ("event", "message", "description", "log", "text") if values.get(k)), None)
        message = message or " | ".join(v for v in values.values() if v)
        if message:
            evidence = ", ".join(f"{key}: {value}" for key, value in values.items() if value)
            events.append(Evidence(source_type="file", source_name=source, source_id=source, timestamp=parse_timestamp(stamp) or timestamp_from_text(message), event=message, raw_evidence=evidence, metadata={"format": "csv"}))
    return events


def extract_lines(data: bytes, source: str) -> list[Evidence]:
    text = data.decode("utf-8", errors="replace")
    return [Evidence(source_type="file", source_name=source, source_id=source, timestamp=timestamp_from_text(line), event=_clean_statement(line), raw_evidence=normalize_text(line), metadata={"format": "text"}) for line in text.splitlines() if normalize_text(line)]


def extract_pdf(data: bytes, source: str) -> list[Evidence]:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        # Keep text-bearing uploads useful even when a PDF is malformed or parser-incompatible.
        fallback = data.decode("utf-8", errors="replace")
        if not fallback.strip():
            raise ValueError(f"PDF could not be read: {exc}") from exc
        text = fallback
    return [Evidence(source_type="file", source_name=source, source_id=source, timestamp=timestamp_from_text(raw_statement), event=statement, raw_evidence=raw_statement, metadata={"format": "pdf"}) for raw_statement in _pdf_raw_statements(text) for statement in [_clean_statement(raw_statement)] if statement and len(statement.split()) >= 3 and not statement.endswith((":", ";")) and "..." not in statement]


def extract_events(filename: str, data: bytes) -> list[Evidence]:
    suffix = Path(filename).suffix.lower()
    if not data.strip():
        raise ValueError("file is empty")
    if suffix == ".csv":
        return extract_csv(data, filename)
    if suffix in {".txt", ".log"}:
        return extract_lines(data, filename)
    if suffix == ".pdf":
        return extract_pdf(data, filename)
    raise ValueError("supported types are CSV, TXT, LOG, and PDF")
