from __future__ import annotations

import threading
from typing import Optional
from typing import Any

from supply_v2.persistent import PersistentPlatform
from supply_v2.platform import SupplyPlatform


class AppContainer:
    def __init__(self, platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> None:
        self.persistent = persistent
        self.platform = platform or (persistent.platform if persistent else SupplyPlatform())
        self.lock = threading.RLock()

    def reload(self) -> None:
        with self.lock:
            if self.persistent:
                self.persistent.refresh()
                self.platform = self.persistent.platform

    def commit(self) -> None:
        with self.lock:
            if self.persistent:
                self.persistent.commit()

    def get_idempotent_response(self, tenant_id: str, endpoint: str, idempotency_key: Optional[str]) -> Optional[dict[str, Any]]:
        with self.lock:
            if not idempotency_key:
                return None
            for record in self.platform.store.idempotency_records.values():
                if (
                    record.tenant_id == tenant_id
                    and record.endpoint == endpoint
                    and record.idempotency_key == idempotency_key
                ):
                    return record.response_payload
            return None

    def save_idempotent_response(self, tenant_id: str, endpoint: str, idempotency_key: Optional[str], payload: dict[str, Any]) -> None:
        with self.lock:
            if not idempotency_key:
                return
            record_id = f"idempotency_{len(self.platform.store.idempotency_records) + 1:06d}"
            from supply_v2.models import IdempotencyRecord

            self.platform.store.idempotency_records[record_id] = IdempotencyRecord(
                key_id=record_id,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                endpoint=endpoint,
                response_payload=payload,
            )
