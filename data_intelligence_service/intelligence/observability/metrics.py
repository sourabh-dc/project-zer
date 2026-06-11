"""
Prometheus metrics for the intelligence service.

WHY Prometheus?
  Prometheus metrics give us infrastructure-level visibility: request rates,
  latency distributions, error rates, and routing distribution — all in one
  place. If Grafana is already deployed in the infra, this is zero extra cost.
  The /metrics endpoint is scraped by Prometheus; Grafana reads from Prometheus.

WHY not just use LangSmith/Langfuse for metrics?
  Those tools are great for per-query traces and LLM debugging. But for
  aggregate metrics (p99 latency over the last hour, error rate trends,
  routing distribution over time), Prometheus + Grafana is the standard.
  Both layers complement each other.

USAGE:
  from data_intelligence_service.intelligence.observability.metrics import (
      record_query, record_guardrail_block, record_llm_tokens
  )

  record_query(engine="sql", tier=1, latency_ms=120, success=True)
  record_guardrail_block(category="prompt_injection")
  record_llm_tokens(operation="plan", prompt=500, completion=200)

SCRAPING:
  GET /metrics — returns Prometheus text format
  Set scrape_interval: 15s in Prometheus config.
"""
import time
from typing import Optional

try:
    from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

    # Use a single registry to avoid duplicate registration errors
    _REGISTRY = CollectorRegistry(auto_describe=True)

    # ── Query counters ──────────────────────────────────────────────────────────

    QUERIES_TOTAL = Counter(
        "zeroque_intelligence_queries_total",
        "Total queries processed by the intelligence agent",
        ["engine", "tier", "success"],
        registry=_REGISTRY,
    )

    GUARDRAIL_BLOCKS = Counter(
        "zeroque_intelligence_guardrail_blocks_total",
        "Queries blocked by guardrails",
        ["category", "tier"],
        registry=_REGISTRY,
    )

    PLAN_RETRIES = Counter(
        "zeroque_intelligence_plan_retries_total",
        "Number of LLM plan correction retries triggered by schema errors",
        registry=_REGISTRY,
    )

    # ── Latency histograms ──────────────────────────────────────────────────────

    QUERY_LATENCY = Histogram(
        "zeroque_intelligence_query_latency_ms",
        "End-to-end query latency in milliseconds",
        ["engine"],
        buckets=[50, 100, 250, 500, 1000, 2000, 5000, 10000],
        registry=_REGISTRY,
    )

    NODE_LATENCY = Histogram(
        "zeroque_intelligence_node_latency_ms",
        "Per-node latency in milliseconds",
        ["node"],
        buckets=[10, 50, 100, 500, 1000, 3000],
        registry=_REGISTRY,
    )

    # ── LLM token usage ─────────────────────────────────────────────────────────

    LLM_TOKENS = Counter(
        "zeroque_intelligence_llm_tokens_total",
        "Total LLM tokens consumed",
        ["operation", "token_type"],  # operation: plan | summarize | guardrail
        registry=_REGISTRY,
    )

    # ── Active sessions gauge ────────────────────────────────────────────────────

    ACTIVE_SESSIONS = Gauge(
        "zeroque_intelligence_active_sessions",
        "Number of active conversation sessions in memory",
        registry=_REGISTRY,
    )

    _METRICS_AVAILABLE = True

except ImportError:
    _METRICS_AVAILABLE = False
    _REGISTRY = None


# ── Public helpers ────────────────────────────────────────────────────────────

def record_query(
    engine: str,
    tier: int,
    latency_ms: float,
    success: bool,
) -> None:
    """Record a completed query. Call at end of run_agent()."""
    if not _METRICS_AVAILABLE:
        return
    QUERIES_TOTAL.labels(engine=engine, tier=str(tier), success=str(success)).inc()
    QUERY_LATENCY.labels(engine=engine).observe(latency_ms)


def record_guardrail_block(category: str, tier: int = 1) -> None:
    """Record a guardrail block event."""
    if not _METRICS_AVAILABLE:
        return
    GUARDRAIL_BLOCKS.labels(category=category, tier=str(tier)).inc()


def record_plan_retry() -> None:
    """Record a schema correction retry."""
    if not _METRICS_AVAILABLE:
        return
    PLAN_RETRIES.inc()


def record_node_latency(node: str, latency_ms: float) -> None:
    """Record per-node latency from OTel span timing."""
    if not _METRICS_AVAILABLE:
        return
    NODE_LATENCY.labels(node=node).observe(latency_ms)


def record_llm_tokens(operation: str, prompt: int, completion: int) -> None:
    """Record LLM token usage for cost tracking."""
    if not _METRICS_AVAILABLE:
        return
    LLM_TOKENS.labels(operation=operation, token_type="prompt").inc(prompt)
    LLM_TOKENS.labels(operation=operation, token_type="completion").inc(completion)


def set_active_sessions(count: int) -> None:
    """Update the active sessions gauge (call periodically or after each query)."""
    if not _METRICS_AVAILABLE:
        return
    ACTIVE_SESSIONS.set(count)


def get_registry():
    """Return the Prometheus registry for use in the /metrics endpoint."""
    return _REGISTRY


def is_available() -> bool:
    """Check if prometheus_client is installed."""
    return _METRICS_AVAILABLE
