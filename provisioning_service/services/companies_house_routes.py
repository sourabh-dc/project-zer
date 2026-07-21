"""
Companies House API — Company search & profile proxy.

Exposes two endpoints so the frontend can provide an autocomplete
dropdown during tenant registration without exposing the API key.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional

from provisioning_service.core.config import SETTINGS
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/companies-house", tags=["companies-house"])

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CompanySearchItem(BaseModel):
    """A single result from the companies search endpoint."""
    company_number: str
    title: str           # company name
    company_status: str
    company_type: str
    address_snippet: str = ""
    date_of_creation: str = ""
    description: str = ""  # SIC code description (first one)


class CompanySearchResponse(BaseModel):
    items: list[CompanySearchItem] = Field(default_factory=list)
    total_results: int = 0


class RegisteredOffice(BaseModel):
    address_line_1: str = ""
    address_line_2: str = ""
    locality: str = ""
    postal_code: str = ""
    country: str = ""


class CompanyProfile(BaseModel):
    company_number: str
    company_name: str
    company_status: str
    company_type: str
    date_of_creation: str = ""
    registered_office_address: RegisteredOffice = Field(default_factory=RegisteredOffice)
    sic_codes: list[str] = Field(default_factory=list)
    jurisdiction: str = ""
    last_full_members_list_date: str = ""
    has_been_liquidated: bool = False
    has_insolvency_history: bool = False
    undeliverable_registered_office_address: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _auth_headers() -> dict:
    """Build Basic-Auth headers for Companies House (API key as username)."""
    key = SETTINGS.COMPANIES_HOUSE_API_KEY
    if not key:
        raise HTTPException(status_code=500, detail="Companies House API key not configured")
    import base64
    credentials = base64.b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


def _build_search_item(raw: dict) -> CompanySearchItem:
    """Map a raw Companies House search hit → CompanySearchItem."""
    addr = raw.get("address", {}) or {}
    snippet = ", ".join(
        filter(None, [
            addr.get("address_line_1", ""),
            addr.get("locality", ""),
            addr.get("postal_code", ""),
        ])
    )
    return CompanySearchItem(
        company_number=raw.get("company_number", ""),
        title=raw.get("title", ""),
        company_status=raw.get("company_status", ""),
        company_type=raw.get("company_type", ""),
        address_snippet=snippet,
        date_of_creation=raw.get("date_of_creation", ""),
        description=raw.get("description", ""),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/search", response_model=CompanySearchResponse)
async def search_companies(
    q: str = Query(..., min_length=2, description="Company name or number to search"),
    max_results: int = Query(10, ge=1, le=50, description="Max results to return"),
):
    """
    Search UK companies by name or registration number.

    Calls ``GET /search/companies`` on the Companies House API and returns
    a slimmed-down list suitable for an autocomplete dropdown.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SETTINGS.COMPANIES_HOUSE_BASE_URL}/search/companies",
                params={"q": q, "items_per_page": max_results},
                headers=_auth_headers(),
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=500, detail="Invalid Companies House API key")
            resp.raise_for_status()
            data = resp.json()

        # Build results, excluding dissolved/liquidated companies
        items = [
            _build_search_item(hit)
            for hit in data.get("items", [])
            if hit.get("company_status") not in ("dissolved", "liquidation", "converted-closed")
        ]
        return CompanySearchResponse(
            items=items,
            total_results=data.get("total_results", len(items)),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Companies House search failed: {exc}")
        raise HTTPException(status_code=502, detail="Companies House API unavailable")


@router.get("/company/{company_number}", response_model=CompanyProfile)
async def get_company_profile(company_number: str):
    """
    Fetch the full profile for a single company.

    Calls ``GET /company/{companyNumber}`` on the Companies House API.
    Useful to pre-fill the registration form after the user selects a company.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SETTINGS.COMPANIES_HOUSE_BASE_URL}/company/{company_number}",
                headers=_auth_headers(),
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Company {company_number} not found")
            if resp.status_code == 401:
                raise HTTPException(status_code=500, detail="Invalid Companies House API key")
            resp.raise_for_status()
            data = resp.json()

        office = data.get("registered_office_address", {}) or {}
        return CompanyProfile(
            company_number=data.get("company_number", company_number),
            company_name=data.get("company_name", ""),
            company_status=data.get("company_status", ""),
            company_type=data.get("type", ""),
            date_of_creation=data.get("date_of_creation", ""),
            registered_office_address=RegisteredOffice(
                address_line_1=office.get("address_line_1", ""),
                address_line_2=office.get("address_line_2", ""),
                locality=office.get("locality", ""),
                postal_code=office.get("postal_code", ""),
                country=office.get("country", ""),
            ),
            sic_codes=data.get("sic_codes", []),
            jurisdiction=data.get("jurisdiction", ""),
            last_full_members_list_date=data.get("last_full_members_list_date", ""),
            has_been_liquidated=data.get("has_been_liquidated", False),
            has_insolvency_history=data.get("has_insolvency_history", False),
            undeliverable_registered_office_address=data.get(
                "undeliverable_registered_office_address", False
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Companies House profile fetch failed: {exc}")
        raise HTTPException(status_code=502, detail="Companies House API unavailable")
