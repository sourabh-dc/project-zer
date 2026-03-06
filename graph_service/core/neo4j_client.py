"""
Graph Service — Neo4j driver wrapper.

Provides session management and constraint initialization
for the governance topology graph.
"""
from neo4j import GraphDatabase

from graph_service.core.config import SETTINGS
from graph_service.core.logger import logger

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            SETTINGS.NEO4J_URI,
            auth=(SETTINGS.NEO4J_USER, SETTINGS.NEO4J_PASSWORD),
        )
        logger.info(f"Neo4j driver connected to {SETTINGS.NEO4J_URI}")
    return _driver


def close_driver():
    global _driver
    if _driver:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def get_session():
    return get_driver().session(database=SETTINGS.NEO4J_DATABASE)


def init_constraints():
    """Create uniqueness constraints and indexes on startup.

    Per engineering doc §1.1: all IDs are globally unique UUIDs.
    """
    constraints = [
        ("Tenant", "tenant_id"),
        ("OrgUnit", "org_unit_id"),
        ("CostCentre", "cost_centre_id"),
        ("User", "user_id"),
        ("Role", "role_id"),
        ("ApprovedRange", "approved_range_id"),
        ("Product", "product_id"),
        ("Carrier", "carrier_id"),
    ]

    with get_session() as session:
        for label, prop in constraints:
            try:
                session.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                )
            except Exception as exc:
                logger.warning(f"Constraint {label}.{prop} creation warning: {exc}")

        logger.info(f"Neo4j constraints initialized ({len(constraints)} labels)")
