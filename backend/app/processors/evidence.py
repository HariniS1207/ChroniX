import csv
import hashlib
import io
import json
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
    text = data.decode("utf-8-sig")
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
            metadata = {"format": "csv"}
            metadata.update({key: value for key, value in values.items() if key not in {"timestamp", "time", "datetime", "date", "event", "message", "description", "log", "text"} and value})
            events.append(Evidence(source_type="file", source_name=source, source_id=source, timestamp=parse_timestamp(stamp) or timestamp_from_text(message), event=message, raw_evidence=evidence, metadata=metadata))
    return events


def extract_lines(data: bytes, source: str) -> list[Evidence]:
    text = data.decode("utf-8")
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
    if not text.strip():
        raise ValueError("PDF contains no extractable text; OCR is not enabled")
    return [Evidence(source_type="file", source_name=source, source_id=source, timestamp=timestamp_from_text(raw_statement), event=statement, raw_evidence=raw_statement, metadata={"format": "pdf"}) for raw_statement in _pdf_raw_statements(text) for statement in [_clean_statement(raw_statement)] if statement and len(statement.split()) >= 3 and not statement.endswith((":", ";")) and "..." not in statement]


def _json_events(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        canonical = {"timestamp", "time", "date", "datetime", "event", "message", "description", "text"}
        if any(key.lower() in canonical for key in value):
            return [value]
        for nested in value.values():
            events = _json_events(nested)
            if events:
                return events
    return []


def extract_json(data: bytes, source: str) -> list[Evidence]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON could not be parsed: {exc}") from exc
    events = []
    for record in _json_events(payload):
        values = {str(key): value for key, value in record.items()}
        lowered = {key.lower(): value for key, value in values.items()}
        timestamp_value = next((lowered[key] for key in ("timestamp", "time", "datetime", "date") if lowered.get(key)), None)
        message = next((str(lowered[key]) for key in ("event", "message", "description", "text") if lowered.get(key)), None)
        if not message:
            continue
        metadata = {key: json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value for key, value in values.items() if key.lower() not in {"timestamp", "time", "datetime", "date", "event", "message", "description", "text"}}
        metadata["format"] = "json"
        raw = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        events.append(Evidence(source_type="file", source_name=source, source_id=source, timestamp=parse_timestamp(str(timestamp_value)) if timestamp_value else timestamp_from_text(message), event=message, raw_evidence=raw, metadata=metadata))
    if not events:
        raise ValueError("JSON contains no recognizable event records")
    return events


def extract_events(filename: str, data: bytes) -> list[Evidence]:
    suffix = Path(filename).suffix.lower()
    if not data.strip():
        raise ValueError("file is empty")
    if suffix == ".csv":
        return extract_csv(data, filename)
    if suffix in {".txt", ".log"}:
        return extract_lines(data, filename)
    if suffix == ".json":
        return extract_json(data, filename)
    if suffix == ".pdf":
        return extract_pdf(data, filename)
    raise ValueError("supported types are TXT, LOG, CSV, JSON, and PDF")
