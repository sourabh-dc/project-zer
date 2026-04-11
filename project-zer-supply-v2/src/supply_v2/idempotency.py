from __future__ import annotations

from typing import Optional

from fastapi import Header


def get_idempotency_key(x_idempotency_key: Optional[str] = Header(default=None)) -> Optional[str]:
    return x_idempotency_key
