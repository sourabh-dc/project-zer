# AI Gateway — Tiered Model Routing

Routes each intelligence query to the cheapest model that can answer it correctly.

## Why

Every query used `gpt-5-nano` (reasoning model). That's 10× more expensive and 10× slower than needed for simple factual lookups. Tiered routing picks the right tool for the job.

## Tiers

| Tier | Model | When | Latency | Cost |
|------|-------|------|---------|------|
| ZERO | None | Tier 0 template match | < 1 ms | Free |
| FAST | `gpt-4o-mini` | High confidence, single engine, no retries | ~200 ms | Low |
| REASON | `gpt-5-nano` | Complex, hybrid, low confidence, retries | ~2000 ms | High |

## Decision Rules (all must pass for FAST)

1. Engine is `sql`, `graph`, or `vector` — not `hybrid` or `unknown`
2. Classifier confidence ≥ 0.85 (query well understood)
3. Routing tier ≤ 2 (regex or scoring match — no LLM involved in classification)
4. First plan attempt (retries always use REASON)
5. No prior schema errors

If `AZURE_OPENAI_FAST_DEPLOYMENT` is not set, falls back to the REASON deployment transparently.

## Environment Variables

```env
AZURE_OPENAI_LLM_DEPLOYMENT=gpt-5-nano        # REASON tier (default)
AZURE_OPENAI_FAST_DEPLOYMENT=gpt-4o-mini       # FAST tier (optional)
GATEWAY_FAST_CONFIDENCE_THRESHOLD=0.85         # tune FAST eligibility
GATEWAY_FAST_MAX_ROUTING_TIER=2                # tune FAST eligibility
```

## Usage

```python
from intelligence.gateway.router import choose_tier, make_llm_for_tier, ModelTier

tier = choose_tier(
    engine_hint="sql",
    routing_tier=1,
    confidence=0.95,
    plan_attempts=0,
)
llm = make_llm_for_tier(tier, temperature=0.0)
response = llm.invoke(messages)
```

## Files

| File | Purpose |
|------|---------|
| `router.py` | `ModelTier` enum, `choose_tier()`, `make_llm_for_tier()` |
| `README.md` | This file |
