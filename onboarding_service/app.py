"""
onboarding_service.app
-----------------------
FastAPI application for the onboarding service.

Usage:
    uvicorn onboarding_service.app:app --port 8020 --reload
"""
from fastapi import FastAPI

from shared.db import engine, SessionFactory
from shared.models import Base as SharedBase
from onboarding_service.models import Base as OnboardingBase
from onboarding_service.routes import router, set_session_factory

app = FastAPI(title="ZeroQue Onboarding Service", version="1.0.0")
app.include_router(router)


@app.on_event("startup")
def _startup():
    SharedBase.metadata.create_all(engine)
    OnboardingBase.metadata.create_all(engine)
    set_session_factory(SessionFactory)


@app.get("/health")
def root_health():
    return {"status": "ok", "service": "onboarding_service"}
