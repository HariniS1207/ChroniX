import re
from difflib import SequenceMatcher
from datetime import datetime

from app.models.incident import Evidence, Event, IncidentAnalysis, Relationship

INFERENCE_WORDS = re.compile(r"\b(suspect|suspected|seems? to be|may have|might|possibly|believe|appears|could be|likely)\b", re.I)
CONFLICT_WORDS = re.compile(r"\b(normal|healthy|no issue|not affected|unaffected)\b", re.I)
CAUSE_WORDS = re.compile(r"\b(cause|caused by|root cause|failure)\b", re.I)
CAUSAL_ASSERTION_WORDS = re.compile(r"\b(?:caused|triggered|led to|resulted in|because of|due to)\b", re.I)
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
    # Preserve a causal assertion as a separate, traceable evidence item; it
    # must not be merged into a similar observation such as a pool metric.
    left_asserts_cause = bool(CAUSAL_ASSERTION_WORDS.search(f"{left.event} {left.raw_evidence}"))
    right_asserts_cause = bool(CAUSAL_ASSERTION_WORDS.search(f"{right.event} {right.raw_evidence}"))
    if left_asserts_cause != right_asserts_cause:
        return False
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


def build_deterministic_relationships(events: list[Event]) -> list[Relationship]:
    relationships: list[Relationship] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    def add_rel(source_id: str, target_id: str, rel_type: str, confidence: float, basis: str, status: str = "deterministic"):
        if not source_id or not target_id or source_id == target_id:
            return
        pair = (source_id, target_id, rel_type)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            relationships.append(
                Relationship(
                    source_evidence_id=source_id,
                    target_evidence_id=target_id,
                    relationship_type=rel_type,
                    confidence=round(confidence, 2),
                    basis=basis,
                    status=status,
                )
            )

    # 1. Temporal sequence (PRECEDED)
    dated_events = [e for e in events if e.timestamp is not None]
    for i in range(len(dated_events) - 1):
        e1, e2 = dated_events[i], dated_events[i + 1]
        t1 = e1.timestamp.strftime("%H:%M:%S") if e1.timestamp else ""
        t2 = e2.timestamp.strftime("%H:%M:%S") if e2.timestamp else ""
        add_rel(
            e1.source_id,
            e2.source_id,
            "PRECEDED",
            1.0,
            f"Chronological sequence: '{e1.event}' at {t1} preceded '{e2.event}' at {t2}",
        )

    # 2. Correlated signals & Shared operational entities (CORRELATED_WITH)
    for i, e1 in enumerate(events):
        kw1 = _keywords(e1)
        for j in range(i + 1, len(events)):
            e2 = events[j]
            kw2 = _keywords(e2)
            shared = kw1 & kw2
            important_tokens = shared & {"database", "payment", "api", "timeout", "service", "error", "connection", "restart", "metric", "pool", "deploy"}
            if important_tokens:
                confidence = min(0.95, 0.6 + 0.1 * len(important_tokens))
                add_rel(
                    e1.source_id,
                    e2.source_id,
                    "CORRELATED_WITH",
                    confidence,
                    f"Correlated operational signals: {', '.join(sorted(important_tokens))}",
                )

    # 3. Conflicts (CONFLICTS_WITH)
    for inference in events:
        if inference.classification != "INFERENCE":
            continue
        inf_words = _keywords(inference)
        if not (inf_words & {"database", "db", "service", "payment"}):
            continue
        for fact in events:
            if fact.classification != "FACT":
                continue
            fact_words = _keywords(fact)
            if not (fact_words & inf_words):
                continue
            suggests_failure = bool(inf_words & {"fail", "error", "degrade", "suspect"})
            reports_health = bool(fact_words & {"normal", "healthy", "return", "recovery"}) and bool(fact_words & {"database", "cpu", "metric", "connection"})
            if suggests_failure and reports_health:
                add_rel(
                    inference.source_id,
                    fact.source_id,
                    "CONFLICTS_WITH",
                    0.85,
                    f"Conflicting status between '{inference.event}' and '{fact.event}'",
                )

    # 4. Explicit causal/contributing remediation (CONTRIBUTED_TO / CAUSED_BY)
    for e in events:
        txt = e.event.lower()
        if "restart" in txt:
            for other in events:
                if other.source_id != e.source_id and ("timeout" in other.event.lower() or "error" in other.event.lower()):
                    if other.timestamp and e.timestamp and other.timestamp < e.timestamp:
                        add_rel(
                            e.source_id,
                            other.source_id,
                            "CONTRIBUTED_TO",
                            0.75,
                            f"Remediation action: '{e.event}' addressed prior degradation '{other.event}'",
                        )

    # 5. Semantic similarity correlation via local semantic engine
    try:
        from app.services.semantic_service import semantic_correlator

        semantic_rels = semantic_correlator.find_semantic_correlations(events)
        for rel in semantic_rels:
            add_rel(
                rel.source_evidence_id,
                rel.target_evidence_id,
                rel.relationship_type,
                rel.confidence,
                rel.basis,
                rel.status,
            )
    except Exception:
        pass

    return relationships


