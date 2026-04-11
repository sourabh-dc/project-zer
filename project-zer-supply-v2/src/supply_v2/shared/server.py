from __future__ import annotations

import os

from fastapi import FastAPI

from supply_v2.persistent import PersistentPlatform

def build_service_app(factory) -> FastAPI:
    database_url = os.environ.get("SUPPLY_V2_DB_URL")
    persistent = PersistentPlatform(database_url=database_url) if database_url else None
    return factory(persistent=persistent)
