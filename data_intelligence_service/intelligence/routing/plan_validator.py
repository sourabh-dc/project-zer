"""
Validates LLM-generated query plans before execution.

Catches structural issues early so we never pass a broken plan to the
database layer.
"""
from typing import Dict, Any, List

VALID_ENGINES = {"sql", "graph", "vector"}
MAX_STEPS = 8


class PlanValidationError(Exception):
    """Raised when a plan is fundamentally un-executable."""


def validate_plan(plan: Dict[str, Any]) -> List[str]:
    """Validate a query plan. Returns a list of warning strings.

    Raises PlanValidationError for fatal structural problems.
    Mutates the plan in-place to fix auto-correctable issues (e.g. caps steps).
    """
    if not isinstance(plan, dict):
        raise PlanValidationError("Plan is not a dict")

    if "error" in plan:
        raise PlanValidationError(f"LLM returned error in plan: {plan['error']}")

    steps = plan.get("steps")
    if not steps:
        raise PlanValidationError("Plan has no steps — LLM failed to generate a query")

    if not isinstance(steps, list):
        raise PlanValidationError(f"Plan steps must be a list, got {type(steps)}")

    warnings: List[str] = []

    if len(steps) > MAX_STEPS:
        warnings.append(f"Plan has {len(steps)} steps — capped at {MAX_STEPS}")
        plan["steps"] = steps[:MAX_STEPS]
        steps = plan["steps"]

    valid_steps = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            warnings.append(f"Step {i} is not a dict — skipped")
            continue

        engine = step.get("engine", "")
        if engine not in VALID_ENGINES:
            warnings.append(f"Step {i}: unknown engine '{engine}' — skipped")
            continue

        query = step.get("query", "")
        if not query or not isinstance(query, str) or not query.strip():
            warnings.append(f"Step {i} ({engine}): empty query — skipped")
            continue

        dep = step.get("depends_on")
        if dep is not None:
            if not isinstance(dep, int) or dep < 0 or dep >= i:
                warnings.append(
                    f"Step {i}: invalid depends_on={dep!r} (must be int 0..{i-1}) — cleared"
                )
                step["depends_on"] = None

        valid_steps.append(step)

    if not valid_steps:
        raise PlanValidationError("All steps were invalid — nothing to execute")

    plan["steps"] = valid_steps
    return warnings
