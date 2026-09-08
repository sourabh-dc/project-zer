"""
Creditsafe Connect API — global company search & profile proxy.

Companion to companies_house_routes.py: Companies House covers the UK
for free; Creditsafe covers 160+ countries (paid). Same pattern —
API key stays server-side, frontend gets slim form-ready responses.

Endpoints:
  - GET /creditsafe/search              — search companies worldwide
  - GET /creditsafe/company/{id}        — full profile (+ credit rating)

Docs: https://connect.creditsafe.com/v1 (Connect API reference)
"""
from __future__ import annotations

from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from provisioning_service.core.config import SETTINGS
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/creditsafe", tags=["creditsafe"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CreditsafeSearchItem(BaseModel):
    """A single search hit."""
    company_id: str                     # Creditsafe id, e.g. "GB-0-00123456"
    name: str
    status: str = ""                    # Active | Inactive | ...
    country: str = ""                   # ISO code, e.g. "DE"
    reg_no: str = ""                    # local registration number
    company_type: str = ""
    address_snippet: str = ""


class CreditsafeSearchResponse(BaseModel):
    items: list[CreditsafeSearchItem] = Field(default_factory=list)
    total_results: int = 0


class CreditsafeCompanyProfile(BaseModel):
    """Full company profile — form-ready, plus credit summary."""
    company_id: str
    name: str
    status: str = ""
    country: str = ""
    reg_no: str = ""
    company_type: str = ""
    address_line_1: str = ""
    city: str = ""
    county: str = ""                    # region / state
    postal_code: str = ""
    incorporation_date: str = ""
    credit_rating: str = ""             # e.g. "B" — Creditsafe rating
    credit_limit_minor: Optional[int] = None
    currency: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    key = SETTINGS.CREDITSAFE_API_KEY
    if not key:
        raise HTTPException(status_code=500, detail="Creditsafe API key not configured")
    return {"x-creditsafe-api-key": key, "Accept": "application/json"}


def _address_snippet(addr: dict) -> str:
    return ", ".join(filter(None, [
        addr.get("street", ""),
        addr.get("city", ""),
        addr.get("postCode", ""),
    ]))


def _build_search_item(raw: dict) -> CreditsafeSearchItem:
    addr = raw.get("address", {}) or {}
    return CreditsafeSearchItem(
        company_id=str(raw.get("id", "")),
        name=raw.get("name", ""),
        status=str(raw.get("status", "")),
        country=raw.get("country", ""),
        reg_no=str(raw.get("regNo", "") or ""),
        company_type=str(raw.get("type", "") or ""),
        address_snippet=_address_snippet(addr),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/search", response_model=CreditsafeSearchResponse)
async def search_companies(
    q: str = Query(..., min_length=2, description="Company name to search"),
    countries: Optional[str] = Query(None, description="ISO codes, comma-separated, e.g. DE,FR"),
    max_results: int = Query(10, ge=1, le=50),
):
    """
    Search companies worldwide by name.

    Calls ``GET /companies`` on the Creditsafe Connect API. Pass
    ``countries`` to narrow results (strongly recommended — global
    searches are slow and noisy).
    """
    params: dict = {"name": q, "pageSize": max_results}
    if countries:
        params["countries"] = countries.upper()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{SETTINGS.CREDITSAFE_BASE_URL}/companies",
                params=params,
                headers=_headers(),
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=500, detail="Invalid Creditsafe API key")
            if resp.status_code == 402:
                raise HTTPException(status_code=402, detail="Creditsafe credit balance exhausted")
            resp.raise_for_status()
            data = resp.json()

        items = [_build_search_item(c) for c in (data.get("companies") or [])]
        return CreditsafeSearchResponse(
            items=items,
            total_results=data.get("totalNrOfHits", len(items)),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Creditsafe search failed: {exc}")
        raise HTTPException(status_code=502, detail="Creditsafe API unavailable")


@router.get("/company/{company_id}", response_model=CreditsafeCompanyProfile)
async def get_company_profile(company_id: str):
    """
    Full profile for one company (Creditsafe id from the search results).

    Calls ``GET /companies/{id}``. Includes credit rating/limit when the
    subscription covers it — useful for supplier risk checks.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{SETTINGS.CREDITSAFE_BASE_URL}/companies/{company_id}",
                headers=_headers(),
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
            if resp.status_code == 401:
                raise HTTPException(status_code=500, detail="Invalid Creditsafe API key")
            resp.raise_for_status()
            data = resp.json()

        addr = (data.get("address") or {})
        rating = (data.get("creditRating") or {})
        limit_value = (rating.get("creditLimit") or {}).get("value")
        return CreditsafeCompanyProfile(
            company_id=str(data.get("id", company_id)),
            name=data.get("name", ""),
            status=str(data.get("status", "")),
            country=data.get("country", ""),
            reg_no=str(data.get("regNo", "") or ""),
            company_type=str(data.get("type", "") or ""),
            address_line_1=addr.get("street", ""),
            city=addr.get("city", ""),
            county=addr.get("region", "") or addr.get("state", ""),
            postal_code=addr.get("postCode", ""),
            incorporation_date=str(data.get("incorporationDate", "") or ""),
            credit_rating=str(rating.get("commonDescription", "") or rating.get("rating", "") or ""),
            credit_limit_minor=int(round(float(limit_value) * 100)) if limit_value is not None else None,
            currency=(rating.get("creditLimit") or {}).get("currency", ""),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Creditsafe profile fetch failed: {exc}")
        raise HTTPException(status_code=502, detail="Creditsafe API unavailable")
