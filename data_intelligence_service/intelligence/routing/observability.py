"""
Observability for the intelligence routing layer.

Emits one structured JSON audit line per query to the logger.
Fields are designed to be ingested by Azure Monitor / Application Insights
via log aggregation (e.g. Fluent Bit → Log Analytics Workspace).

Audit line prefix: [INTELLIGENCE_AUDIT]
"""
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List

from data_intelligence_service.core.logger import logger


@dataclass
class StepTrace:
    step_index: int
    engine: str
    description: str
    latency_ms: float
    row_count: int
    cache_hit: bool = False
    error: Optional[str] = None


@dataclass
class QueryTrace:
    question_hash: str          # SHA256[:12] of question — no PII in logs
    tenant_id: str
    has_user_id: bool
    routing_tier: int
    classified_engine: str
    routing_confidence: float
    plan_cache_hit: bool
    steps: List[StepTrace] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    total_latency_ms: float = 0.0
    llm_plan_latency_ms: float = 0.0
    llm_summarize_latency_ms: float = 0.0
    error: Optional[str] = None

    def emit(self):
        d = asdict(self)
        logger.info(f"[INTELLIGENCE_AUDIT] {json.dumps(d, default=str)}")


def now_ms() -> float:
    return time.monotonic() * 1000


def question_hash(question: str) -> str:
    import hashlib
    return hashlib.sha256(question.encode()).hexdigest()[:12]
