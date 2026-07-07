"""
Schema-grounded query validator.

WHY validate AFTER the LLM generates a query?
  Even with schema grounding in the prompt, LLMs occasionally hallucinate
  table or column names. Catching these here — before hitting the DB — lets
  us give the LLM a precise error message for self-correction instead of
  a raw database exception that leaks schema info in the traceback.

WHY not validate columns too (only tables)?
  Column validation requires parsing complex SQL expressions and handling
  aliases, subqueries, CTEs, etc. Table validation catches ~80% of hallucinations
  at much lower complexity. Column validation is a future improvement.

HOW the retry loop works:
  1. LLM generates plan
  2. schema_validator finds errors → returns error list
  3. agent.py feeds errors back as a correction prompt
  4. LLM generates corrected plan
  5. schema_validator runs again → if clean, proceed to execute
  6. After 2 failed attempts → return clear error to user
"""
import re
from typing import Dict, List, Set, Any


# ---------------------------------------------------------------------------
# SQL validation
# ---------------------------------------------------------------------------

def validate_sql(sql: str, schema_dict: Dict[str, List[str]]) -> List[str]:
    """Check that all tables referenced in SQL exist in schema_dict.

    schema_dict: {table_name_lower: [col1, col2, ...]}
    Returns a list of human-readable error strings (empty = clean).
    """
    errors: List[str] = []
    sql_lower = sql.lower()

    # Extract table references from FROM and JOIN clauses (handles aliases)
    table_refs: Set[str] = set()

    # FROM table [AS alias] / JOIN table [AS alias]
    for m in re.finditer(
        r'\b(?:from|join)\s+([a-z_][a-z0-9_]*)(?:\s+(?:as\s+)?[a-z_][a-z0-9_]*)?',
        sql_lower,
    ):
        table_refs.add(m.group(1))

    known_tables = set(schema_dict.keys())
    bad_tables = table_refs - known_tables

    if bad_tables:
        available = sorted(known_tables)
        errors.append(
            f"Unknown table(s): {sorted(bad_tables)}. "
            f"Available tables: {available}"
        )

    return errors


def build_sql_schema_dict(schema_description: str) -> Dict[str, List[str]]:
    """Parse the text schema description returned by get_schema_description()
    into a dict keyed by lowercase table name.

    Input format:
      TABLE foo (
        col1 type NOT NULL,
        col2 type NULL
      )
    """
    schema: Dict[str, List[str]] = {}
    current_table = None
    for line in schema_description.splitlines():
        stripped = line.strip()
        if stripped.startswith("TABLE "):
            current_table = stripped.split()[1].lower().rstrip("(").strip()
            schema[current_table] = []
        elif current_table and stripped and not stripped.startswith(")"):
            col_name = stripped.split()[0].lower()
            schema[current_table].append(col_name)
    return schema


# ---------------------------------------------------------------------------
# Cypher validation
# ---------------------------------------------------------------------------

def validate_cypher(
    cypher: str,
    known_labels: List[str],
    known_rels: List[str],
) -> List[str]:
    """Check that all node labels and relationship types in Cypher exist.

    Returns a list of human-readable error strings (empty = clean).
    """
    errors: List[str] = []

    # Node labels: (:Label) or (alias:Label)
    used_labels: Set[str] = set()
    for m in re.finditer(r'\([\w]*:(\w+)', cypher):
        used_labels.add(m.group(1))

    # Relationship types: [:TYPE] or -[:TYPE]->
    used_rels: Set[str] = set()
    for m in re.finditer(r'\[:(\w+)', cypher):
        used_rels.add(m.group(1))

    known_label_set = set(known_labels)
    known_rel_set = set(known_rels)

    bad_labels = used_labels - known_label_set
    bad_rels = used_rels - known_rel_set

    if bad_labels:
        errors.append(
            f"Unknown node label(s): {sorted(bad_labels)}. "
            f"Valid labels: {sorted(known_label_set)}"
        )
    if bad_rels:
        errors.append(
            f"Unknown relationship type(s): {sorted(bad_rels)}. "
            f"Valid types: {sorted(known_rel_set)}"
        )

    return errors


# ---------------------------------------------------------------------------
# Graph schema extraction (from live schema description text)
# ---------------------------------------------------------------------------

def parse_graph_schema(graph_description: str) -> Dict[str, List[str]]:
    """Extract {labels: [...], relationships: [...]} from graph schema description text."""
    labels: List[str] = []
    rels: List[str] = []

    in_labels = False
    in_rels = False

    for line in graph_description.splitlines():
        stripped = line.strip()
        if "Node labels" in stripped:
            in_labels = True
            in_rels = False
            continue
        if "Relationship types" in stripped:
            in_labels = False
            in_rels = True
            continue
        if "Known relationship directions" in stripped or "Notes:" in stripped:
            in_rels = False
            continue

        if in_labels and stripped.startswith(":"):
            # :Label  {props}
            label = stripped.lstrip(":").split()[0].split("{")[0].strip()
            if label:
                labels.append(label)

        if in_rels and stripped.startswith("[:"):
            # [:REL_TYPE]
            rel = stripped.lstrip("[:").rstrip("]").strip()
            if rel:
                rels.append(rel)

        # Also catch direction lines like (:Tenant)-[:HAS_SITE]->(:Site)
        for m in re.finditer(r'\[:(\w+)\]', stripped):
            r = m.group(1)
            if r not in rels:
                rels.append(r)

    return {"labels": list(dict.fromkeys(labels)), "relationships": list(dict.fromkeys(rels))}


# ---------------------------------------------------------------------------
# Plan-level validation: iterate all steps
# ---------------------------------------------------------------------------

def validate_plan_schema(
    plan: Dict[str, Any],
    sql_schema_dict: Dict[str, List[str]],
    graph_schema: Dict[str, List[str]],
) -> List[str]:
    """Validate all steps in a plan against real schemas.

    Returns aggregated error list (empty = clean).
    """
    all_errors: List[str] = []

    for i, step in enumerate(plan.get("steps", [])):
        engine = step.get("engine", "")
        query = step.get("query", "")
        if not query:
            continue

        if engine == "sql" and sql_schema_dict:
            errs = validate_sql(query, sql_schema_dict)
            for e in errs:
                all_errors.append(f"Step {i} (SQL): {e}")

        elif engine == "graph" and graph_schema.get("labels"):
            errs = validate_cypher(
                query,
                graph_schema["labels"],
                graph_schema["relationships"],
            )
            for e in errs:
                all_errors.append(f"Step {i} (Cypher): {e}")

    return all_errors
