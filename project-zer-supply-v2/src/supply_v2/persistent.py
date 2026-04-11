from __future__ import annotations

from typing import Optional

from supply_v2.db import (
    OrderLineRow,
    OrderRow,
    PurchaseOrderRow,
    VendorRow,
    build_engine,
    build_session_factory,
    init_db,
    load_platform_state,
    save_platform_state,
)
from supply_v2.rbac import RBACService


class PersistentPlatform:
    def __init__(self, database_url: Optional[str] = None, snapshot_key: str = "main") -> None:
        self.engine = build_engine(database_url)
        self.session_factory = build_session_factory(self.engine)
        self.snapshot_key = snapshot_key
        init_db(self.engine)
        RBACService(self.session_factory).seed_defaults()
        self.platform = self._load_platform()

    def _load_platform(self):
        session = self.session_factory()
        try:
            has_rows = (
                session.query(VendorRow).first()
                or session.query(OrderRow).first()
                or session.query(OrderLineRow).first()
                or session.query(PurchaseOrderRow).first()
            )
            if has_rows:
                return load_platform_state(session)
            return load_platform_state(session)
        finally:
            session.close()

    def commit(self) -> None:
        session = self.session_factory()
        try:
            save_platform_state(session, self.platform)
        finally:
            session.close()

    def refresh(self) -> None:
        self.platform = self._load_platform()