def _evidence_text(event: Event) -> str:
    return f"{event.event}\n{event.raw_evidence}".lower()


def _is_deployment(event: Event) -> bool:
    return bool(re.search(r"\b(?:deploy(?:ment|ed|ing)?|rollout)\b", _evidence_text(event)))


def _is_pool_exhaustion(event: Event) -> bool:
    text = _evidence_text(event)
    if re.search(r"\b(?:not|never|no|without)\b.{0,30}\b(?:exhaust\w*|saturat\w*)\b", text):
        return False
    if "pool" in text and re.search(r"\b(?:normal|healthy|within limits|not exhausted|no exhaustion)\b", text):
        return False
    return bool(
        re.search(r"\b(?:connection\s+)?pool\b.{0,45}\b(?:exhaust(?:ed|ion)?|saturat(?:ed|ion)?|at capacity|full)\b", text)
        or re.search(r"\b(?:exhaust(?:ed|ion)?|saturat(?:ed|ion)?)\b.{0,45}\b(?:connection\s+)?pool\b", text)
    )


def _is_database_error(event: Event) -> bool:
    text = _evidence_text(event)
    if re.search(r"\b(?:no|not|never|without)\b.{0,30}\b(?:error|timeout|fail\w*|unavailable)\b", text):
        return False
    return bool(re.search(r"\b(?:database|db)\b", text) and re.search(r"\b(?:error|timeout|fail(?:ure|ed)?|unavailable)\b", text))


def _is_api_error(event: Event) -> bool:
    text = _evidence_text(event)
    if re.search(r"\b(?:no|not|never|without)\b.{0,30}\b(?:error|failure|fail\w*|degrad\w*)\b", text):
        return False
    has_api = bool(re.search(r"\b(?:api|payment|http\s*5\d\d)\b", text))
    has_error = bool(re.search(r"\b(?:error|errors|failure|failed|degrad\w*|5\d\d)\b", text))
    return has_api and has_error


def _in_time_order(events: list[Event]) -> bool:
    return all(
        left.timestamp is not None and right.timestamp is not None and left.timestamp < right.timestamp
        for left, right in zip(events, events[1:])
    )


def _explicit_causal_statement(event: Event) -> bool:
    text = _evidence_text(event)
    direct_cause = re.search(r"\b(?:caused|triggered|led to|resulted in|introduced)\b", text)
    mentions_deployment = _is_deployment(event)
    mentions_pool = _is_pool_exhaustion(event)
    tentative = INFERENCE_WORDS.search(text)
    return bool(direct_cause and mentions_deployment and mentions_pool and not tentative and event.classification == "FACT")


def _contradicts_causal_chain(event: Event) -> bool:
    text = _evidence_text(event)
    denies_impact = re.search(
        r"\b(?:did not|didn't|does not|doesn't|never|no evidence (?:that|of)|unaffected by)\b.{0,100}"
        r"\b(?:deploy\w*|rollout|cause\w*|impact\w*|affect\w*|exhaust\w*|saturat\w*)\b",
        text,
    )
    normal_pool = _is_pool_exhaustion(event) or "pool" in text
    normal_pool = normal_pool and bool(re.search(r"\b(?:normal|healthy|within limits|not exhausted|no exhaustion)\b", text))
    healthy_database = bool(re.search(r"\b(?:database|db)\b", text)) and bool(
        re.search(r"\b(?:normal|healthy|within limits|no errors|no failure)\b", text)
    )
    return bool(denies_impact or normal_pool or healthy_database)


