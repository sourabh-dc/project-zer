"""
AI Gateway — tiered model routing for the ZeroQue intelligence agent.

WHY tiered routing?
  Every query today uses gpt-5-nano (a reasoning model). That's like driving
  a Formula 1 car to buy milk — expensive and slow. Most queries are simple
  ("how many products do we have?") and can be answered correctly by a fast,
  cheap model. Complex multi-hop queries genuinely need the reasoning model.

  Tiered routing gives us:
    ZERO  — no LLM at all   (Tier 0 template matches)
    FAST  — gpt-4o-mini     (~200ms, ~10x cheaper than reasoning model)
    REASON— gpt-5-nano      (~2000ms, full reasoning for complex queries)

HOW it works:
  choose_tier() is called in node_plan and node_summarize after classification.
  The decision uses the classifier output (tier, engine_hint, confidence)
  already sitting in AgentState — zero extra latency, no extra LLM call.

  FAST is chosen when ALL of:
    - Classifier confidence >= threshold (default 0.85 — well-understood query)
    - Engine is single (sql, graph, or vector — NOT hybrid, NOT unknown)
    - Routing tier <= 2 (regex or scoring match, not LLM-classified)
    - No prior schema errors on this query (retries get the full model)

  REASON is the safe default — if we're unsure, use the powerful model.

ADDING A NEW TIER:
  1. Add a value to ModelTier enum
  2. Add the deployment name to ModelConfig
  3. Update choose_tier() logic
  4. Add the deployment to Azure OpenAI and to .env.example

DEPLOYMENT NAMES (configure in .env):
  AZURE_OPENAI_LLM_DEPLOYMENT       = gpt-5-nano      (REASON — default)
  AZURE_OPENAI_FAST_DEPLOYMENT      = gpt-4o-mini     (FAST)
"""
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from data_intelligence_service.core.logger import logger


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

class ModelTier(str, Enum):
    """Which model class to use for this query.

    String enum so values can be set as OTel span attributes without conversion.
    """
    ZERO   = "zero"    # No LLM — template answer, no tokens spent
    FAST   = "fast"    # gpt-4o-mini — simple, high-confidence queries
    REASON = "reason"  # gpt-5-nano  — complex, multi-hop, low confidence


# ---------------------------------------------------------------------------
# Config — deployment names resolved from environment at import time
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    """Resolved Azure deployment names for each tier."""
    reason_deployment: str  # full reasoning model (default for all queries)
    fast_deployment: str    # fast/cheap model for simple queries

    @classmethod
    def from_env(cls) -> "ModelConfig":
        reason = os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT", "gpt-5-nano")
        fast   = os.getenv("AZURE_OPENAI_FAST_DEPLOYMENT", reason)  # fallback to reason if not set
        return cls(reason_deployment=reason, fast_deployment=fast)


MODEL_CONFIG: ModelConfig = ModelConfig.from_env()


# ---------------------------------------------------------------------------
# Routing thresholds (tuneable via env)
# ---------------------------------------------------------------------------

# Minimum classifier confidence to consider FAST tier.
# Below this, use REASON regardless of engine/tier.
_FAST_CONFIDENCE_THRESHOLD = float(os.getenv("GATEWAY_FAST_CONFIDENCE_THRESHOLD", "0.85"))

# Only route to FAST if the classifier used tier 1 or 2 (no LLM involvement).
# Tier 3 (LLM-classified) queries indicate ambiguity — use REASON.
_FAST_MAX_ROUTING_TIER = int(os.getenv("GATEWAY_FAST_MAX_ROUTING_TIER", "2"))

# Engines eligible for FAST tier — hybrid/unknown always use REASON.
_FAST_ELIGIBLE_ENGINES = frozenset({"sql", "graph", "vector"})


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------

