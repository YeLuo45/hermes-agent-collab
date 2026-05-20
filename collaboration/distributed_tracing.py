"""
Distributed tracing with OpenTelemetry + Jaeger.
Provides full-stack observability for hermes-agent-collab.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

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


# -----------------------------------------------------------------------------
# In-memory Trace Store (for API access without external backend)
# -----------------------------------------------------------------------------


@dataclass
class StoredSpan:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    service_name: str
    start_time: float
    end_time: float
    duration_ms: float
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status_code: str = "OK"
    status_message: str = ""
    span_kind: str = "internal"

    def to_dict(self) -> dict:
        return asdict(self)


class InMemoryTraceStore:
    """
    Thread-safe in-memory store for recent spans.
    Used by the REST API to query traces without Jaeger.
    Configurable max size with LRU eviction.
    """

    def __init__(self, max_traces: int = 10000, max_spans_per_trace: int = 1000):
        self._traces: OrderedDict[str, list[StoredSpan]] = OrderedDict()
        self._lock = threading.RLock()
        self._max_traces = max_traces
        self._max_spans_per_trace = max_spans_per_trace
        self._stats = {
            "total_traces": 0,
            "total_spans": 0,
            "slow_spans": 0,
        }

    def store_span(self, span: StoredSpan) -> None:
        with self._lock:
            tid = span.trace_id
            if tid not in self._traces:
                self._traces[tid] = []
                self._stats["total_traces"] += 1
            self._traces[tid].append(span)
            self._stats["total_spans"] += 1

            # Trim if too many spans for this trace
            if len(self._traces[tid]) > self._max_spans_per_trace:
                self._traces[tid] = self._traces[tid][-self._max_spans_per_trace:]

            # LRU eviction
            while len(self._traces) > self._max_traces:
                self._traces.popitem(last=False)

    def get_trace(self, trace_id: str) -> list[StoredSpan]:
        with self._lock:
            spans = self._traces.get(trace_id, [])
            return sorted(spans, key=lambda s: s.start_time)

    def list_recent_traces(self, limit: int = 100) -> list[dict]:
        with self._lock:
            result = []
            for tid, spans in reversed(list(self._traces.items())):
                if not spans:
                    continue
                root = next((s for s in spans if s.parent_span_id is None), spans[0])
                result.append({
                    "trace_id": tid,
                    "name": root.name,
                    "start_time": root.start_time,
                    "duration_ms": root.duration_ms,
                    "span_count": len(spans),
                    "status": root.status_code,
                })
                if len(result) >= limit:
                    break
            return result

    def get_slow_spans(self, threshold_ms: float = 1000.0, limit: int = 50) -> list[StoredSpan]:
        with self._lock:
            slow = []
            for spans in self._traces.values():
                for span in spans:
                    if span.duration_ms > threshold_ms:
                        slow.append(span)
                        self._stats["slow_spans"] += 1
            slow.sort(key=lambda s: s.duration_ms, reverse=True)
            return slow[:limit]

    def get_stats(self) -> dict:
        with self._lock:
            return {
                **self._stats,
                "unique_traces": len(self._traces),
                "avg_spans_per_trace": (
                    self._stats["total_spans"] / self._stats["total_traces"]
                    if self._stats["total_traces"] > 0 else 0
                ),
            }

    def annotate_span(self, trace_id: str, span_id: str, event_name: str, attrs: dict[str, Any] | None = None) -> bool:
        with self._lock:
            spans = self._traces.get(trace_id, [])
            for span in spans:
                if span.span_id == span_id:
                    span.events.append({
                        "name": event_name,
                        "timestamp": time.time(),
                        "attributes": attrs or {},
                    })
                    return True
        return False


# ─── Global trace store ────────────────────────────────────────────────────────

_trace_store: Optional[InMemoryTraceStore] = None


def get_trace_store() -> InMemoryTraceStore:
    global _trace_store
    if _trace_store is None:
        _trace_store = InMemoryTraceStore()
    return _trace_store


# -----------------------------------------------------------------------------
# Span-to-Traces Bridge
# -----------------------------------------------------------------------------


class TraceCollector:
    """
    Collects spans from the OTel tracer and stores them in the InMemoryTraceStore.
    Also exposes slow-span tracking and stats.
    """

    def __init__(self, slow_threshold_ms: float = 1000.0):
        self._store = get_trace_store()
        self._slow_threshold_ms = slow_threshold_ms
        self._lock = threading.Lock()

    def collect_span(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str],
        name: str,
        start_time: float,
        end_time: float,
        attrs: dict[str, Any],
        events: list[dict],
        status_code: str,
        status_message: str,
        span_kind: str,
        service_name: str,
    ) -> None:
        duration_ms = (end_time - start_time) * 1000

        stored = StoredSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            service_name=service_name,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            attributes=attrs,
            events=events,
            status_code=status_code,
            status_message=status_message,
            span_kind=span_kind,
        )
        self._store.store_span(stored)

    def get_recent_traces(self, limit: int = 100) -> list[dict]:
        return self._store.list_recent_traces(limit)

    def get_trace(self, trace_id: str) -> list[StoredSpan]:
        return self._store.get_trace(trace_id)

    def get_slow_spans(self, threshold_ms: float | None = None, limit: int = 50) -> list[StoredSpan]:
        return self._store.get_slow_spans(threshold_ms or self._slow_threshold_ms, limit)

    def get_stats(self) -> dict:
        return self._store.get_stats()

    def annotate_span(self, trace_id: str, span_id: str, event_name: str, attrs: dict[str, Any] | None = None) -> bool:
        return self._store.annotate_span(trace_id, span_id, event_name, attrs)


# ─── Global collector ─────────────────────────────────────────────────────────

_trace_collector: Optional[TraceCollector] = None


def get_trace_collector() -> TraceCollector:
    global _trace_collector
    if _trace_collector is None:
        _trace_collector = TraceCollector()
    return _trace_collector


# -----------------------------------------------------------------------------
# Enhanced TracingManager methods
# -----------------------------------------------------------------------------


def generate_trace_id() -> str:
    """Generate a new unique trace ID."""
    return uuid.uuid4().hex[:16]


def generate_span_id() -> str:
    """Generate a new unique span ID."""
    return uuid.uuid4().hex[:8]


class EnhancedTracingManager(TracingManager):
    """
    Extended TracingManager with:
    - In-memory trace store for API queries
    - Span event recording
    - Slow span tracking
    - Manual annotation support
    """

    def __init__(self):
        super().__init__()
        self._collector = get_trace_collector()
        self._slow_threshold_ms = 1000.0
        self._capture_spans_in_memory = True

    def set_slow_threshold(self, threshold_ms: float) -> None:
        """Set threshold for slow span detection (ms)."""
        self._slow_threshold_ms = threshold_ms
        self._collector = TraceCollector(slow_threshold_ms=threshold_ms)

    def set_capture_in_memory(self, enabled: bool) -> None:
        """Enable/disable in-memory span capture."""
        self._capture_spans_in_memory = enabled

    def start_span(
        self,
        name: str,
        attrs: dict[str, Any] | None = None,
        kind: str = "internal",
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> Any | None:
        """
        Start a new span with enhanced tracking.
        If trace_id is None, generates a new one.
        """
        if not self._enabled:
            return None

        from opentelemetry import trace
        from opentelemetry.trace import SpanKind, Link

        kind_map = {
            "internal": SpanKind.INTERNAL,
            "server": SpanKind.SERVER,
            "client": SpanKind.CLIENT,
            "producer": SpanKind.PRODUCER,
            "consumer": SpanKind.CONSUMER,
        }
        span_kind = kind_map.get(kind, SpanKind.INTERNAL)

        # Generate IDs
        tid = trace_id or generate_trace_id()
        sid = generate_span_id()

        # Build links if trace_id provided
        links = []
        if trace_id and parent_span_id:
            from opentelemetry.trace import SpanContext
            # Create linked context for child traces
            links = []

        span = self._tracer.start_span(
            name,
            kind=span_kind,
            links=links if links else None,
        )

        # Set trace_id/span_id as attributes
        span.set_attribute("trace.id", tid)
        span.set_attribute("span.id", sid)

        if attrs:
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool)) else v)

        return span

    def end_span(
        self,
        span: Any,
        status: str = "OK",
        error_message: str | None = None,
    ) -> None:
        """End a span and store it in the in-memory collector."""
        if not self._enabled or span is None:
            return

        from opentelemetry.trace import Status, StatusCode

        if status == "ERROR":
            span.set_status(Status(StatusCode.ERROR, error_message or ""))
            if error_message:
                span.record_exception(Exception(error_message))
        else:
            span.set_status(Status(StatusCode.OK))

        # Collect into in-memory store
        if self._capture_spans_in_memory:
            try:
                ctx = span.get_span_context()
                trace_id = format(ctx.trace_id, '032x') if ctx.trace_id else ""
                span_id = format(ctx.span_id, '016x') if ctx.span_id else ""
                parent_span_id = format(ctx.parent_span_id, '016x') if ctx.parent_span_id else None

                start_time = self._span_start_time(span)
                end_time = time.time()
                attrs = dict(span.attributes) if hasattr(span, "attributes") else {}
                events = [
                    {"name": e.name, "timestamp": e.timestamp, "attributes": dict(e.attributes)}
                    for e in (span.events or [])
                ]

                self._collector.collect_span(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    name=span.name,
                    service_name=self._service_name,
                    start_time=start_time,
                    end_time=end_time,
                    attrs=attrs,
                    events=events,
                    status_code=status,
                    status_message=error_message or "",
                    span_kind=span.kind.name.lower() if hasattr(span, "kind") else "internal",
                )
            except Exception as e:
                _log.debug("Failed to collect span to in-memory store: %s", e)

        span.end()

    def _span_start_time(self, span: Any) -> float:
        """Get approximate start time from span."""
        try:
            if hasattr(span, "start_time"):
                return span.start_time
            return time.time() - (span.duration_ms / 1000) if hasattr(span, "duration_ms") else time.time()
        except Exception:
            return time.time()

    def add_span_event(self, span: Any, name: str, attrs: dict[str, Any] | None = None) -> None:
        """Add a named event to a span."""
        if not self._enabled or span is None:
            return
        span.add_event(name, attrs=attrs or {})

    def record_exception(self, span: Any, exc: BaseException) -> None:
        """Record an exception on a span."""
        if not self._enabled or span is None:
            return
        span.record_exception(exc)
        from opentelemetry.trace import Status, StatusCode
        span.set_status(Status(StatusCode.ERROR, str(exc)))

    def get_recent_traces(self, limit: int = 100) -> list[dict]:
        """Get recent traces from in-memory store."""
        return self._collector.get_recent_traces(limit)

    def get_trace(self, trace_id: str) -> list[StoredSpan]:
        """Get all spans for a trace."""
        return self._collector.get_trace(trace_id)

    def get_slow_spans(self, threshold_ms: float | None = None, limit: int = 50) -> list[StoredSpan]:
        """Get slow spans above threshold."""
        return self._collector.get_slow_spans(threshold_ms, limit)

    def get_trace_stats(self) -> dict:
        """Get tracing statistics."""
        return self._collector.get_stats()

    def annotate_span(self, trace_id: str, span_id: str, event_name: str, attrs: dict[str, Any] | None = None) -> bool:
        """Manually annotate a span with an event."""
        return self._collector.annotate_span(trace_id, span_id, event_name, attrs)

    @contextmanager
    def span(
        self,
        name: str,
        attrs: dict[str, Any] | None = None,
        kind: str = "internal",
        trace_id: str | None = None,
    ):
        """
        Enhanced context manager for creating a span.

        Usage:
            with tracing.span("task.execute", {"task_id": "123"}, trace_id=parent_trace_id):
                execute_task()
        """
        span = self.start_span(name, attrs, kind, trace_id=trace_id)
        try:
            yield span
            self.end_span(span, status="OK")
        except Exception as e:
            self.record_exception(span, e)
            self.end_span(span, status="ERROR", error_message=str(e))
            raise


# Replace the global tracing manager with enhanced version
def get_tracing_manager() -> EnhancedTracingManager:
    global _tracing_manager
    if _tracing_manager is None:
        _tracing_manager = EnhancedTracingManager()
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
