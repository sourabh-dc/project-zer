"""
Google Address & Location APIs — proxy around Google Places API (New)
and the Geocoding API.

Mirrors the Companies House pattern: the API key stays server-side and
the frontend gets slim, form-ready responses.

Endpoints:
  - GET /google/address/autocomplete  — suggestions as the user types
  - GET /google/address/place/{id}    — full address for a picked suggestion
  - GET /google/address/reverse       — address from coordinates
        ("use current location": browser Geolocation gives lat/lng,
        this turns them into a fillable address)

Note: autocomplete + place details use Places API (New) — the legacy
Places API is unavailable on Google Cloud projects created after
March 2025. Reverse geocoding stays on the Geocoding API.
"""
from __future__ import annotations

from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from provisioning_service.core.config import SETTINGS
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/google", tags=["google-geo"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class AddressSuggestion(BaseModel):
    """One autocomplete suggestion."""
    place_id: str
    description: str                    # full text, e.g. "10 Downing Street, London, UK"
    main_text: str = ""                 # bold part — "10 Downing Street"
    secondary_text: str = ""            # remainder — "London, UK"


class AddressSuggestionResponse(BaseModel):
    items: list[AddressSuggestion] = Field(default_factory=list)


class AddressDetails(BaseModel):
    """Structured, form-ready address with coordinates."""
    formatted_address: str = ""
    address_line_1: str = ""
    address_line_2: str = ""
    city: str = ""                      # locality / post town
    county: str = ""                    # administrative_area_level_2
    postal_code: str = ""
    country: str = ""
    country_code: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _api_key() -> str:
    key = SETTINGS.GOOGLE_MAPS_API_KEY
    if not key:
        raise HTTPException(status_code=500, detail="Google Maps API key not configured")
    return key


def _places_headers(field_mask: Optional[str] = None) -> dict:
    """Headers for Places API (New) — key header + optional field mask."""
    headers = {"X-Goog-Api-Key": _api_key(), "Content-Type": "application/json"}
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask
    return headers


def _component(components: list, type_name: str, short: bool = False) -> str:
    """Pull one component out of a Google address components array.

    Handles both shapes: legacy (long_name/short_name) and
    Places API (New) (longText/shortText).
    """
    for comp in components:
        if type_name in (comp.get("types") or []):
            if short:
                return comp.get("shortText") or comp.get("short_name", "")
            return comp.get("longText") or comp.get("long_name", "")
    return ""


def _build_address(result: dict) -> AddressDetails:
    """Map a geocode/place-details result → AddressDetails (both API shapes)."""
    components = result.get("address_components") or result.get("addressComponents") or []
    geometry = (result.get("geometry") or {}).get("location") or {}
    location = result.get("location") or {}  # Places API (New) top-level

    street_number = _component(components, "street_number")
    route = _component(components, "route")
    line_1 = " ".join(filter(None, [street_number, route]))

    # City: UK uses post_town; elsewhere locality
    city = (
        _component(components, "postal_town")
        or _component(components, "locality")
        or _component(components, "administrative_area_level_3")
    )

    return AddressDetails(
        formatted_address=result.get("formatted_address") or result.get("formattedAddress", ""),
        address_line_1=line_1,
        address_line_2=_component(components, "sublocality")
                       or _component(components, "sublocality_level_1"),
        city=city,
        county=_component(components, "administrative_area_level_2"),
        postal_code=_component(components, "postal_code"),
        country=_component(components, "country"),
        country_code=_component(components, "country", short=True),
        latitude=geometry.get("lat") or location.get("latitude"),
        longitude=geometry.get("lng") or location.get("longitude"),
    )


