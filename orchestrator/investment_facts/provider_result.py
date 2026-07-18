from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any

@dataclass
class SectionSelection:
    completeness_score: float = 0.0
    validation_score: float = 0.0
    source_quality_score: float = 0.0
    freshness_score: float = 0.0
    selected_provider: str | None = None
    attempted_providers: list[str] = field(default_factory=list)
    fallback_used: bool = False
    rejected_candidates: list[dict[str,Any]] = field(default_factory=list)
    selection_reason: str = ''
    def to_dict(self): return asdict(self)
