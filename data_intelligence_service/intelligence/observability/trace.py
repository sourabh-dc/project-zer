"""
Per-query trace dataclass — explainability for every intelligence request.

WHY a separate trace object?
  We want to return structured metadata with every API response so callers
  can see: which engine answered, how confident the routing was, how many
  LLM retries happened, how long each step took, and how many tokens were used.
  This is the explainability layer — no black boxes.

The trace is built incrementally as the agent runs each node, then returned
in the API response alongside the answer.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StepTrace:
    """Trace for one execution step (one SQL/graph/vector query)."""
    step_index: int
    engine: str                  # sql | graph | vector
    description: str
    rows_returned: int
    latency_ms: float
    error: Optional[str] = None


@dataclass
class QueryTrace:
    """
    Full trace for one /intelligence/query call.

    Returned in the API response under the 'trace' key.
    Used by Langfuse/OTel for structured span metadata.
    """
    # Routing
    engine: str = "unknown"          # sql | graph | vector | hybrid | unknown
    tier: int = 3                    # 1=regex, 2=scoring, 3=llm
    confidence: float = 0.0

    # Safety
    guardrail_passed: bool = True
    guardrail_tier: int = 0          # 1=regex blocked, 2=llm blocked, 0=passed

    # Planning
    plan_attempts: int = 0           # 1 = first try, 2 = needed correction
    schema_errors: List[str] = field(default_factory=list)

    # Execution
    steps: List[StepTrace] = field(default_factory=list)
    total_rows: int = 0

    # Timing (set at start/end of run_agent)
    start_ts: float = field(default_factory=time.monotonic)
    latency_ms: float = 0.0

    # Token usage (populated from LLM response metadata if available)
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0

    def finish(self) -> "QueryTrace":
        """Call at end of agent run to compute total latency."""
        self.latency_ms = round((time.monotonic() - self.start_ts) * 1000, 1)
        self.total_rows = sum(s.rows_returned for s in self.steps)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict for API response."""
        return {
            "engine":          self.engine,
            "tier":            self.tier,
            "confidence":      round(self.confidence, 3),
            "guardrail_passed": self.guardrail_passed,
            "guardrail_tier":  self.guardrail_tier,
            "plan_attempts":   self.plan_attempts,
            "schema_errors":   self.schema_errors,
            "steps": [
                {
                    "step":        s.step_index,
                    "engine":      s.engine,
                    "description": s.description,
                    "rows":        s.rows_returned,
                    "latency_ms":  round(s.latency_ms, 1),
                    **({"error": s.error} if s.error else {}),
                }
                for s in self.steps
            ],
            "total_rows":          self.total_rows,
            "latency_ms":          self.latency_ms,
            "tokens": {
                "prompt":     self.tokens_prompt,
                "completion": self.tokens_completion,
                "total":      self.tokens_total,
            },
        }
