










































We need to apply the suggested edit to the original code. The original code has a list of constraints, and the suggested edit adds a new entry ("Category", "category_id") to that list. Also, the suggested edit has a slightly different structure (the `def init_constraints()` function definition is repeated but we only need to modify the list). The original code's `init_constraints` function has 8 entries; the suggested edit adds the 9th entry "Category" after "Product". Also note that the original code includes imports and driver functions, which should remain unchanged. So we output the complete file with only the constraint list modified.


Thus, final output is the original code with the line `("Product", "product_id"),` followed by `("Category", "category_id"),` (indented appropriately) and then `("Carrier", "carrier_id"),` stays.

We need to ensure the exact formatting: the constraints list should have the new tuple inserted between "Product" and "Carrier". So the list becomes:
        ("Tenant", "tenant_id"),
        ("OrgUnit", "org_unit_id"),
        ("CostCentre", "cost_centre_id"),
        ("User", "user_id"),
        ("Role", "role_id"),
        ("ApprovedRange", "approved_range_id"),
        ("Product", "product_id"),









        ("Category", "category_id"),
        ("Carrier", "carrier_id"),

That's the only change. Everything else stays same.```
"""
Graph Service — Neo4j driver wrapper.

Provides session management and constraint initialization
for the governance topology graph.
"""
from neo4j import GraphDatabase

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

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
        ("Category", "category_id"),
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
We must output only the code, no explanation.
