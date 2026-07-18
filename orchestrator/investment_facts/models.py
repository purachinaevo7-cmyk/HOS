from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class DocumentCandidate:
    url: str | None
    canonical_url: str | None = None
    title: str | None = None
    document_type: str | None = None
    published_at: str | None = None
    fiscal_period: str | None = None
    language: str | None = None
    mime_type: str | None = None
    official_domain_verified: bool = False
    discovery_source_url: str | None = None
    discovery_method: str | None = None
    candidate_score: float = 0.0
    def to_dict(self)->dict[str,Any]: return asdict(self)

@dataclass
class Fact:
    value: Any
    unit: str | None = None
    period: str | None = None
    scope: str | None = None
    method: str = 'reported'
    label_original: str | None = None
    source_ref: str | None = None
    document_page: int | None = None
    confidence: str = 'low'
    validation_status: str = 'PARTIAL'
    def to_dict(self)->dict[str,Any]: return asdict(self)
