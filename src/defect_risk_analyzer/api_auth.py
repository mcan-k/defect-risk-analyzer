"""
API key authentication for the Predictive Defect Analysis Engine.

All endpoints except /health require a valid X-API-Key header.
The key is auto-generated on first run and saved to .env.
"""

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from defect_risk_analyzer import config

# Header-based API key scheme
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """
    FastAPI dependency that validates the X-API-Key header.

    Usage:
        @app.post("/analyze", dependencies=[Depends(require_api_key)])
        async def analyze(...): ...

    Raises:
        HTTPException 503 if the server has no API key configured.
        HTTPException 401 if the header is missing.
        HTTPException 403 if the key is invalid.
    """
    # Checked before anything else: an empty config.API_KEY would make the
    # comparison below succeed for a request sending an empty X-API-Key
    # header, silently bypassing authentication. A server without a key is
    # misconfigured, not unauthenticated — reject every request outright.
    expected_key = config.API_KEY
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server has no API key configured. Set API_KEY in .env.",
        )

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is missing.",
        )

    # compare_digest, not `!=`. The two accept and refuse exactly the same keys,
    # so no test of behaviour can tell them apart — what differs is how long
    # they take to disagree. `!=` on str stops at the first differing character,
    # which leaks the length of the matching prefix to anyone who can time the
    # response, and that is enough to recover a key one character at a time.
    #
    # Both operands are str here: `expected_key` was checked non-empty above and
    # `api_key` comes from the header as str, so compare_digest's "both ASCII
    # str or both bytes-like" requirement holds without an encode step.
    #
    # The rule is pinned in tests/test_api_auth.py by a source guard rather than
    # a timing measurement — see that module's docstring for why.
    if not secrets.compare_digest(api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key
