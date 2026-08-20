"""Connector registry — provider_code → connector class."""
from __future__ import annotations

from typing import Dict, Type

from provisioning_service.core.connectors.base import BaseConnector
from provisioning_service.core.connectors.dynamics_bc import DynamicsBCConnector
from provisioning_service.core.connectors.netsuite import NetSuiteConnector
from provisioning_service.core.connectors.oracle_erp import OracleERPConnector
from provisioning_service.core.connectors.sap_b1 import SapB1Connector

CONNECTORS: Dict[str, Type[BaseConnector]] = {
    "dynamics_bc": DynamicsBCConnector,
    "sap_b1": SapB1Connector,
    "netsuite": NetSuiteConnector,
    "oracle_erp": OracleERPConnector,
}


def get_connector_class(provider_code: str) -> Type[BaseConnector]:
    cls = CONNECTORS.get(provider_code)
    if cls is None:
        raise KeyError(f"Unknown connector provider: {provider_code!r}")
    return cls
