# Report types
from enum import Enum


class ReportType(str, Enum):
    SALES_ANALYTICS = "sales_analytics"
    INVENTORY_ANALYTICS = "inventory_analytics"
    CUSTOMER_ANALYTICS = "customer_analytics"
    OPERATIONAL_ANALYTICS = "operational_analytics"
    FINANCIAL_ANALYTICS = "financial_analytics"
    USAGE_ANALYTICS = "usage_analytics"
    PERFORMANCE_ANALYTICS = "performance_analytics"

# Phase 6: Dashboard types for Power BI integration
class DashboardType(str, Enum):
    OVERVIEW = "overview"
    SALES = "sales"
    INVENTORY = "inventory"
    CUSTOMER = "customer"
    OPERATIONAL = "operational"
    FINANCIAL = "financial"
    CUSTOM = "custom"

class ReportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    EXCEL = "xlsx"
    PDF = "pdf"

class ReportStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"