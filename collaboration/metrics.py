"""Prometheus metrics registry and collectors for hermes-agent-collab.

Provides a singleton MetricsRegistry with counter/gauge/histogram factories.
Exposes standard Prometheus /metrics endpoint format.
"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter as PromCounter,
    Gauge as PromGauge,
    Histogram as PromHistogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# Use the default REGISTRY to share with prometheus_client
REGISTRY = CollectorRegistry()

# Default bucket boundaries
DEFAULT_TASK_BUCKETS = (0.1, 0.5, 1, 5, 10, 30, 60, 300, float("inf"))
DEFAULT_API_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
DEFAULT_HOOK_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5)


class MetricsRegistry:
    """Singleton Prometheus metrics registry.

    Provides factory methods for counters/gauges/histograms and ensures
    all metrics are registered with the shared CollectorRegistry.
    """

    _instance: "MetricsRegistry | None" = None

    def __init__(self):
        self._counters: dict[str, PromCounter] = {}
        self._gauges: dict[str, PromGauge] = {}
        self._histograms: dict[str, PromHistogram] = {}
        self._task_duration_buckets = DEFAULT_TASK_BUCKETS
        self._api_duration_buckets = DEFAULT_API_BUCKETS
        self._hook_duration_buckets = DEFAULT_HOOK_BUCKETS
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "MetricsRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ─── Factory methods ─────────────────────────────────────────────────────

    def counter(
        self,
        name: str,
        description: str,
        labels: list[str] | None = None,
    ) -> PromCounter:
        """Get or create a Counter metric."""
        if name not in self._counters:
            c = PromCounter(name, description, labels or [], registry=REGISTRY)
            self._counters[name] = c
        return self._counters[name]

    def gauge(
        self,
        name: str,
        description: str,
        labels: list[str] | None = None,
    ) -> PromGauge:
        """Get or create a Gauge metric."""
        if name not in self._gauges:
            g = PromGauge(name, description, labels or [], registry=REGISTRY)
            self._gauges[name] = g
        return self._gauges[name]

    def histogram(
        self,
        name: str,
        description: str,
        buckets: tuple[float, ...] | None = None,
        labels: list[str] | None = None,
    ) -> PromHistogram:
        """Get or create a Histogram metric."""
        if name not in self._histograms:
            h = PromHistogram(
                name,
                description,
                labels or [],
                buckets=buckets or DEFAULT_API_BUCKETS,
                registry=REGISTRY,
            )
            self._histograms[name] = h
        return self._histograms[name]

    # ─── Pre-defined metric groups ───────────────────────────────────────────

    def init_task_metrics(self) -> None:
        """Register task-related counters, gauges, and histograms."""
        self.counter(
            "hermes_task_created_total",
            "Total number of tasks created",
            ["complexity"],
        )
        self.counter(
            "hermes_task_completed_total",
            "Total number of tasks completed",
            ["complexity"],
        )
        self.counter(
            "hermes_task_failed_total",
            "Total number of tasks failed",
            ["complexity"],
        )
        self.histogram(
            "hermes_task_duration_seconds",
            "Task completion duration in seconds",
            self._task_duration_buckets,
            ["complexity"],
        )
        self.gauge(
            "hermes_task_in_flight",
            "Number of tasks currently in flight by status",
            ["status"],
        )
        self.gauge(
            "hermes_task_queue_depth",
            "Current task queue depth",
        )

    def init_agent_metrics(self) -> None:
        """Register agent-related counters and gauges."""
        self.counter(
            "hermes_agent_registered_total",
            "Total number of agents registered",
            ["role"],
        )
        self.counter(
            "hermes_agent_status_changes_total",
            "Total agent status changes",
            ["role", "status"],
        )
        self.gauge(
            "hermes_agent_active",
            "Number of currently active agents",
        )
        self.gauge(
            "hermes_agent_idle",
            "Number of currently idle agents",
        )

    def init_hook_metrics(self) -> None:
        """Register hook emission counters and histograms."""
        self.counter(
            "hermes_hooks_emitted_total",
            "Total hook emissions by event type",
            ["event"],
        )
        self.counter(
            "hermes_hooks_failed_total",
            "Total failed hook emissions by event type",
            ["event"],
        )
        self.histogram(
            "hermes_hook_handler_duration_seconds",
            "Hook handler execution duration in seconds",
            self._hook_duration_buckets,
            ["event"],
        )

    def init_api_metrics(self) -> None:
        """Register API request counters and histograms."""
        self.counter(
            "hermes_api_request_total",
            "Total API requests",
            ["method", "endpoint", "status"],
        )
        self.histogram(
            "hermes_api_request_duration_seconds",
            "API request duration in seconds",
            self._api_duration_buckets,
            ["endpoint"],
        )
        self.gauge(
            "hermes_workspace_count",
            "Number of active workspaces",
        )

    def emit_metrics(self) -> None:
        """Initialize all metric groups (idempotent)."""
        if self._initialized:
            return
        self.init_task_metrics()
        self.init_agent_metrics()
        self.init_hook_metrics()
        self.init_api_metrics()
        self._initialized = True

    # ─── Convenience helpers ─────────────────────────────────────────────────

    def task_created(self, complexity: str = "normal") -> None:
        """Increment task created counter."""
        self.counter("hermes_task_created_total", "").labels(complexity=complexity).inc()

    def task_completed(self, complexity: str = "normal", duration: float | None = None) -> None:
        """Increment task completed counter and optionally observe duration."""
        self.counter("hermes_task_completed_total", "").labels(complexity=complexity).inc()
        if duration is not None:
            self.histogram(
                "hermes_task_duration_seconds", "", self._task_duration_buckets
            ).labels(complexity=complexity).observe(duration)

    def task_failed(self, complexity: str = "normal") -> None:
        """Increment task failed counter."""
        self.counter("hermes_task_failed_total", "").labels(complexity=complexity).inc()

    def task_in_flight(self, status: str, delta: int = 1) -> None:
        """Adjust task in-flight gauge."""
        self.gauge("hermes_task_in_flight", "").labels(status=status).inc(delta)

    def task_queue_depth(self, value: int) -> None:
        """Set task queue depth gauge."""
        self.gauge("hermes_task_queue_depth", "").set(value)

    def agent_registered(self, role: str) -> None:
        """Increment agent registered counter."""
        self.counter("hermes_agent_registered_total", "").labels(role=role).inc()

    def agent_status_change(self, role: str, status: str) -> None:
        """Increment agent status change counter."""
        self.counter(
            "hermes_agent_status_changes_total", ""
        ).labels(role=role, status=status).inc()

    def agent_active(self, count: int) -> None:
        """Set active agents gauge."""
        self.gauge("hermes_agent_active", "").set(count)

    def agent_idle(self, count: int) -> None:
        """Set idle agents gauge."""
        self.gauge("hermes_agent_idle", "").set(count)

    def hook_emitted(self, event: str) -> None:
        """Increment hook emitted counter."""
        self.counter("hermes_hooks_emitted_total", "").labels(event=event).inc()

    def hook_failed(self, event: str) -> None:
        """Increment hook failed counter."""
        self.counter("hermes_hooks_failed_total", "").labels(event=event).inc()

    def hook_duration(self, event: str, duration: float) -> None:
        """Observe hook handler duration histogram."""
        self.histogram(
            "hermes_hook_handler_duration_seconds", "",
            self._hook_duration_buckets
        ).labels(event=event).observe(duration)

    def api_request(
        self, method: str, endpoint: str, status: str, duration: float | None = None
    ) -> None:
        """Record API request counter and optionally observe duration."""
        self.counter(
            "hermes_api_request_total", ""
        ).labels(method=method, endpoint=endpoint, status=status).inc()
        if duration is not None:
            self.histogram(
                "hermes_api_request_duration_seconds", "",
                self._api_duration_buckets
            ).labels(endpoint=endpoint).observe(duration)

    def workspace_count(self, count: int) -> None:
        """Set workspace count gauge."""
        self.gauge("hermes_workspace_count", "").set(count)


# ─── Prometheus exposition ─────────────────────────────────────────────────────


def get_metrics_output() -> bytes:
    """Generate Prometheus text format metrics output."""
    MetricsRegistry.get_instance().emit_metrics()
    return generate_latest(REGISTRY)


def get_content_type() -> str:
    """Return the Prometheus content type."""
    return CONTENT_TYPE_LATEST
