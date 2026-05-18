"""
OpenTelemetry Tracing for hermes-agent-collab.

Provides distributed tracing across all collaboration components.
Supports OTLP gRPC export, console export, and context propagation.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .config import CollabConfig, get_config

_log = logging.getLogger(__name__)

# Lazy import OpenTelemetry to allow optional dependency
_otel_available = False
_TracerProvider = None
_TraceProvider = None
_Tracer = None
_trace = None


def _ensure_otel():
    """Lazy import OpenTelemetry."""
    global _otel_available, _TracerProvider, _TraceProvider, _Tracer, _trace
    if _otel_available:
        return True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.trace import Tracer
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        _TracerProvider = TracerProvider
        _TraceProvider = TracerProvider
        _Tracer = Tracer
        _trace = trace
        _otel_available = True
        return True
    except ImportError:
        _log.warning("OpenTelemetry not installed. Tracing disabled.")
        return False


# ─── Tracing Config ────────────────────────────────────────────────────────────


@dataclass
class TracingConfig:
    """Tracing configuration."""
    enabled: bool = True
    service_name: str = "hermes-agent-collab"
    exporter: str = "console"  # "otlp" | "console" | "jaeger"
    otlp_endpoint: str = "http://localhost:4317"
    sample_rate: float = 1.0
    propagator: str = "tracecontext"


# ─── Global state ──────────────────────────────────────────────────────────────


_provider = None
_tracer = None
_initialized = False


# ─── Initialization ────────────────────────────────────────────────────────────


def init_tracing(config: CollabConfig | None = None) -> bool:
    """
    Initialize OpenTelemetry tracing.

    Returns True if tracing was initialized, False if OpenTelemetry is not available
    or if tracing is disabled.
    """
    global _provider, _tracer, _initialized

    if _initialized:
        return _tracer is not None

    _initialized = True

    cfg = config or get_config()

    tracing_enabled = getattr(cfg, "TRACING_ENABLED", True)
    if not tracing_enabled:
        _log.info("Tracing disabled by configuration")
        return False

    if not _ensure_otel():
        return False

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes

    service_name = getattr(cfg, "TRACING_SERVICE_NAME", "hermes-agent-collab")
    exporter_type = getattr(cfg, "TRACING_EXPORTER", "console")
    otlp_endpoint = getattr(cfg, "TRACING_OTLP_ENDPOINT", "http://localhost:4317")

    # Create resource
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: service_name,
        ResourceAttributes.SERVICE_VERSION: "1.0.0",
    })

    # Create provider
    provider = TracerProvider(resource=resource)

    # Add exporter
    if exporter_type == "console":
        exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
    elif exporter_type == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            _log.info(f"OTLP tracing enabled, exporting to {otlp_endpoint}")
        except ImportError:
            _log.warning("OTLP exporter not installed, falling back to console")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif exporter_type == "jaeger":
        try:
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter
            jaeger_exporter = JaegerExporter(
                agent_host_name="localhost",
                agent_port=6831,
            )
            provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
        except ImportError:
            _log.warning("Jaeger exporter not installed")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Set global provider
    from opentelemetry import trace
    trace.set_tracer_provider(provider)

    # Create tracer
    _tracer = trace.get_tracer(service_name)
    _provider = provider

    _log.info(f"Tracing initialized with {exporter_type} exporter")
    return True


def get_tracer():
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        init_tracing()
    return _tracer


# ─── Context Propagation ───────────────────────────────────────────────────────


def get_current_trace_id() -> str | None:
    """Get the current trace ID as a hex string."""
    if not _ensure_otel():
        return None
    from opentelemetry import trace
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().trace_id, "032x")
    return None


def get_current_span_id() -> str | None:
    """Get the current span ID as a hex string."""
    if not _ensure_otel():
        return None
    from opentelemetry import trace
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().span_id, "016x")
    return None


def inject_trace_context(carrier: dict[str, str]) -> dict[str, str]:
    """
    Inject current trace context into a carrier dict (e.g., HTTP headers).

    Uses W3C Trace Context standard.
    """
    if not _ensure_otel():
        return carrier
    from opentelemetry.propagation import get_global_textmap
    propagator = get_global_textmap()
    propagator.inject(carrier)
    return carrier


def extract_trace_context(carrier: dict[str, str]):
    """Extract trace context from a carrier dict."""
    if not _ensure_otel():
        return None
    from opentelemetry.propagation import get_global_textmap
    propagator = get_global_textmap()
    return propagator.extract(carrier)


# ─── Span Decorators & Helpers ─────────────────────────────────────────────────


@contextmanager
def create_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    kind: str = "internal",
):
    """
    Context manager to create a span.

    Usage:
        with create_span("task.execute", {"task_id": "123"}) as span:
            # do work
            span.set_attribute("result", "success")
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry.trace import SpanKind
    kind_map = {
        "server": SpanKind.SERVER,
        "client": SpanKind.CLIENT,
        "producer": SpanKind.PRODUCER,
        "consumer": SpanKind.CONSUMER,
        "internal": SpanKind.INTERNAL,
    }
    span_kind = kind_map.get(kind, SpanKind.INTERNAL)

    with tracer.start_as_current_span(name, kind=span_kind) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(_trace.Status(_trace.StatusCode.ERROR, str(e)))
            raise


