"""
Distributed tracing with OpenTelemetry + Jaeger.
Provides full-stack observability for hermes-agent-collab.
"""

from __future__ import annotations

import functools
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — opentelemetry is optional
# ---------------------------------------------------------------------------

_tracer = None
_provider = None
_initialized = False
_init_lock = threading.Lock()


def _lazy_import():
    global _tracer, _provider, _initialized
    if _initialized:
        return True
    with _init_lock:
        if _initialized:
            return _tracer is not None
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.trace import Status, StatusCode
            _initialized = True
            return True
        except ImportError:
            _initialized = True
            return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class TracingManager:
    """
    Manages OpenTelemetry tracers for hermes-agent-collab.
    Supports Jaeger OTLP exporter with configurable sampling.
    """

    def __init__(self):
        self._tracer = None
        self._enabled = False
        self._service_name = "hermes-agent-collab"
        self._endpoint = "http://localhost:6831"

    def init(
        self,
        service_name: str = "hermes-agent-collab",
        endpoint: str = "http://localhost:6831",
        sampling_ratio: float = 1.0,
    ) -> bool:
        """
        Initialize the tracer provider with Jaeger OTLP exporter.

        Args:
            service_name: Name of this service in Jaeger UI
            endpoint: Jaeger OTLP collector endpoint (default: localhost:6831)
            sampling_ratio: Fraction of spans to capture (1.0 = 100%, 0.1 = 10%)

        Returns:
            True if tracing was initialized successfully, False if opentelemetry not installed
        """
        if not _lazy_import():
            _log.warning("OpenTelemetry not installed — tracing disabled")
            return False

        global _tracer, _provider

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider, TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, AlwaysOn, AlwaysOff
            from opentelemetry.trace import Status, StatusCode

            # Configure sampler
            if sampling_ratio >= 1.0:
                sampler = AlwaysOn()
            elif sampling_ratio <= 0.0:
                sampler = AlwaysOff()
            else:
                sampler = TraceIdRatioBased(sampling_ratio)

            # Create resource
            resource = Resource(attributes={
                SERVICE_NAME: service_name,
                "service.version": "1.0.0",
                "deployment.environment": "development",
            })

            # Create provider with sampler
            _provider = TracerProvider(resource=resource, sampler=sampler)

            # Create OTLP exporter
            otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)

            # Register processor
            _provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

            # Set global provider
            trace.set_tracer_provider(_provider)

            # Get tracer
            _tracer = trace.get_tracer(__name__)

            self._tracer = _tracer
            self._enabled = True
            self._service_name = service_name
            self._endpoint = endpoint

            _log.info("Tracing initialized: service=%s endpoint=%s sampling=%.0f%%",
                      service_name, endpoint, sampling_ratio * 100)
            return True

        except ImportError:
            _log.warning("OpenTelemetry packages not fully installed — tracing disabled")
            return False
        except Exception as e:
            _log.error("Failed to initialize tracing: %s", e)
            return False

    def is_enabled(self) -> bool:
        return self._enabled

    def start_span(
        self,
        name: str,
        attrs: dict[str, Any] | None = None,
        kind: str = "internal",
    ) -> Any | None:
        """
        Start a new span.

        Args:
            name: Name of the span (e.g. "task.execute")
            attrs: Optional attributes to attach
            kind: Span kind — "internal", "server", "client", "producer", "consumer"

        Returns:
            Span object if enabled, None otherwise
        """
        if not self._enabled:
            return None

        from opentelemetry import trace
        from opentelemetry.trace import SpanKind

        kind_map = {
            "internal": SpanKind.INTERNAL,
            "server": SpanKind.SERVER,
            "client": SpanKind.CLIENT,
            "producer": SpanKind.PRODUCER,
            "consumer": SpanKind.CONSUMER,
        }
        span_kind = kind_map.get(kind, SpanKind.INTERNAL)

        span = self._tracer.start_span(name, kind=span_kind)
        if attrs:
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool)) else v)

        return span

    def end_span(self, span: Any, status: str = "OK", error_message: str | None = None) -> None:
        """End a span with optional error status."""
        if not self._enabled or span is None:
            return

        from opentelemetry.trace import Status, StatusCode

        if status == "ERROR":
            span.set_status(Status(StatusCode.ERROR, error_message or ""))
            if error_message:
                span.record_exception(Exception(error_message))
        else:
            span.set_status(Status(StatusCode.OK))

        span.end()

    def record_exception(self, span: Any, exc: BaseException) -> None:
        """Record an exception on a span."""
        if not self._enabled or span is None:
            return
        span.record_exception(exc)
        span.set_status(
            __import__("opentelemetry").trace.Status(__import__("opentelemetry").trace.StatusCode.ERROR)
        )

    def add_attrs(self, span: Any, attrs: dict[str, Any]) -> None:
        """Add attributes to an existing span."""
        if not self._enabled or span is None:
            return
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool)) else v)

    def get_current_span(self) -> Any | None:
        """Get the current active span."""
        if not self._enabled:
            return None
        from opentelemetry import trace
        return trace.get_current_span()

    @contextmanager
    def span(
        self,
        name: str,
        attrs: dict[str, Any] | None = None,
        kind: str = "internal",
    ):
        """
        Context manager for creating a span.

        Usage:
            with tracing.span("task.execute", {"task_id": "123"}):
                execute_task()
        """
        span = self.start_span(name, attrs, kind)
        try:
            yield span
            self.end_span(span, status="OK")
        except Exception as e:
            self.record_exception(span, e)
            self.end_span(span, status="ERROR", error_message=str(e))
            raise


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def with_trace(
    name: str | None = None,
    attrs: dict[str, Any] | None = None,
    kind: str = "internal",
):
    """
    Decorator to trace a function.

    Usage:
        @with_trace("task.execute")
        def execute_task(task_id: str):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            span_name = name or f"{fn.__module__}.{fn.__name__}"
            span = _tracer.start_span(span_name) if _tracer else None
            if attrs:
                for k, v in attrs.items():
                    if v is not None:
                        span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool)) else v)
            try:
                result = fn(*args, **kwargs)
                if span:
                    from opentelemetry.trace import Status, StatusCode
                    span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                if span:
                    span.record_exception(e)
                    from opentelemetry.trace import Status, StatusCode
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
            finally:
                if span:
                    span.end()
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

_tracing_manager: TracingManager | None = None


def get_tracing_manager() -> TracingManager:
    global _tracing_manager
    if _tracing_manager is None:
        _tracing_manager = TracingManager()
    return _tracing_manager


# ---------------------------------------------------------------------------
# Convenience decorators for common operations
# ---------------------------------------------------------------------------

def trace_http(method: str, path_template: str):
    """Decorator for HTTP request tracing."""
    return with_trace(f"http.{method.lower()}", {"http.method": method, "http.path_template": path_template})


def trace_db(operation: str, table: str):
    """Decorator for database operation tracing."""
    return with_trace(f"db.{operation}", {"db.operation": operation, "db.table": table})


def trace_agent(operation: str):
    """Decorator for agent operation tracing."""
    return with_trace(f"agent.{operation}", {"agent.operation": operation})


def trace_task(operation: str):
    """Decorator for task operation tracing."""
    return with_trace(f"task.{operation}", {"task.operation": operation})
