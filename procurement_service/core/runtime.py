from __future__ import annotations

import threading
from typing import Optional, Any

from procurement_service.Models import IdempotencyRecord
from procurement_service.core.procurement_engine import ProcurementPlatform


class RuntimeContainer:
    def __init__(self) -> None:
        self.platform = ProcurementPlatform()
        self.lock = threading.RLock()

    def get_idempotent_response(self, tenant_id: str, endpoint: str, idempotency_key: Optional[str]) -> Optional[dict[str, Any]]:
        if not idempotency_key:
            return None
        for record in self.platform.store.idempotency_records.values():
            if record.tenant_id == tenant_id and record.endpoint == endpoint and record.idempotency_key == idempotency_key:
                return record.response_payload
        return None

    def save_idempotent_response(self, tenant_id: str, endpoint: str, idempotency_key: Optional[str], payload: dict[str, Any]) -> None:
        if not idempotency_key:
            return
        record_id = f"idempotency_{len(self.platform.store.idempotency_records) + 1:06d}"
        self.platform.store.idempotency_records[record_id] = IdempotencyRecord(
            key_id=record_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            response_payload=payload,
        )


_container = RuntimeContainer()


def get_container() -> RuntimeContainer:
    return _container
