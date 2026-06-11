"""
OpenTelemetry setup and helpers for the intelligence agent.

WHY OpenTelemetry and not just LangSmith?
  LangSmith is great for dev debugging of LangGraph runs, but it's vendor-specific.
  OTel is the industry standard — instrument once, route to any backend:
  Langfuse (open-source), Grafana/Tempo, Datadog, Honeycomb, or Azure Monitor.
  We use OTel GenAI semantic conventions so any OTel-aware backend understands
  our spans out of the box.

HOW to use:
  1. Call setup_tracing() once at app startup (done in main.py).
  2. Wrap agent nodes with span_node() context manager.
  3. Spans automatically export to configured backend.

BACKENDS (configure via .env):
  - Langfuse: set LANGFUSE_SECRET_KEY + LANGFUSE_PUBLIC_KEY + LANGFUSE_HOST
  - Grafana/Tempo: set OTEL_EXPORTER_OTLP_ENDPOINT to Tempo's OTLP HTTP endpoint
  - No backend configured → spans printed to stdout in dev (OTEL_LOG_LEVEL=debug)

LANGCHAIN_TRACING_V2 (LangSmith) still works independently — both can run together.
"""
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource

_tracer: Optional[trace.Tracer] = None
_provider: Optional[TracerProvider] = None


def setup_tracing(service_name: str = "zeroque-intelligence") -> None:
    """
    Initialise the OpenTelemetry tracer.

    Call once at application startup. Idempotent — safe to call multiple times.

    Backends detected from environment (in priority order):
      1. Langfuse   — LANGFUSE_SECRET_KEY present
      2. OTLP HTTP  — OTEL_EXPORTER_OTLP_ENDPOINT present
      3. Console    — fallback for dev (prints spans to stdout)
    """
    global _tracer, _provider

    if _provider is not None:
        return  # already initialised

    resource = Resource.create({"service.name": service_name})
    _provider = TracerProvider(resource=resource)

    exporters_configured = False

    # ── Langfuse backend ──────────────────────────────────────────────────────
    langfuse_secret = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_public = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_host   = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if langfuse_secret and langfuse_public:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            import base64
            creds = base64.b64encode(f"{langfuse_public}:{langfuse_secret}".encode()).decode()
            exporter = OTLPSpanExporter(
                endpoint=f"{langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
                headers={"Authorization": f"Basic {creds}"},
            )
            _provider.add_span_processor(BatchSpanProcessor(exporter))
            exporters_configured = True
            _log(f"[OTel] Langfuse backend configured → {langfuse_host}")
        except Exception as exc:
            _log(f"[OTel] Langfuse setup failed: {exc}", warn=True)

    # ── Generic OTLP backend (Grafana Tempo, Jaeger, etc.) ────────────────────
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if otlp_endpoint and not exporters_configured:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            _provider.add_span_processor(BatchSpanProcessor(exporter))
            exporters_configured = True
            _log(f"[OTel] OTLP backend configured → {otlp_endpoint}")
        except Exception as exc:
            _log(f"[OTel] OTLP setup failed: {exc}", warn=True)

    # ── Console fallback (dev / no backend configured) ────────────────────────
    if not exporters_configured:
        if os.getenv("OTEL_LOG_LEVEL", "").lower() == "debug":
            _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        _log("[OTel] No backend configured. Set LANGFUSE_* or OTEL_EXPORTER_OTLP_ENDPOINT to export traces.")

    trace.set_tracer_provider(_provider)
    _tracer = trace.get_tracer(service_name)
    _log("[OTel] Tracing initialised")


def get_tracer() -> trace.Tracer:
    """Return the configured tracer. Call setup_tracing() first."""
    if _tracer is None:
        setup_tracing()
    return _tracer


@contextmanager
def span_node(node_name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Context manager that wraps a LangGraph node in an OTel span.

    Usage:
        with span_node("plan", {"engine_hint": "sql"}) as span:
            ... do the node work ...
            span.set_attribute("plan.steps", 2)

    The span name follows OTel GenAI conventions: 'gen_ai.agent.node.<name>'
    """
    tracer = get_tracer()
    span_name = f"agent.node.{node_name}"
    with tracer.start_as_current_span(span_name) as span:
        # OTel GenAI semantic convention attributes
        span.set_attribute("gen_ai.operation.name", node_name)
        span.set_attribute("gen_ai.provider.name", "azure_openai")

        if attributes:
            for k, v in attributes.items():
                try:
                    span.set_attribute(k, v)
                except Exception:
                    pass  # attribute type mismatch — skip rather than crash

        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise


@contextmanager
def span_llm_call(operation: str, model: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Context manager for a single LLM call (plan or summarize).

    Captures OTel GenAI semantic convention attributes:
      gen_ai.operation.name, gen_ai.request.model, gen_ai.usage.*
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"gen_ai.{operation}") as span:
        span.set_attribute("gen_ai.operation.name", operation)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.provider.name", "azure_openai")

        if attributes:
            for k, v in attributes.items():
                try:
                    span.set_attribute(k, v)
                except Exception:
                    pass

        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise


def record_token_usage(span: trace.Span, response_metadata: Dict[str, Any]) -> Dict[str, int]:
    """
    Extract token counts from LangChain response metadata and add to span.

    LangChain stores usage in response.response_metadata['token_usage'] or
    response.usage_metadata depending on the SDK version.

    Returns dict with prompt/completion/total keys (all default to 0).
    """
    usage: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}

    try:
        # LangChain >= 0.2 stores in response.usage_metadata
        if hasattr(response_metadata, "usage_metadata") and response_metadata.usage_metadata:
            um = response_metadata.usage_metadata
            usage["prompt"]     = um.get("input_tokens", 0)
            usage["completion"] = um.get("output_tokens", 0)
            usage["total"]      = um.get("total_tokens", 0)
        # Older LangChain stores in response_metadata dict
        elif isinstance(response_metadata, dict):
            tu = response_metadata.get("token_usage", {})
            usage["prompt"]     = tu.get("prompt_tokens", 0)
            usage["completion"] = tu.get("completion_tokens", 0)
            usage["total"]      = tu.get("total_tokens", 0)
    except Exception:
        pass  # token tracking is best-effort — never fail the main flow

    span.set_attribute("gen_ai.usage.input_tokens",  usage["prompt"])
    span.set_attribute("gen_ai.usage.output_tokens", usage["completion"])

    return usage


def _log(msg: str, warn: bool = False) -> None:
    """Simple print wrapper to avoid importing logger (circular dep risk)."""
    import sys
    level = "WARNING" if warn else "INFO"
    print(f"{level}: {msg}", file=sys.stderr if warn else sys.stdout)
