"""
graph_service.neo4j_client
--------------------------
Neo4j driver management and helper functions.
"""
import logging
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

from shared.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

logger = logging.getLogger("graph_service.neo4j")

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        logger.info(f"Neo4j driver connected to {NEO4J_URI}")
    return _driver


def close_driver():
    global _driver
    if _driver:
        _driver.close()
        _driver = None


def init_constraints():
    """Create uniqueness constraints for core entity labels."""
    labels = {
        "Tenant": "tenant_id",
        "Site": "site_id",
        "Store": "store_id",
        "User": "user_id",
        "Vendor": "vendor_id",
        "CostCentre": "cost_centre_id",
        "OrgUnit": "org_unit_id",
        "Role": "role_id",
        "Product": "product_id",
        "Category": "category_id",
    }
    driver = get_driver()
    with driver.session() as session:
        for label, prop in labels.items():
            try:
                session.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                )
            except Exception as exc:
                logger.warning(f"Constraint {label}.{prop}: {exc}")
    logger.info(f"Neo4j constraints initialized ({len(labels)} labels)")


def run_cypher(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Execute a Cypher query and return results as list of dicts."""
    driver = get_driver()
    with driver.session() as session:
        result = session.run(query, params or {})
        return [dict(record) for record in result]