def choose_tier(
    engine_hint: str,
    routing_tier: int,
    confidence: float,
    plan_attempts: int,
    schema_errors: Optional[list] = None,
) -> ModelTier:
    """Decide which model tier to use for this query.

    Called in node_plan (planner LLM) and node_summarize (summarizer LLM).

    Args:
        engine_hint:    Classifier engine output — sql | graph | vector | hybrid | unknown
        routing_tier:   Classifier tier — 1=regex, 2=scoring, 3=llm
        confidence:     Classifier confidence [0.0, 1.0]
        plan_attempts:  Number of plan attempts so far (0 = first try)
        schema_errors:  Any schema errors from the previous plan attempt

    Returns:
        ModelTier indicating which model to use.

    Decision rules (all must pass for FAST, otherwise REASON):
      1. Engine is a single, well-defined engine (not hybrid/unknown)
      2. Classifier confidence >= threshold (query well understood)
      3. Routing tier <= max tier (no LLM involvement in classification)
      4. First plan attempt only (retries need full reasoning power)
      5. No prior schema errors (errors indicate model needs more guidance)
    """
    # Tier 0 queries have no plan → no LLM needed at all.
    # Caller is responsible for short-circuiting before calling node_plan;
    # but if choose_tier is called anyway, return ZERO.
    if routing_tier == 0:
        return ModelTier.ZERO

    # Any retry or prior schema error → use full reasoning model for correction
    if plan_attempts > 0 or (schema_errors and len(schema_errors) > 0):
        logger.debug(f"[Gateway] REASON (retry): attempts={plan_attempts} errors={len(schema_errors or [])}")
        return ModelTier.REASON

    # Check all FAST eligibility conditions
    engine_ok     = engine_hint in _FAST_ELIGIBLE_ENGINES
    confidence_ok = confidence >= _FAST_CONFIDENCE_THRESHOLD
    tier_ok       = routing_tier <= _FAST_MAX_ROUTING_TIER

    if engine_ok and confidence_ok and tier_ok:
        # Only use FAST if a separate fast deployment is actually configured.
        # If AZURE_OPENAI_FAST_DEPLOYMENT is not set, fast == reason — still works,
        # just logs that we would have used FAST.
        if MODEL_CONFIG.fast_deployment != MODEL_CONFIG.reason_deployment:
            logger.debug(
                f"[Gateway] FAST: engine={engine_hint} confidence={confidence:.2f} "
                f"tier={routing_tier} → {MODEL_CONFIG.fast_deployment}"
            )
            return ModelTier.FAST
        else:
            logger.debug(
                f"[Gateway] FAST eligible but AZURE_OPENAI_FAST_DEPLOYMENT not configured "
                f"— using REASON deployment ({MODEL_CONFIG.reason_deployment})"
            )
            return ModelTier.REASON

    logger.debug(
        f"[Gateway] REASON: engine={engine_hint} engine_ok={engine_ok} "
        f"confidence={confidence:.2f} confidence_ok={confidence_ok} "
        f"tier={routing_tier} tier_ok={tier_ok}"
    )
    return ModelTier.REASON


# ---------------------------------------------------------------------------
# LLM factory per tier
# ---------------------------------------------------------------------------

def make_llm_for_tier(
    tier: ModelTier,
    temperature: float = 0.0,
):
    """Return an AzureChatOpenAI instance for the given model tier.

    WHY lazy import?
      Keeps this module importable without requiring langchain to be installed
      in environments that only use the routing logic (e.g. unit tests).

    WHY temperature=0.0 default?
      Planner calls need deterministic JSON output. Summarizer may pass 1.0
      for slightly more natural prose — the caller decides.

    WHY max_completion_tokens=8000 for REASON?
      Reasoning models (gpt-5-nano, o1, o3) spend internal thinking tokens
      before producing output. Without headroom, the model returns empty
      output with finish_reason='length'. 8000 covers complex plans.

    WHY max_completion_tokens=2000 for FAST?
      gpt-4o-mini is a standard model — no reasoning token overhead.
      2000 is more than enough for a query plan or a short summary.
    """
    from langchain_openai import AzureChatOpenAI
    from data_intelligence_service.core.config import SETTINGS

    if tier == ModelTier.FAST:
        deployment = MODEL_CONFIG.fast_deployment
        max_tokens = 2000
    else:
        # REASON or ZERO (ZERO shouldn't reach here, but fall back safely)
        deployment = MODEL_CONFIG.reason_deployment
        max_tokens = 8000

    return AzureChatOpenAI(
        azure_endpoint=SETTINGS.AZURE_OPENAI_ENDPOINT,
        azure_deployment=deployment,
        api_version=SETTINGS.AZURE_OPENAI_API_VERSION,
        api_key=SETTINGS.AZURE_OPENAI_API_KEY,
        max_completion_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deployment_for_tier(tier: ModelTier) -> str:
    """Return the Azure deployment name for a given tier (for span attributes)."""
    if tier == ModelTier.FAST:
        return MODEL_CONFIG.fast_deployment
    return MODEL_CONFIG.reason_deployment
