"""Security dependencies and authentication middleware (Task A13)."""

from __future__ import annotations

from fastapi import HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    header_key: str | None = Security(api_key_header),
) -> str | None:
    """Validate API Key if settings.API_KEY is configured.

    If settings.API_KEY is None or empty string, authentication is bypassed.
    Accepts key via 'X-API-Key' header or 'Authorization: Bearer <key>'.
    """
    configured_key = settings.API_KEY
    if not configured_key or not configured_key.strip():
        return None

    # Check X-API-Key header
    provided_key = header_key

    # Check Authorization: Bearer <key> fallback
    if not provided_key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()

    if not provided_key or provided_key != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

    return provided_key
