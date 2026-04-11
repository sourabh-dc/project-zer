from __future__ import annotations

from datetime import timedelta, timezone

from supply_v2.models import SLARecord, utc_now
from supply_v2.store import InMemoryStore


class SLAService:
    def __init__(self, store: InMemoryStore, id_gen) -> None:
        self.store = store
        self.id_gen = id_gen

    def create_vendor_ack_sla(self, tenant_id: str, po_id: str, hours: int) -> SLARecord:
        sla = SLARecord(
            sla_id=self.id_gen("sla"),
            tenant_id=tenant_id,
            entity_type="purchase_order",
            entity_id=po_id,
            metric="vendor_ack_due",
            due_at=utc_now() + timedelta(hours=hours),
        )
        self.store.sla_records[sla.sla_id] = sla
        self.store.emit("sla.created", sla.sla_id)
        return sla

    def evaluate_due_records(self) -> list[SLARecord]:
        breached = []
        now = utc_now()
        for sla in self.store.sla_records.values():
            due_at = sla.due_at if sla.due_at.tzinfo else sla.due_at.replace(tzinfo=timezone.utc)
            if sla.status == "pending" and now >= due_at:
                sla.status = "breached"
                breached.append(sla)
                self.store.emit("sla.breached", sla.sla_id)
        return breached
