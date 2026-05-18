"""
FastAPI Rate Limiting Middleware for hermes-agent-collab.

Applies rate limiting to all /api/ endpoints based on API key and endpoint.
"""

from __future__ import annotations

import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import get_config
from .rate_limiter import RateLimitExceeded, get_rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that enforces rate limits on incoming requests.

    Checks rate limits in order:
    1. Global limit
    2. Per-API-Key limit
    3. Per-Endpoint limit
    4. Burst capacity (Token Bucket)

    Adds rate limit headers to all responses:
    - X-RateLimit-Limit
    - X-RateLimit-Remaining
    - X-RateLimit-Reset
    """

    # Paths to exclude from rate limiting
    EXCLUDED_PATHS = {
        "/",
        "/health",
        "/monitor/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    async def dispatch(self, request: Request, call_next):
        # Skip excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Only rate limit /api/ endpoints
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Get API key from header
        config = get_config()
        api_key_header = config.API_KEY_HEADER
        api_key = request.headers.get(api_key_header)

        # Get endpoint identifier (use path template if available)
        endpoint = request.url.path

        # Check rate limit
        limiter = get_rate_limiter(config)
        try:
            limit, remaining, reset_ts = await limiter.check(api_key, endpoint)

            # Process request
            response: Response = await call_next(request)

            # Add rate limit headers
            if limit > 0:
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
                response.headers["X-RateLimit-Reset"] = str(reset_ts)

            return response

        except RateLimitExceeded as e:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": str(e),
                    "limit": e.limit,
                    "retry_after": e.retry_after,
                    "scope": e.scope,
                    "upgrade": "Contact support for higher limits",
                },
                headers={
                    "X-RateLimit-Limit": str(e.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + e.retry_after),
                    "Retry-After": str(e.retry_after),
                    "Content-Type": "application/json",
                },
            )
