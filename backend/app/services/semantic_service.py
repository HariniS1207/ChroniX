import logging
import os
import re
from typing import Literal

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models.incident import Event, Relationship

logger = logging.getLogger(__name__)

# Domain synonym normalizations to enhance local operational similarity
DOMAIN_SYNONYMS = {
    r"\bdb\b": "database",
    r"\bconn\b": "connection",
    r"\berrs\b": "error",
    r"\berrors\b": "error",
    r"\btimeouts?\b": "timeout",
    r"\bexhausted\b": "depleted pool failure",
    r"\blatency\b": "slow response delay timeout",
    r"\bgateway timeout\b": "504 gateway timeout",
    r"\brestarted?\b": "restart recovery",
    r"\bdegraded?\b": "slow degradation fail",
}


def _expand_text(text: str) -> str:
    expanded = text.lower()
    for pattern, replacement in DOMAIN_SYNONYMS.items():
        expanded = re.sub(pattern, replacement, expanded)
    return expanded


class SemanticCorrelator:
    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = threshold or float(os.getenv("CHRONIX_SEMANTIC_THRESHOLD", "0.50"))
        self._st_model = None
        self._st_loaded = False
        self._method: Literal["sentence-transformers", "tfidf_ngram"] = "tfidf_ngram"

    def _load_sentence_transformers(self) -> None:
        if self._st_loaded:
            return
        self._st_loaded = True
        try:
            from sentence_transformers import SentenceTransformer

            model_name = os.getenv("CHRONIX_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            # Only load if model cache exists or local loading is fast
            self._st_model = SentenceTransformer(model_name)
            self._method = "sentence-transformers"
            logger.info("SentenceTransformer model %s loaded successfully", model_name)
        except Exception as exc:
            logger.info("SentenceTransformer unavailable (%s); using TF-IDF n-gram embeddings", exc)
            self._st_model = None
            self._method = "tfidf_ngram"

    @property
    def method_name(self) -> str:
        return self._method

    def compute_similarity(self, text1: str, text2: str) -> float:
        if not text1.strip() or not text2.strip():
            return 0.0
        exp1, exp2 = _expand_text(text1), _expand_text(text2)
        try:
            vec = TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True)
            matrix = vec.fit_transform([exp1, exp2])
            sim = cosine_similarity(matrix[0:1], matrix[1:2])[0][0]
            return float(sim)
        except Exception:
            return 0.0

    def compute_pairwise_similarities(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0))
        expanded = [_expand_text(t) for t in texts]
        try:
            vec = TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True)
            matrix = vec.fit_transform(expanded)
            return cosine_similarity(matrix)
        except Exception as exc:
            logger.warning("Pairwise similarity error: %s", exc)
            return np.zeros((len(texts), len(texts)))

    def find_semantic_correlations(self, events: list[Event]) -> list[Relationship]:
        if len(events) < 2:
            return []
        texts = [f"{e.event} {e.raw_evidence}" for e in events]
        sim_matrix = self.compute_pairwise_similarities(texts)
        relationships: list[Relationship] = []
        seen = set()

        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                score = float(sim_matrix[i, j])
                if score >= self.threshold:
                    e1, e2 = events[i], events[j]
                    if e1.source_id == e2.source_id:
                        continue
                    pair = (e1.source_id, e2.source_id)
                    if pair not in seen:
                        seen.add(pair)
                        confidence = min(0.95, round(max(score, 0.60), 3))
                        relationships.append(
                            Relationship(
                                source_evidence_id=e1.source_id,
                                target_evidence_id=e2.source_id,
                                relationship_type="CORRELATED_WITH",
                                confidence=confidence,
                                basis=f"Semantic correlation ({score * 100:.1f}%) via {self._method}: related operational semantics between '{e1.event}' and '{e2.event}'",
                                status="deterministic",
                            )
                        )
        return relationships


semantic_correlator = SemanticCorrelator()