def _check_legacy_status(data: dict) -> None:
    """Translate Geocoding API status field into HTTP errors."""
    status = data.get("status")
    if status in ("OK", "ZERO_RESULTS"):
        return
    if status == "REQUEST_DENIED":
        logger.error(f"Google API request denied: {data.get('error_message')}")
        raise HTTPException(status_code=500, detail="Google API key invalid or Geocoding API not enabled")
    if status == "OVER_QUERY_LIMIT":
        raise HTTPException(status_code=429, detail="Google Maps quota exceeded — try again later")
    logger.error(f"Google API error: {status} {data.get('error_message')}")
    raise HTTPException(status_code=502, detail="Google Maps API error")


def _check_places_response(resp: httpx.Response) -> None:
    """Places API (New) signals errors via HTTP status, not a body field."""
    if resp.status_code == 200:
        return
    try:
        message = (resp.json().get("error") or {}).get("message", resp.text[:200])
    except Exception:
        message = resp.text[:200]
    logger.error(f"Places API (New) error {resp.status_code}: {message}")
    if resp.status_code == 403:
        raise HTTPException(status_code=500, detail="Google API key invalid or Places API (New) not enabled")
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Google Maps quota exceeded — try again later")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Place not found")
    raise HTTPException(status_code=502, detail="Google Places API error")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/address/autocomplete", response_model=AddressSuggestionResponse)
async def address_autocomplete(
    input: str = Query(..., min_length=3, description="Partial address the user is typing"),
    country: Optional[str] = Query(None, max_length=2, description="ISO country bias, e.g. gb"),
    max_results: int = Query(5, ge=1, le=10),
):
    """
    Address suggestions while the user types.

    Calls Places API (New) Autocomplete and returns slimmed-down items
    for a dropdown. Debounce client-side (~300ms) to save quota.
    """
    body: dict = {
        "input": input,
        "includedPrimaryTypes": ["street_address", "premise", "subpremise", "route"],
    }
    if country:
        body["includedRegionCodes"] = [country.lower()]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{SETTINGS.GOOGLE_PLACES_BASE_URL}/places:autocomplete",
                json=body,
                headers=_places_headers(),
            )
        _check_places_response(resp)
        data = resp.json()

        items = []
        for s in (data.get("suggestions") or [])[:max_results]:
            prediction = s.get("placePrediction") or {}
            fmt = prediction.get("structuredFormat") or {}
            items.append(AddressSuggestion(
                place_id=prediction.get("placeId", ""),
                description=(prediction.get("text") or {}).get("text", ""),
                main_text=(fmt.get("mainText") or {}).get("text", ""),
                secondary_text=(fmt.get("secondaryText") or {}).get("text", ""),
            ))
        return AddressSuggestionResponse(items=items)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Google autocomplete failed: {exc}")
        raise HTTPException(status_code=502, detail="Google Places API unavailable")


@router.get("/address/place/{place_id}", response_model=AddressDetails)
async def address_place_details(place_id: str):
    """
    Full structured address for a suggestion the user picked.

    Calls Places API (New) Place Details. Use this to fill the address
    form after the user selects from the autocomplete dropdown.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SETTINGS.GOOGLE_PLACES_BASE_URL}/places/{place_id}",
                headers=_places_headers("formattedAddress,addressComponents,location"),
            )
        _check_places_response(resp)
        return _build_address(resp.json())
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Google place details failed: {exc}")
        raise HTTPException(status_code=502, detail="Google Places API unavailable")


@router.get("/address/reverse", response_model=AddressDetails)
async def address_reverse_geocode(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
):
    """
    Reverse-geocode coordinates into a structured address.

    Powers "use current location": the browser's Geolocation API
    supplies lat/lng, this returns the fillable address.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SETTINGS.GOOGLE_MAPS_BASE_URL}/geocode/json",
                params={"latlng": f"{lat},{lng}", "key": _api_key()},
            )
            resp.raise_for_status()
            data = resp.json()

        _check_legacy_status(data)
        results = data.get("results") or []
        if not results:
            raise HTTPException(status_code=404, detail="No address found for these coordinates")
        return _build_address(results[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Google reverse geocode failed: {exc}")
        raise HTTPException(status_code=502, detail="Google Geocoding API unavailable")
