"""
AI Gateway — tiered model routing for the ZeroQue intelligence agent.

WHY tiered routing? (spec §11)
  Using gpt-5-nano (reasoning model) for every query is like driving a
  Formula 1 car to buy milk — expensive and slow. Most queries are simple
  factual lookups that need no reasoning tokens at all.

  Four tiers (aligned to spec §11):

  ZERO   — No LLM at all. Pure template / deterministic retrieval.
           Examples: "Show me fireproof shoes", "Has this product been purchased before?"

  FAST   — gpt-4o. Simple, high-confidence lookups and short explanations.
           Examples: "How many products do we have?", "Summarise this supplier note"
           Triggers when: single engine, confidence ≥ 0.85, routing tier ≤ 2, first attempt

  MID    — gpt-4o. Comparisons, moderate reasoning, analytical queries.
           Examples: "Compare these two suppliers", "Recommend alternatives", "Summarise performance"
           Triggers when: analytical patterns in question, multi-source but not complex,
                          or FAST threshold not met but no need for full reasoning

  REASON — gpt-5-nano. Complex, multi-hop, strategic queries and all retries.
           Examples: "Supplier risk analysis", "Multi-factor spend analysis", "Contract interpretation"
           Triggers when: hybrid engine, low confidence, retries, schema errors, strategic intent

DEPLOYMENT NAMES (configure in .env):
  AZURE_OPENAI_LLM_DEPLOYMENT       = gpt-5-nano    (REASON — default / fallback)
  AZURE_OPENAI_FAST_DEPLOYMENT      = gpt-4o        (FAST)
  AZURE_OPENAI_TIER2_DEPLOYMENT     = gpt-4o        (MID — same or different deployment)

TUNEABLE via .env:
  GATEWAY_FAST_CONFIDENCE_THRESHOLD  default 0.85
  GATEWAY_FAST_MAX_ROUTING_TIER      default 2
  GATEWAY_MID_CONFIDENCE_THRESHOLD   default 0.60
"""
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from data_intelligence_service.core.logger import logger


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

class ModelTier(str, Enum):
    """Which model class to use for this query.

    String enum so values can be set as OTel span attributes without conversion.
    """
    ZERO   = "zero"    # No LLM — template / deterministic answer
    FAST   = "fast"    # gpt-4o — simple, high-confidence single-engine queries
    MID    = "mid"     # gpt-4o — comparisons, moderate reasoning, analytical
    REASON = "reason"  # gpt-5-nano — complex, multi-hop, retries, strategic


# ---------------------------------------------------------------------------
# Config — resolved from environment at import time
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    reason_deployment: str   # Tier 3 — full reasoning model
    fast_deployment:   str   # Tier 1 — fast/cheap
    mid_deployment:    str   # Tier 2 — moderate reasoning

    @classmethod
    def from_env(cls) -> "ModelConfig":
        reason = os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT",   "gpt-5-nano")
        fast   = os.getenv("AZURE_OPENAI_FAST_DEPLOYMENT",   reason)    # fallback to reason
        mid    = os.getenv("AZURE_OPENAI_TIER2_DEPLOYMENT",  fast)      # fallback to fast
        return cls(reason_deployment=reason, fast_deployment=fast, mid_deployment=mid)


MODEL_CONFIG: ModelConfig = ModelConfig.from_env()


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_FAST_CONFIDENCE_THRESHOLD = float(os.getenv("GATEWAY_FAST_CONFIDENCE_THRESHOLD", "0.85"))
_MID_CONFIDENCE_THRESHOLD  = float(os.getenv("GATEWAY_MID_CONFIDENCE_THRESHOLD",  "0.60"))
_FAST_MAX_ROUTING_TIER     = int(os.getenv("GATEWAY_FAST_MAX_ROUTING_TIER", "2"))
_FAST_ELIGIBLE_ENGINES     = frozenset({"sql", "graph", "vector"})


# ---------------------------------------------------------------------------
# MID tier intent patterns
# ---------------------------------------------------------------------------
# Questions that need moderate reasoning but not the full reasoning model.

