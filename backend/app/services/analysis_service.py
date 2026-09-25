import re
from difflib import SequenceMatcher
from datetime import datetime

from app.models.incident import Evidence, Event, IncidentAnalysis

INFERENCE_WORDS = re.compile(r"\b(suspect|suspected|seems? to be|may have|might|possibly|believe|appears|could be|likely)\b", re.I)
CONFLICT_WORDS = re.compile(r"\b(normal|healthy|no issue|not affected|unaffected)\b", re.I)
CAUSE_WORDS = re.compile(r"\b(cause|caused by|root cause|failure)\b", re.I)
STOP_WORDS = {"about", "after", "appears", "around", "been", "from", "have", "into", "that", "the", "this", "with", "were"}
OPPOSITE_WORDS = (({"increase"}, {"decrease"}), ({"fail"}, {"normal"}), ({"degrade"}, {"healthy"}), ({"error"}, {"normal"}))


def _normalized_words(text: str) -> set[str]:
    replacements = {
        "increased": "increase", "increasing": "increase", "decreased": "decrease", "decreasing": "decrease",
        "restarted": "restart", "restarting": "restart", "failure": "fail", "failing": "fail",
        "errors": "error", "metrics": "metric", "returned": "return", "detected": "detect",
        "db": "database",
    }
    words = re.findall(r"[a-z0-9]{2,}", text.lower().replace("-", " "))
    return {replacements.get(word, word) for word in words if word not in STOP_WORDS}


def _keywords(event: Event) -> set[str]:
    return _normalized_words(event.event)


def _has_opposite_polarity(left: set[str], right: set[str]) -> bool:
    return any((left & first and right & second) or (left & second and right & first) for first, second in OPPOSITE_WORDS)


def _duplicate(left: Event, right: Event) -> bool:
    left_words = _keywords(left)
    right_words = _keywords(right)
    if _has_opposite_polarity(left_words, right_words):
        return False
    if not left_words or not right_words:
        return False
    shared = len(left_words & right_words)
    overlap = shared / min(len(left_words), len(right_words))
    similarity = SequenceMatcher(None, " ".join(sorted(left_words)), " ".join(sorted(right_words))).ratio()
    shared_words = left_words & right_words
    return (shared >= 3 and overlap >= 0.6) or {"restart", "service"}.issubset(shared_words) or similarity >= 0.78


def deduplicate(events: list[Event]) -> list[Event]:
    merged: list[Event] = []
    for event in events:
        if not event.sources:
            event.sources = [event.source_name]
        if not event.supporting_evidence:
            event.supporting_evidence = [event.raw_evidence]
        match = next((candidate for candidate in merged if _duplicate(candidate, event)), None)
        if match is None:
            merged.append(event)
            continue
        for source in event.sources:
            if source not in match.sources:
                match.sources.append(source)
        for raw_evidence in event.supporting_evidence:
            if raw_evidence not in match.supporting_evidence:
                match.supporting_evidence.append(raw_evidence)
        match.raw_evidence = "\n".join(match.supporting_evidence)
        if match.timestamp is None or (event.timestamp is not None and event.timestamp < match.timestamp):
            match.timestamp = event.timestamp
    return merged


def correlate(events: list[Event]) -> list[Event]:
    for index, event in enumerate(events):
        event.order = index
        event.related_event_ids = [other_index for other_index, other in enumerate(events) if other_index != index and _keywords(event) & _keywords(other)]
    return events


def classify(events: list[Event]) -> list[Event]:
    for event in events:
        if INFERENCE_WORDS.search(event.event) or INFERENCE_WORDS.search(event.evidence):
            event.classification = "INFERENCE"
        else:
            event.classification = "FACT"
    return events


def _conflicts(events: list[Event]) -> list[str]:
    relationships = []
    for inference in events:
        if inference.classification != "INFERENCE":
            continue
        inference_words = _keywords(inference)
        if not (inference_words & {"database", "db", "service", "payment"}):
            continue
        for fact in events:
            fact_words = _keywords(fact)
            if fact.classification != "FACT" or not (fact_words & inference_words):
                continue
            suggests_failure = bool(inference_words & {"fail", "error", "degrade", "suspect"})
            reports_health = bool(fact_words & {"normal", "healthy", "return", "recovery"}) and bool(fact_words & {"database", "cpu", "metric", "connection"})
            if suggests_failure and reports_health:
                relationships.append(
                    f"Evidence A ({', '.join(inference.sources)}): {inference.event}. "
                    f"Evidence B ({', '.join(fact.sources)}): {fact.event}. Status: UNRESOLVED."
                )
    return relationships


def analyze(evidence: list[Evidence], file_errors: list[str]) -> IncidentAnalysis:
    events = [Event.model_validate(item.model_dump()) for item in evidence]
    events = deduplicate(events)
    dated = [event for event in events if event.timestamp is not None]
    undated = [event for event in events if event.timestamp is None]
    dated.sort(key=lambda event: event.timestamp or datetime.max)
    events = dated + undated
    events = classify(correlate(events))
    for index, event in enumerate(events):
        event.order = index

    facts = [event.event for event in events if event.classification == "FACT"]
    inferences = [event.event for event in events if event.classification == "INFERENCE"]
    conflicts = _conflicts(events)
    unknowns = ["Confirmed root cause cannot be established from the uploaded evidence."]
    database_issue = any("database" in event.event.lower() or "db " in event.event.lower() for event in events)
    missing = ["Database query/error logs", "Connection pool metrics", "Deployment impact analysis"] if database_issue else ["A verified root-cause signal or recovery validation data."]
    first = events[0].timestamp.strftime("%H:%M") if events and events[0].timestamp else "the available evidence"
    summary = f"Evidence reconstructed {len(events)} event(s), beginning at {first}. The timeline shows observable system changes and operational responses, but the available sources do not prove a single root cause."
    title = "Payment API Incident" if any("payment" in event.event.lower() for event in events) else "Reconstructed Incident"
    return IncidentAnalysis(incident_title=title, summary=summary, root_cause_status="NOT CONFIRMED", timeline=events, facts=facts, inferences=inferences, conflicts=conflicts, unknowns=unknowns, missing_evidence=missing, file_errors=file_errors)
