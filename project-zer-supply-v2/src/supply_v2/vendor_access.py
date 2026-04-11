from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _secret() -> str:
    return os.environ.get("SUPPLY_V2_VENDOR_LINK_SECRET", "local-vendor-link-secret")


def issue_vendor_token(*, tenant_id: str, vendor_id: str, po_id: str, ttl_seconds: int = 86400) -> str:
    payload = {
        "tenant_id": tenant_id,
        "vendor_id": vendor_id,
        "po_id": po_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(_secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_vendor_token(token: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid vendor token") from exc
    expected = hmac.new(_secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid vendor token signature")
    padded = body + "=" * (-len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("vendor token expired")
    return payload
