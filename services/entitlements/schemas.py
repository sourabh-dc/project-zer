from pydantic import BaseModel

# Pydantic Models
class CheckEntitlementRequest(BaseModel):
    tenant_id: str
    feature_code: str

class RecordUsageRequest(BaseModel):
    tenant_id: str
    feature_code: str
    usage_type: str
    count: int = 1