def _root_cause_assessment(events: list[Event]) -> dict[str, object]:
    facts = [event for event in events if event.classification == "FACT"]
    deployments = [event for event in facts if _is_deployment(event)]
    pool_events = [event for event in facts if _is_pool_exhaustion(event)]
    database_errors = [event for event in facts if _is_database_error(event)]
    api_errors = [event for event in facts if _is_api_error(event)]

    # A candidate requires four separate, dated observations in causal order.
    # Ordering supports a hypothesis, but never confirms causation by itself.
    probable_candidates: list[list[Event]] = []
    confirmed_candidates: list[list[Event]] = []
    for deployment in deployments:
        for pool_event in pool_events:
            for database_error in database_errors:
                for api_error in api_errors:
                    chain = [deployment, pool_event, database_error, api_error]
                    if len({item.source_id for item in chain}) < 4 or not _in_time_order(chain):
                        continue

                    contradicted = any(
                        _contradicts_causal_chain(event)
                        and (event.timestamp is None or api_error.timestamp is None or event.timestamp <= api_error.timestamp)
                        for event in facts
                        if event.source_id not in {item.source_id for item in chain}
                    )
                    if contradicted:
                        continue

                    direct_claims = [
                        event for event in facts
                        if event.source_id not in {item.source_id for item in chain}
                        and _explicit_causal_statement(event)
                    ]
                    if direct_claims:
                        claim = direct_claims[0]
                        confirmed_candidates.append([claim, *chain])
                    else:
                        probable_candidates.append(chain)

    if confirmed_candidates:
        supporting = confirmed_candidates[0]
        ids = list(dict.fromkeys(item.source_id for item in supporting))
        return {
            "status": "CONFIRMED",
            "evidence_ids": ids,
            "confidence": len(ids) / 5,
            "basis": "Evidence coverage: 5/5 checks (100%). An explicit deployment-to-pool causal statement is corroborated by separate deployment, pool, database-error, and API-error evidence. Coverage is checklist-based, not a statistical probability.",
        }
    if probable_candidates:
        ids = list(dict.fromkeys(item.source_id for item in probable_candidates[0]))
        return {
            "status": "PROBABLE",
            "evidence_ids": ids,
            "confidence": len(ids) / 5,
            "basis": "Evidence coverage: 4/5 checks (80%). Deployment, pool exhaustion, database errors, and API errors appear in independent chronological evidence. Direct deployment-impact evidence is missing. Coverage is checklist-based, not a statistical probability.",
        }

    return {
        "status": "NOT CONFIRMED",
        "evidence_ids": [],
        "confidence": None,
        "basis": "Available evidence is insufficient or contradictory to establish a causal chain.",
    }



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
    assessment = _root_cause_assessment(events)
    unknowns = []
    if assessment["status"] == "NOT CONFIRMED":
        unknowns.append("Causality cannot be established from the available evidence.")
    elif assessment["status"] == "PROBABLE":
        unknowns.append("Direct evidence of deployment impact is still missing.")
    database_issue = any("database" in event.event.lower() or "db " in event.event.lower() for event in events)
    if assessment["status"] == "CONFIRMED":
        missing = []
    elif assessment["status"] == "PROBABLE":
        missing = ["Direct deployment impact/error record"]
    else:
        missing = ["Database query/error logs", "Connection pool metrics", "Deployment impact analysis"] if database_issue else ["A verified root-cause signal or recovery validation data."]
    first = events[0].timestamp.strftime("%H:%M") if events and events[0].timestamp else "the available evidence"
    summary = f"Evidence reconstructed {len(events)} event(s), beginning at {first}. "
    if assessment["status"] == "CONFIRMED":
        summary += "An explicit causal statement is corroborated by independent deployment, pool, database-error, and API-error evidence."
    elif assessment["status"] == "PROBABLE":
        summary += "The ordered deployment, pool-exhaustion, database-error, and API-error evidence supports a probable database-related cause, but direct deployment-impact evidence is missing."
    else:
        summary += "The timeline shows observable system changes and operational responses, but the available sources do not prove a single root cause."
    title = "Payment API Incident" if any("payment" in event.event.lower() for event in events) else "Reconstructed Incident"
    relationships = build_deterministic_relationships(events)
    return IncidentAnalysis(
        incident_title=title,
        summary=summary,
        root_cause_status=assessment["status"],
        root_cause_evidence_ids=assessment["evidence_ids"],
        root_cause_confidence=assessment["confidence"],
        root_cause_basis=assessment["basis"],
        timeline=events,
        facts=facts,
        inferences=inferences,
        conflicts=conflicts,
        unknowns=unknowns,
        missing_evidence=missing,
        file_errors=file_errors,
        relationships=relationships,
    )