_MID_PATTERNS = [
    r"\bcompare\b",
    r"\bvs\.?\b",
    r"\bversus\b",
    r"\brecommend\b",
    r"\balternative\b",
    r"\bsubstitut\b",
    r"\bsummarise\b",
    r"\bsummarize\b",
    r"\bperformance\b",
    r"\brank\b",
    r"\bbest\b.{0,15}(supplier|vendor|product|option)\b",
    r"\bwhich.{0,20}(supplier|vendor|product|option).{0,20}(should|best|recommend)\b",
    r"\btop\b.{0,10}(supplier|vendor|categor)\b",
    r"\bspend.{0,20}trend\b",
    r"\bhow.{0,10}(perform|doing|risk)\b",
]

def _is_mid_intent(question: str) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in _MID_PATTERNS)


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------

def choose_tier(
    engine_hint: str,
    routing_tier: int,
    confidence: float,
    plan_attempts: int,
    schema_errors: Optional[List] = None,
    question: str = "",
) -> ModelTier:
    """Pick the cheapest model tier sufficient for this query.

    Priority (first match wins):
      ZERO   — routing_tier == 0
      REASON — any retry, schema error, hybrid/unknown engine, low confidence
      FAST   — single engine, high confidence, low routing tier, first attempt
      MID    — analytical/comparison patterns detected, or moderate confidence
      REASON — safe default
    """
    # Tier 0 — no LLM needed
    if routing_tier == 0:
        return ModelTier.ZERO

    # Always REASON for retries and schema-error corrections
    if plan_attempts > 0 or (schema_errors and len(schema_errors) > 0):
        logger.debug(f"[Gateway] REASON: retry attempts={plan_attempts} schema_errors={len(schema_errors or [])}")
        return ModelTier.REASON

    # REASON for hybrid or unknown (needs full reasoning to combine sources)
    if engine_hint not in _FAST_ELIGIBLE_ENGINES:
        logger.debug(f"[Gateway] REASON: engine={engine_hint} not single-engine")
        return ModelTier.REASON

    # REASON for low confidence (classifier not sure what engine to use)
    if confidence < _MID_CONFIDENCE_THRESHOLD:
        logger.debug(f"[Gateway] REASON: confidence={confidence:.2f} < {_MID_CONFIDENCE_THRESHOLD}")
        return ModelTier.REASON

    # FAST: high confidence + simple routing + first attempt + single engine
    engine_ok     = engine_hint in _FAST_ELIGIBLE_ENGINES
    confidence_ok = confidence >= _FAST_CONFIDENCE_THRESHOLD
    tier_ok       = routing_tier <= _FAST_MAX_ROUTING_TIER

    if engine_ok and confidence_ok and tier_ok and not _is_mid_intent(question):
        _resolved = ModelTier.FAST if MODEL_CONFIG.fast_deployment != MODEL_CONFIG.reason_deployment else ModelTier.REASON
        logger.debug(f"[Gateway] FAST: engine={engine_hint} conf={confidence:.2f} → {MODEL_CONFIG.fast_deployment}")
        return _resolved

    # MID: moderate confidence or analytical patterns detected
    if _is_mid_intent(question) or confidence >= _MID_CONFIDENCE_THRESHOLD:
        _resolved = ModelTier.MID if MODEL_CONFIG.mid_deployment != MODEL_CONFIG.reason_deployment else ModelTier.REASON
        logger.debug(f"[Gateway] MID: question pattern matched → {MODEL_CONFIG.mid_deployment}")
        return _resolved

    logger.debug(f"[Gateway] REASON: safe default")
    return ModelTier.REASON


# ---------------------------------------------------------------------------
# LLM factory per tier
# ---------------------------------------------------------------------------

def make_llm_for_tier(tier: ModelTier, temperature: float = 0.0):
    """Return an AzureChatOpenAI instance for the given model tier.

    Token headroom:
      REASON (gpt-5-nano): 8000 — reasoning model needs internal thinking tokens
      MID    (gpt-4o):     4000 — moderate output, no reasoning overhead
      FAST   (gpt-4o):     2000 — short answers, query plans
    """
    from langchain_openai import AzureChatOpenAI
    from data_intelligence_service.core.config import SETTINGS

    if tier == ModelTier.FAST:
        deployment = MODEL_CONFIG.fast_deployment
        max_tokens = 2000
    elif tier == ModelTier.MID:
        deployment = MODEL_CONFIG.mid_deployment
        max_tokens = 4000
    else:
        # REASON or ZERO (ZERO shouldn't reach here — fall back safely)
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
    if tier == ModelTier.MID:
        return MODEL_CONFIG.mid_deployment
    return MODEL_CONFIG.reason_deployment
