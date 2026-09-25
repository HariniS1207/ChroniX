"""Offline, deterministic semantic matching for common operations language."""

import os
import re
from typing import Literal

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models.incident import Event, Relationship

# Canonical concepts deliberately stay narrow: a shared generic word such as
# "service" or "error" alone should never create a graph edge.
_ALIASES = {
    "db": "database",
    "datastore": "database",
    "conn": "connection",
    "connections": "connection",
    "pool": "connection_pool",
    "pools": "connection_pool",
    "timeout": "timeout",
    "timeouts": "timeout",
    "latency": "timeout",
    "slow": "timeout",
    "504": "timeout",
    "depleted": "exhausted",
    "exhaustion": "exhausted",
    "failure": "failure",
    "failed": "failure",
    "failing": "failure",
    "errors": "error",
    "err": "error",
    "restarted": "restart",
    "restarting": "restart",
    "recovery": "recovery",
    "recovered": "recovery",
    "deployment": "release",
    "deployed": "release",
    "deploy": "release",
    "degraded": "degradation",
    "degrade": "degradation",
}
_STOP_WORDS = {"a", "an", "and", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "was", "with"}
_WEIGHTS = {"database": 2.5, "connection": 2.0, "connection_pool": 2.5, "timeout": 2.0, "response_delay": 2.0, "failure": 1.5, "error": 1.25, "restart": 1.5, "recovery": 1.5, "release": 1.5, "degradation": 1.5, "exhausted": 2.0, "availability_fault": 1.5, "remediation": 1.5}


def _features(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    features = {_ALIASES.get(word, word) for word in words if word not in _STOP_WORDS and len(word) > 1}
    # "connection pool" and its common abbreviation are the same concept.
    if "connection" in features or "pool" in words:
        features.add("connection_pool")
    if "database" in features and ("connection" in features or "connection_pool" in features):
        features.add("database_connection")
    if features & {"failure", "error"}:
        features.add("availability_fault")
    if "timeout" in features:
        features.add("response_delay")
    if features & {"restart", "recovery"}:
        features.add("remediation")
    return features


def _similarity(left: str, right: str) -> float:
    a, b = _features(left), _features(right)
    if not a or not b:
        return 0.0
    shared = a & b
    # Generic text overlap (for example, "service") is not operational
    # evidence of a relationship by itself.
    if not shared & _WEIGHTS.keys():
        return 0.0
    weighted_union = sum(_WEIGHTS.get(item, 1.0) for item in a | b)
    weighted_shared = sum(_WEIGHTS.get(item, 1.0) for item in shared)
    domain_score = weighted_shared / weighted_union
    try:
        matrix = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform([left.lower(), right.lower()])
        lexical_score = float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
    except ValueError:
        lexical_score = 0.0
    # Domain overlap is useful across different phrasing; lexical overlap keeps
    # the score precise when events share specific wording.
    return max(domain_score, lexical_score)


class SemanticCorrelator:
    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = float(os.getenv("CHRONIX_SEMANTIC_THRESHOLD", "0.50")) if threshold is None else threshold
        self._method: Literal["domain_tfidf"] = "domain_tfidf"

    @property
    def method_name(self) -> str:
        return self._method

    def compute_similarity(self, text1: str, text2: str) -> float:
        if not text1.strip() or not text2.strip():
            return 0.0
        return _similarity(text1, text2)

    def compute_pairwise_similarities(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), len(texts)), dtype=float)
        for i, left in enumerate(texts):
            matrix[i, i] = 1.0
            for j in range(i + 1, len(texts)):
                matrix[i, j] = matrix[j, i] = _similarity(left, texts[j])
        return matrix

    def find_semantic_correlations(self, events: list[Event]) -> list[Relationship]:
        relationships: list[Relationship] = []
        for index, first in enumerate(events):
            for second in events[index + 1:]:
                if first.source_id == second.source_id:
                    continue
                score = self.compute_similarity(
                    f"{first.event} {first.raw_evidence}", f"{second.event} {second.raw_evidence}"
                )
                if score < self.threshold:
                    continue
                relationships.append(Relationship(
                    source_evidence_id=first.source_id,
                    target_evidence_id=second.source_id,
                    relationship_type="CORRELATED_WITH",
                    confidence=round(min(0.95, max(0.60, score)), 3),
                    basis=(f"Semantic correlation ({score * 100:.1f}%) via {self._method}: "
                           f"shared operational concepts between '{first.event}' and '{second.event}'"),
                    status="deterministic",
                ))
        return relationships


semantic_correlator = SemanticCorrelator()
