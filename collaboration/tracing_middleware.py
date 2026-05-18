"""
FastAPI OpenTelemetry Tracing Middleware.

Creates a span for each HTTP request with proper context extraction.
"""

from __future__ import annotations

import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .tracing import (
    get_tracer,
    extract_trace_context,
    init_tracing,
)


class OTelTracingMiddleware(BaseHTTPMiddleware):
    """
    OpenTelemetry tracing middleware for FastAPI.

    Creates a server span for each incoming HTTP request.
    Extracts W3C Trace Context from incoming headers.
    """

    async def dispatch(self, request: Request, call_next):
        # Ensure tracing is initialized
        init_tracing()
        tracer = get_tracer()

        if tracer is None:
            return await call_next(request)

        from opentelemetry.trace import SpanKind, Status, StatusCode

        # Extract trace context from incoming headers
        headers = dict(request.headers)
        ctx = extract_trace_context(headers)

        # Create span name
        span_name = f"{request.method} {request.url.path}"

        with tracer.start_as_current_span(span_name, context=ctx, kind=SpanKind.SERVER) as span:
            if span:
                # Set request attributes
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.url", str(request.url))
                span.set_attribute("http.scheme", request.url.scheme)
                span.set_attribute("http.host", request.url.hostname or "")
                span.set_attribute("http.target", request.url.path)
                span.set_attribute("http.user_agent", request.headers.get("user-agent", ""))

                # Client socket info
                client = request.client
                if client:
                    span.set_attribute("http.client_ip", client.host or "")

            # Time the request
            start_time = time.perf_counter()

            try:
                response: Response = await call_next(request)
            except Exception as e:
                if span:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

            duration = time.perf_counter() - start_time

            if span:
                # Set response attributes
                span.set_attribute("http.status_code", response.status_code)
                span.set_attribute("http.response_duration_ms", duration * 1000)

                # Mark error if 5xx
                if response.status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR, "Server error"))
                elif response.status_code >= 400:
                    span.set_status(Status(StatusCode.ERROR, "Client error"))

            return response
