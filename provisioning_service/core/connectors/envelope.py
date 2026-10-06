"""
Source envelope — one per ingested object (deck slide 15).

Every record that crosses the adapter boundary is wrapped in an envelope:
identity · version · unaltered payload · extraction metadata · integrity.
The envelope is the evidence: any canonical match must be reproducible
from it (hash + adapter version + extraction time).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def content_hash(payload: Dict[str, Any]) -> str:
    """Stable SHA-256 over the unaltered source payload."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SourceEnvelope(BaseModel):
    """Standard wrapper for every object read from a source system."""

    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str                              # ties to the sync run / request
    connection_id: str
    provider_code: str
    adapter_version: str

    # Identity
    object_type: str                                 # product | supplier | org_dimension | location | supplier_product
    external_id: str                                 # source-native id (evidence, never mutated)

    # Payload + integrity
    raw_payload: Dict[str, Any]                      # unaltered source record
    payload_hash: str                                # sha256 of raw_payload
    schema_version: Optional[str] = None             # provider schema/api version if known

    # Extraction metadata
    extracted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extraction_method: str = "snapshot"              # snapshot | incremental | manual
    high_water_mark: Optional[str] = None            # cursor value at extraction (incremental)

    # Quality
    warnings: List[str] = []
    provenance: Dict[str, Any] = {}                  # e.g. {"suiteql": "SELECT ...", "page": 3}


def build_envelope(
    *,
    raw: Dict[str, Any],
    object_type: str,
    external_id: str,
    connection_id: str,
    provider_code: str,
    adapter_version: str,
    correlation_id: str,
    extraction_method: str = "snapshot",
    high_water_mark: Optional[str] = None,
    warnings: Optional[List[str]] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> SourceEnvelope:
    return SourceEnvelope(
        correlation_id=correlation_id,
        connection_id=connection_id,
        provider_code=provider_code,
        adapter_version=adapter_version,
        object_type=object_type,
        external_id=str(external_id),
        raw_payload=raw,
        payload_hash=content_hash(raw),
        extraction_method=extraction_method,
        high_water_mark=high_water_mark,
        warnings=warnings or [],
        provenance=provenance or {},
    )
