"""AiFi integration exception hierarchy."""
from __future__ import annotations


class AiFiError(Exception):
    """Base exception for all AiFi integration errors."""

    def __init__(self, message: str, status_code: int | None = None, detail: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {}


class AiFiAuthError(AiFiError):
    """Raised on 401 / 403 responses from AiFi (invalid or missing token)."""


class AiFiNotFoundError(AiFiError):
    """Raised on 404 responses from AiFi."""


class AiFiValidationError(AiFiError):
    """Raised on 422 responses from AiFi (request body failed AiFi validation)."""


class AiFiServerError(AiFiError):
    """Raised on 5xx responses from AiFi."""


class AiFiTimeoutError(AiFiError):
    """Raised when a request to AiFi times out."""


class AiFiConnectionError(AiFiError):
    """Raised when a network-level error prevents reaching AiFi."""
