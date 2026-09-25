from collections.abc import Callable
from threading import Condition, Lock, Thread
from time import monotonic

from app.db.repositories import IncidentRepository
from app.models.incident import Evidence, IncidentAnalysis
from app.services.analysis_service import analyze

ENRICHMENT_DEBOUNCE_SECONDS = 3.0


class ActiveIncidentStore:
    def __init__(self, enrichment: Callable[[IncidentAnalysis], IncidentAnalysis] | None = None, repository: IncidentRepository | None = None) -> None:
        self._repository = repository or IncidentRepository()
        active = self._repository.get_active_incident()
        self._incident_id = active["incident_id"] if active else None
        self._evidence: dict[str, Evidence] = {}
        self._analysis: IncidentAnalysis | None = None
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._revision = active["revision"] if active else 0
        self._pending_revision: int | None = None
        self._last_event_at = 0.0
        self._enrichment = enrichment
        if self._incident_id:
            self._evidence = {item.source_id: item for item in self._repository.get_incident_evidence(self._incident_id)}
            latest = self._repository.get_latest_analysis(self._incident_id)
            if latest:
                self._revision, self._analysis = latest
                if self._analysis.llm_status in {"local_pending", "local_processing"}:
                    self._pending_revision = self._revision
                    self._last_event_at = monotonic()
        self._worker = Thread(target=self._enrichment_worker, name="chronix-llm-enrichment", daemon=True)
        self._worker.start()

    @staticmethod
    def _deterministic_analysis(events: list[Evidence]) -> IncidentAnalysis:
        return analyze(events, []).model_copy(update={"llm_status": "local_pending", "llm_enrichment": None})

    def add(self, evidence: Evidence) -> bool:
        with self._condition:
            if evidence.source_id in self._evidence:
                return False
            if self._incident_id is None:
                self._incident_id = self._repository.create_incident()
            if not self._repository.add_evidence(self._incident_id, evidence):
                return False
            self._evidence[evidence.source_id] = evidence
            self._revision += 1
            self._analysis = self._deterministic_analysis(self._repository.get_incident_evidence(self._incident_id))
            self._repository.update_evidence_classifications(self._incident_id, self._analysis)
            self._repository.save_analysis(self._incident_id, self._revision, self._analysis)
            self._pending_revision = self._revision
            self._last_event_at = monotonic()
            self._condition.notify()
            return True

    def add_to_historical_incident(self, incident_id: str, items: list[Evidence]) -> tuple[int, int]:
        with self._lock:
            incident = self._repository.get_incident(incident_id)
            if incident is None:
                raise KeyError(incident_id)
            created, duplicate_count = self._repository.add_evidence_batch(incident_id, items)
            if not created:
                return 0, duplicate_count
            evidence = self._repository.get_incident_evidence(incident_id)
            analysis = self._deterministic_analysis(evidence)
            revision = incident["revision"] + 1
            self._repository.update_evidence_classifications(incident_id, analysis)
            self._repository.save_analysis(incident_id, revision, analysis)
            Thread(target=self._enrich_persisted, args=(incident_id, revision, analysis), name="chronix-file-enrichment", daemon=True).start()
            return len(created), duplicate_count

    def _enrich_persisted(self, incident_id: str, revision: int, analysis: IncidentAnalysis) -> None:
        enrichment = self._enrichment
        if enrichment is None:
            from app.services.llm_service import enrich_with_llm

            enrichment = enrich_with_llm
        try:
            enriched = enrichment(analysis)
        except Exception:
            enriched = analysis.model_copy(update={"llm_status": "local_failed", "llm_enrichment": None})
        current = self._repository.get_incident(incident_id)
        if current and current["revision"] == revision:
            self._repository.save_analysis(incident_id, revision, enriched)

    def snapshot(self) -> list[Evidence]:
        with self._lock:
            return list(self._evidence.values())

    @property
    def incident_id(self) -> str | None:
        with self._lock:
            return self._incident_id

    def clear(self) -> None:
        with self._condition:
            self._evidence.clear()
            self._analysis = None
            if self._incident_id:
                self._repository.archive_incident(self._incident_id)
            self._incident_id = None
            self._revision = 0
            self._pending_revision = None
            self._condition.notify()

    def refresh(self) -> IncidentAnalysis:
        with self._condition:
            self._revision += 1
            self._analysis = self._deterministic_analysis(list(self._evidence.values()))
            self._pending_revision = self._revision
            self._last_event_at = monotonic()
            if self._incident_id:
                self._repository.update_evidence_classifications(self._incident_id, self._analysis)
                self._repository.save_analysis(self._incident_id, self._revision, self._analysis)
            self._condition.notify()
            return self._analysis

    def _enrichment_worker(self) -> None:
        while True:
            with self._condition:
                while self._pending_revision is None:
                    self._condition.wait()

                while self._pending_revision is not None:
                    remaining = self._last_event_at + ENRICHMENT_DEBOUNCE_SECONDS - monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(timeout=remaining)

                if self._pending_revision is None:
                    continue

                scheduled_revision = self._revision
                events = list(self._evidence.values())
                if not events:
                    self._pending_revision = None
                    continue
                analysis = self._deterministic_analysis(events)
                processing = analysis.model_copy(update={"llm_status": "local_processing", "llm_enrichment": None})
                self._analysis = processing

            enrichment = self._enrichment
            if enrichment is None:
                from app.services.llm_service import enrich_with_llm

                enrichment = enrich_with_llm
            try:
                enriched = enrichment(processing)
            except Exception:
                enriched = processing.model_copy(update={"llm_status": "local_failed", "llm_enrichment": None})

            with self._condition:
                if self._revision == scheduled_revision and self._analysis is processing:
                    self._analysis = enriched
                    self._pending_revision = None
                    if self._incident_id:
                        self._repository.save_analysis(self._incident_id, scheduled_revision, enriched)

    def latest_analysis(self) -> IncidentAnalysis | None:
        with self._lock:
            return self._analysis


active_incident = ActiveIncidentStore()