async def create_span_async(
    name: str,
    attributes: dict[str, Any] | None = None,
    kind: str = "internal",
):
    """
    Async context manager to create a span.
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry.trace import SpanKind
    kind_map = {
        "server": SpanKind.SERVER,
        "client": SpanKind.CLIENT,
        "producer": SpanKind.PRODUCER,
        "consumer": SpanKind.CONSUMER,
        "internal": SpanKind.INTERNAL,
    }
    span_kind = kind_map.get(kind, SpanKind.INTERNAL)

    async with tracer.start_as_current_span(name, kind=span_kind) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(_trace.Status(_trace.StatusCode.ERROR, str(e)))
            raise


# ─── Span helpers for common operations ────────────────────────────────────────


def add_task_span_attributes(
    span,
    task_id: str,
    priority: str | None = None,
    complexity: str | None = None,
):
    """Add common task attributes to a span."""
    if span is None:
        return
    span.set_attribute("task.id", task_id)
    if priority:
        span.set_attribute("task.priority", priority)
    if complexity:
        span.set_attribute("task.complexity", complexity)


def add_llm_span_attributes(
    span,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
):
    """Add common LLM call attributes to a span."""
    if span is None:
        return
    span.set_attribute("llm.model", model)
    if prompt_tokens is not None:
        span.set_attribute("llm.prompt_tokens", prompt_tokens)
    if completion_tokens is not None:
        span.set_attribute("llm.completion_tokens", completion_tokens)
    if prompt_tokens and completion_tokens:
        span.set_attribute("llm.total_tokens", prompt_tokens + completion_tokens)


def add_db_span_attributes(
    span,
    statement: str | None = None,
    operation: str | None = None,
    rows_affected: int | None = None,
):
    """Add common database attributes to a span."""
    if span is None:
        return
    span.set_attribute("db.system", "postgresql")
    if operation:
        span.set_attribute("db.operation", operation)
    if statement:
        # Truncate long statements
        span.set_attribute("db.statement", statement[:500])
    if rows_affected is not None:
        span.set_attribute("db.rows_affected", rows_affected)


def add_channel_span_attributes(
    span,
    adapter: str,
    event_type: str,
):
    """Add common channel/event attributes to a span."""
    if span is None:
        return
    span.set_attribute("channel.adapter", adapter)
    span.set_attribute("channel.event_type", event_type)


# ─── Tracing Middleware for FastAPI ───────────────────────────────────────────


async def tracing_middleware(request, call_next):
    """
    FastAPI middleware that creates a span for each HTTP request.

    This is a simplified version - the actual middleware is in tracing_middleware.py.
    """
    tracer = get_tracer()
    if tracer is None:
        return await call_next(request)

    from opentelemetry.trace import SpanKind

    # Extract trace context from incoming headers
    propagator = extract_trace_context(dict(request.headers))

    span_name = f"{request.method} {request.url.path}"
    with tracer.start_as_current_span(
        span_name,
        kind=SpanKind.SERVER,
        context=propagator,
    ) as span:
        if span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", request.url.path)
            span.set_attribute("http.host", request.url.hostname or "")

        response = await call_next(request)

        if span:
            span.set_attribute("http.status_code", response.status_code)

        return response


# ─── Shutdown ─────────────────────────────────────────────────────────────────


async def shutdown_tracing():
    """Flush and shutdown the tracing provider."""
    global _provider, _tracer, _initialized
    if _provider is not None:
        try:
            await _provider.shutdown()
        except Exception as e:
            _log.warning(f"Error shutting down tracing provider: {e}")
        _provider = None
        _tracer = None
        _initialized = False
