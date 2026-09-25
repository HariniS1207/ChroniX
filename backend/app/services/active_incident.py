from threading import Lock

from app.models.incident import Evidence, IncidentAnalysis


class ActiveIncidentStore:
    def __init__(self) -> None:
        self._evidence: dict[str, Evidence] = {}
        self._analysis: IncidentAnalysis | None = None
        self._lock = Lock()

    def add(self, evidence: Evidence) -> bool:
        with self._lock:
            if evidence.source_id in self._evidence:
                return False
            self._evidence[evidence.source_id] = evidence
            return True

    def snapshot(self) -> list[Evidence]:
        with self._lock:
            return list(self._evidence.values())

    def clear(self) -> None:
        with self._lock:
            self._evidence.clear()
            self._analysis = None

    def refresh(self) -> IncidentAnalysis:
        from app.services.analysis_service import analyze
        from app.services.llm_service import enrich_with_llm

        analysis = enrich_with_llm(analyze(self.snapshot(), []))
        with self._lock:
            self._analysis = analysis
        return analysis

    def latest_analysis(self) -> IncidentAnalysis | None:
        with self._lock:
            return self._analysis


active_incident = ActiveIncidentStore()
